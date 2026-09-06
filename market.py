"""Market data the derived model needs but Wealthsimple does not provide.

- USD/CAD daily average rate from the Bank of Canada Valet API (FXUSDCAD).
- S&P 500 index closes from FRED (SP500), with Stooq (^spx) as a fallback.

Both are persisted in SQLite (store.fx_rates / store.benchmark_prices) and
refreshed incrementally: only days after the newest stored date are fetched.
Every public function swallows network errors and returns what is stored.
"""

from __future__ import annotations

import gzip
import json
import os
import ssl
import threading
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

import store

BOC_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500"
STOOQ_URL = "https://stooq.com/q/d/l/?s=^spx&i=d"
FX_START = "2016-01-01"
TIMEOUT_SEC = 30
STALE_DAYS = 4
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

_lock = threading.Lock()
_refreshing = False
_SSL_CTX = None


def default_ssl_context():
    """Same CA lookup as bagholder._ssl_context: certifi, then system bundles."""
    global _SSL_CTX
    if _SSL_CTX is not None:
        return _SSL_CTX
    ca_files = []
    try:
        import certifi

        ca_files.append(certifi.where())
    except Exception:
        pass
    ca_files.extend(
        (
            "/etc/ssl/cert.pem",
            "/etc/ssl/certs/ca-certificates.crt",
            "/opt/homebrew/etc/openssl@3/cert.pem",
            "/usr/local/etc/openssl@3/cert.pem",
            "/opt/homebrew/etc/openssl@1.1/cert.pem",
        )
    )
    for path in ca_files:
        if path and os.path.isfile(path):
            try:
                _SSL_CTX = ssl.create_default_context(cafile=path)
                return _SSL_CTX
            except Exception:
                continue
    _SSL_CTX = ssl.create_default_context()
    return _SSL_CTX


def _today():
    return datetime.now(timezone.utc).date()


def _get_text(url, ssl_context=None):
    req = Request(url, headers={"User-Agent": UA, "Accept": "text/csv,application/json,*/*;q=0.8"})
    ctx = ssl_context or default_ssl_context()
    with urlopen(req, timeout=TIMEOUT_SEC, context=ctx) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    return raw.decode("utf-8", "replace")


def parse_boc_json(text):
    """{"observations":[{"d":"2024-01-02","FXUSDCAD":{"v":"1.3316"}}]} -> {date: rate}"""
    out = {}
    try:
        data = json.loads(text or "")
    except ValueError:
        return out
    for ob in (data or {}).get("observations") or []:
        if not isinstance(ob, dict):
            continue
        d = str(ob.get("d") or "")[:10]
        cell = ob.get("FXUSDCAD") or {}
        try:
            v = float((cell or {}).get("v"))
        except (TypeError, ValueError):
            continue
        if len(d) == 10 and v > 0:
            out[d] = v
    return out


def parse_fred_csv(text):
    """observation_date,SP500 rows; '.' marks a holiday and is skipped."""
    out = {}
    for line in str(text or "").splitlines():
        parts = line.split(",")
        if len(parts) < 2:
            continue
        d = parts[0].strip()
        raw = parts[1].strip()
        if len(d) != 10 or d[4] != "-" or d[7] != "-" or not raw or raw == ".":
            continue
        try:
            px = float(raw)
        except ValueError:
            continue
        if px > 0:
            out[d] = px
    return out


def parse_stooq_csv(text):
    """Date,Open,High,Low,Close,Volume -> {date: close}"""
    out = {}
    for line in str(text or "").splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        d = parts[0].strip()
        try:
            px = float(parts[4])
        except ValueError:
            continue
        if len(d) == 10 and px > 0:
            out[d] = px
    return out


def refresh_fx(ssl_context=None):
    """Fetch USD/CAD days after the newest stored one (with a small overlap)."""
    last = store.fx_last_date()
    if last:
        start = (date.fromisoformat(last) - timedelta(days=7)).isoformat()
    else:
        start = FX_START
    url = "%s?start_date=%s" % (BOC_URL, start)
    try:
        rates = parse_boc_json(_get_text(url, ssl_context))
    except Exception:
        return 0
    return store.upsert_fx_rates(rates)


def refresh_benchmark(ssl_context=None):
    """S&P 500 closes. FRED serves the trailing ten years in one file."""
    mapping = {}
    try:
        mapping = parse_fred_csv(_get_text(FRED_URL, ssl_context))
    except Exception:
        mapping = {}
    if not mapping:
        try:
            mapping = parse_stooq_csv(_get_text(STOOQ_URL, ssl_context))
        except Exception:
            mapping = {}
    if not mapping:
        return 0
    last = store.benchmark_last_date()
    if last:
        cutoff = (date.fromisoformat(last) - timedelta(days=7)).isoformat()
        mapping = {d: v for d, v in mapping.items() if d >= cutoff}
    return store.upsert_benchmark_prices(mapping)


def is_stale(today=None):
    today = today or _today()
    limit = (today - timedelta(days=STALE_DAYS)).isoformat()
    fx = store.fx_last_date()
    bench = store.benchmark_last_date()
    return (not fx or fx < limit) or (not bench or bench < limit)


def refresh_all(ssl_context=None):
    """Refresh both series. Never raises; returns row counts written."""
    global _refreshing
    with _lock:
        if _refreshing:
            return {"fx": 0, "benchmark": 0, "skipped": True}
        _refreshing = True
    try:
        return {
            "fx": refresh_fx(ssl_context),
            "benchmark": refresh_benchmark(ssl_context),
            "skipped": False,
        }
    finally:
        with _lock:
            _refreshing = False


def refresh_in_background(ssl_context=None):
    t = threading.Thread(
        target=refresh_all, args=(ssl_context,), name="bagholder-market", daemon=True
    )
    t.start()
    return t
