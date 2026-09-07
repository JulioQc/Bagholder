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
TMX_URL = "https://app-money.tmx.com/graphql"
TMX_QUOTE_QUERY = (
    "query getQuoteBySymbol($symbol: String, $locale: String) { getQuoteBySymbol(symbol: $symbol, locale: $locale) "
    "{ symbol name price dividendFrequency dividendYield dividendAmount exDividendDate } }"
)
TMX_DIVIDENDS_QUERY = (
    "query getDividendsForSymbol($symbol: String!, $page: Int, $batch: Int) { dividends: getDividendsForSymbol("
    "symbol: $symbol, page: $page, batch: $batch) { dividends { exDate payableDate amount currency } } }"
)
TMX_BATCH = 24
QUOTE_STALE_HOURS = 20
CANADIAN_EXCHANGES = ("TSX", "TSX-V", "TSXV", "CSE", "CBOE CANADA", "NEO", "ALPHA EXCHANGE")
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


def _post_json(url, payload, ssl_context=None, headers=None):
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "*/*"}
    hdrs.update(headers or {})
    req = Request(url, data=body, headers=hdrs, method="POST")
    ctx = ssl_context or default_ssl_context()
    with urlopen(req, timeout=TIMEOUT_SEC, context=ctx) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    return json.loads(raw.decode("utf-8", "replace"))


_TMX_HEADERS = {"locale": "en", "Origin": "https://money.tmx.com", "Referer": "https://money.tmx.com/"}


def tmx_symbol(symbol):
    """Wealthsimple's Canadian tickers already match TMX Money's (no suffix)."""
    s = str(symbol or "").strip().upper()
    for suffix in (".TO", ".V", ".CN", ".NE"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def is_canadian_listing(exchange, currency):
    ex = str(exchange or "").strip().upper()
    if ex:
        return ex in CANADIAN_EXCHANGES
    return str(currency or "").strip().upper() == "CAD"


def parse_tmx_quote(data):
    q = ((data or {}).get("data") or {}).get("getQuoteBySymbol") or {}
    if not isinstance(q, dict) or not q:
        return None
    ex = str(q.get("exDividendDate") or "")[:10]
    return {
        "price": q.get("price"),
        "dividendAmount": q.get("dividendAmount"),
        "dividendFrequency": str(q.get("dividendFrequency") or ""),
        "exDividendDate": ex,
        "name": str(q.get("name") or ""),
    }


def parse_tmx_dividends(data):
    block = ((data or {}).get("data") or {}).get("dividends") or {}
    rows = block.get("dividends") if isinstance(block, dict) else None
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        ex = str(r.get("exDate") or "")[:10]
        try:
            amt = float(r.get("amount"))
        except (TypeError, ValueError):
            continue
        if len(ex) == 10 and amt > 0:
            out.append({"exDate": ex, "payDate": str(r.get("payableDate") or "")[:10], "amount": amt, "currency": str(r.get("currency") or "")})
    return out


def fetch_tmx(symbol, ssl_context=None):
    """Quote + declared distribution history for one Canadian listing."""
    sym = tmx_symbol(symbol)
    if not sym:
        return None, []
    quote = None
    try:
        quote = parse_tmx_quote(_post_json(TMX_URL, {"operationName": "getQuoteBySymbol", "variables": {"symbol": sym, "locale": "en"}, "query": TMX_QUOTE_QUERY}, ssl_context, _TMX_HEADERS))
    except Exception:
        quote = None
    divs = []
    try:
        divs = parse_tmx_dividends(_post_json(TMX_URL, {"operationName": "getDividendsForSymbol", "variables": {"symbol": sym, "page": 1, "batch": TMX_BATCH}, "query": TMX_DIVIDENDS_QUERY}, ssl_context, _TMX_HEADERS))
    except Exception:
        divs = []
    return quote, divs


def stale_symbols(symbols, now=None):
    """Dividend-paying Canadian listings whose quote is older than QUOTE_STALE_HOURS."""
    now = now or datetime.now(timezone.utc)
    fetched = store.quote_fetched_at()
    out = []
    for rec in symbols or []:
        sym = tmx_symbol(rec.get("symbol"))
        if not sym or not is_canadian_listing(rec.get("exchange"), rec.get("currency")):
            continue
        last = fetched.get(sym) or ""
        try:
            age = now - datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None
        except ValueError:
            age = None
        if age is None or age > timedelta(hours=QUOTE_STALE_HOURS):
            out.append(sym)
    return out


def refresh_distributions(symbols=None, ssl_context=None, force=False):
    """Refresh quotes and declared distributions for the dividend payers."""
    recs = symbols or []
    todo = [tmx_symbol(r.get("symbol")) for r in recs if is_canadian_listing(r.get("exchange"), r.get("currency"))] if force else stale_symbols(recs)
    done = 0
    for sym in todo:
        quote, divs = fetch_tmx(sym, ssl_context)
        if quote:
            store.upsert_quote(sym, quote)
        if divs:
            store.upsert_distributions(sym, divs)
        if quote or divs:
            done += 1
    return done


def is_stale(today=None, symbols=None):
    today = today or _today()
    limit = (today - timedelta(days=STALE_DAYS)).isoformat()
    fx = store.fx_last_date()
    bench = store.benchmark_last_date()
    if (not fx or fx < limit) or (not bench or bench < limit):
        return True
    return bool(stale_symbols(symbols or []))


def refresh_all(ssl_context=None, symbols=None):
    """Refresh FX, the benchmark and the declared distributions for the given
    payer symbols. Never raises; returns row counts written."""
    global _refreshing
    with _lock:
        if _refreshing:
            return {"fx": 0, "benchmark": 0, "skipped": True}
        _refreshing = True
    try:
        return {
            "fx": refresh_fx(ssl_context),
            "benchmark": refresh_benchmark(ssl_context),
            "distributions": refresh_distributions(symbols or [], ssl_context),
            "skipped": False,
        }
    finally:
        with _lock:
            _refreshing = False


def refresh_in_background(ssl_context=None, symbols=None):
    t = threading.Thread(
        target=refresh_all, args=(ssl_context, symbols), name="bagholder-market", daemon=True
    )
    t.start()
    return t
