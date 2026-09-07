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
import re
import ssl
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen

import store

BOC_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500"
STOOQ_URL = "https://stooq.com/q/d/l/?s=^spx&i=d"
TMX_URL = "https://app-money.tmx.com/graphql"
TMX_QUOTE_QUERY = (
    "query getQuoteBySymbol($symbol: String, $locale: String) { getQuoteBySymbol(symbol: $symbol, locale: $locale) "
    "{ symbol name price priceChange percentChange prevClose currency dividendFrequency dividendYield dividendAmount exDividendDate } }"
)
QUOTE_REFRESH_MINUTES = 1
MARKET_CHECK_MINUTES = 60
US_EXCHANGES = ("NASDAQ", "NYSE", "NYSE AMERICAN", "NYSE ARCA", "BATS", "AMEX", "ARCA", "CBOE", "IEX")
TMX_DIVIDENDS_QUERY = (
    "query getDividendsForSymbol($symbol: String!, $page: Int, $batch: Int) { dividends: getDividendsForSymbol("
    "symbol: $symbol, page: $page, batch: $batch) { dividends { exDate payableDate amount currency } } }"
)
TMX_BATCH = 24
QUOTE_STALE_HOURS = 20
COINBASE_URL = "https://api.coinbase.com/v2/prices/%s/spot"
CBOE_CA_URL = "https://www-api.cboe.com/ca/equities/securities-1/%s/quote/"
CBOE_OPTIONS_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/%s.json"
CBOE_CANADA_EXCHANGES = ("CBOE CANADA", "NEO")
TMX_HISTORY_QUERY = (
    "query getTimeSeriesData($symbol: String!, $freq: String, $interval: Int, $start: String, $end: String) "
    "{ getTimeSeriesData(symbol: $symbol, freq: $freq, interval: $interval, start: $start, end: $end) { dateTime open high low close volume } }"
)
CBOE_CA_HISTORY_URL = "https://www-api.cboe.com/ca/equities/securities-1/%s/trading-activity-historical/"
COINGECKO_SEARCH_URL = "https://api.coingecko.com/api/v3/search?query=%s"
COINGECKO_RANGE_URL = "https://api.coingecko.com/api/v3/coins/%s/market_chart/range?vs_currency=%s&from=%d&to=%d&interval=daily"
COINGECKO_MAX_DAYS = 365
HISTORY_STALE_HOURS = 20
RECORD_STALE_HOURS = QUOTE_STALE_HOURS
MARKET_ATTEMPT_HOURS = 6
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


def tmx_quote_symbol(symbol, exchange, currency):
    """TMX Money symbol for a listing: bare for Canadian listings, ':US' for
    US listings. None when TMX does not carry it (Cboe Canada, crypto, options)."""
    s = tmx_symbol(symbol)
    if not s or " " in s:
        return None
    ex = str(exchange or "").strip().upper()
    if ex in US_EXCHANGES or (not ex and str(currency or "").upper() == "USD"):
        return s + ":US"
    if ex in ("TSX", "TSX-V", "TSXV", "CSE", "") or (not ex and str(currency or "").upper() == "CAD"):
        return s
    return None


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
        "priceChange": q.get("priceChange"),
        "percentChange": q.get("percentChange"),
        "prevClose": q.get("prevClose"),
        "currency": str(q.get("currency") or ""),
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


def fetch_tmx_quote(tmx_sym, ssl_context=None):
    try:
        return parse_tmx_quote(_post_json(TMX_URL, {"operationName": "getQuoteBySymbol", "variables": {"symbol": tmx_sym, "locale": "en"}, "query": TMX_QUOTE_QUERY}, ssl_context, _TMX_HEADERS))
    except Exception:
        return None


def _num(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


_OCC_WORDY = re.compile(r"^([A-Z][A-Z0-9.]{0,9}) (\d{1,2})([A-Z]{3})(\d{2}) (\d+(?:\.\d+)?) (CALL|PUT|C|P)$")
_OCC_COMPACT = re.compile(r"^([A-Z][A-Z0-9.]{0,9}) (\d{6}[CP]\d{8})$")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def occ_code(symbol):
    """'QNC 20NOV26 3.00 CALL' -> 'QNC261120C00003000' (the OCC code Cboe keys its chains by)."""
    u = re.sub(r"\s+", " ", str(symbol or "").strip().upper())
    m = _OCC_COMPACT.match(u)
    if m:
        return m.group(1) + m.group(2)
    m = _OCC_WORDY.match(u)
    if not m or m.group(3) not in _MONTHS:
        return ""
    root, day, mon, yy, strike, right = m.groups()
    return "%s%s%02d%02d%s%08d" % (root, yy, _MONTHS.index(mon) + 1, int(day), right[0], int(round(float(strike) * 1000)))


def occ_root(code):
    m = re.match(r"^([A-Z][A-Z0-9.]{0,9})\d{6}[CP]\d{8}$", str(code or ""))
    return m.group(1) if m else ""


def quote_source(rec):
    """(source, key) for a held instrument, or None when no public source covers it.
    tmx: TMX Money symbol. cboe_ca: Cboe Canada symbol. coinbase: 'BTC-CAD' pair in
    the position's own currency. cboe_options: OCC code, US-listed underlyings only."""
    kind = str(rec.get("kind") or "Shares")
    sym = tmx_symbol(rec.get("symbol"))
    ccy = str(rec.get("currency") or "CAD").strip().upper()
    if not sym:
        return None
    if kind == "Crypto":
        return ("coinbase", "%s-%s" % (sym, ccy))
    if kind == "Options":
        code = occ_code(rec.get("symbol"))
        return ("cboe_options", code) if code and ccy == "USD" else None
    if kind != "Shares":
        return None
    if str(rec.get("exchange") or "").strip().upper() in CBOE_CANADA_EXCHANGES:
        return ("cboe_ca", sym)
    q = tmx_quote_symbol(rec.get("symbol"), rec.get("exchange"), rec.get("currency"))
    return ("tmx", q) if q else None


def parse_coinbase(text, pair=""):
    d = (json.loads(text or "{}") or {}).get("data") or {}
    px = _num(d.get("amount"), None)
    if not px or px <= 0:
        return None
    return {"price": px, "currency": str(d.get("currency") or pair.split("-")[-1])}


def parse_cboe_ca_quote(text):
    """Cboe Canada's own quote feed. Outside a session 'last' is 0: use the previous close."""
    d = (json.loads(text or "{}") or {}).get("data") or {}
    last = _num(d.get("last"), None)
    prev = _num(d.get("prev_close"), None)
    px = last if last and last > 0 else prev
    if not px or px <= 0:
        return None
    return {"price": px, "priceChange": _num(d.get("change"), None), "percentChange": _num(d.get("change_pct"), None), "prevClose": prev, "currency": "CAD", "name": str(d.get("company_name") or "")}


def parse_cboe_options(text):
    """OCC code -> row for one underlying's delayed chain."""
    d = (json.loads(text or "{}") or {}).get("data") or {}
    return {str(o.get("option") or ""): o for o in d.get("options") or [] if isinstance(o, dict)}


def option_mark(row):
    """Price of one contract per share: the bid/ask midpoint while both are quoted,
    else the last trade, else the previous close."""
    if not isinstance(row, dict):
        return None
    bid, ask = _num(row.get("bid"), 0.0), _num(row.get("ask"), 0.0)
    prev = _num(row.get("prev_day_close"), None)
    if bid > 0 and ask > 0:
        px = (bid + ask) / 2
    else:
        px = _num(row.get("last_trade_price"), None) or prev
    if not px or px <= 0:
        return None
    return {"price": px, "prevClose": prev, "priceChange": (px - prev) if prev else None, "percentChange": ((px / prev - 1) * 100) if prev else None, "currency": "USD"}


def fetch_coinbase_spot(pair, ssl_context=None):
    try:
        return parse_coinbase(_get_text(COINBASE_URL % pair, ssl_context), pair)
    except Exception:
        return None


def fetch_cboe_ca_quote(sym, ssl_context=None):
    try:
        return parse_cboe_ca_quote(_get_text(CBOE_CA_URL % sym, ssl_context))
    except Exception:
        return None


def fetch_cboe_option_chain(root, ssl_context=None):
    try:
        return parse_cboe_options(_get_text(CBOE_OPTIONS_URL % root, ssl_context))
    except Exception:
        return {}


def quote_symbols_needing_refresh(symbols, now=None, max_age_minutes=QUOTE_REFRESH_MINUTES):
    """[(stored symbol, source, key)] for held instruments whose quote is older than max_age."""
    now = now or datetime.now(timezone.utc)
    fetched = store.quote_fetched_at()
    out = []
    seen = set()
    for rec in symbols or []:
        sym = tmx_symbol(rec.get("symbol"))
        src = quote_source(rec)
        if not sym or not src or sym in seen:
            continue
        seen.add(sym)
        last = fetched.get(sym) or ""
        try:
            age = now - datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None
        except ValueError:
            age = None
        if age is None or age > timedelta(minutes=max_age_minutes):
            out.append((sym, src[0], src[1]))
    return out


def refresh_quotes(symbols, ssl_context=None, now=None):
    """Live-ish prices for held positions, at most every QUOTE_REFRESH_MINUTES.
    Shares and ETFs from TMX Money or Cboe Canada, crypto from Coinbase in the
    position's currency, US-listed options from Cboe's delayed chains."""
    done = 0
    chains = {}
    for sym, source, key in quote_symbols_needing_refresh(symbols, now=now):
        rec = None
        if source == "tmx":
            rec = fetch_tmx_quote(key, ssl_context)
        elif source == "cboe_ca":
            rec = fetch_cboe_ca_quote(key, ssl_context)
        elif source == "coinbase":
            rec = fetch_coinbase_spot(key, ssl_context)
        elif source == "cboe_options":
            root = occ_root(key)
            if root not in chains:
                chains[root] = fetch_cboe_option_chain(root, ssl_context)
            rec = option_mark(chains[root].get(key))
        if rec and rec.get("price") is not None:
            rec = dict(rec, source=source)
            store.upsert_quote(sym, rec, source=source)
            done += 1
    return done


def stale_symbols(symbols, now=None):
    """Dividend-paying Canadian listings whose declared distribution record
    is older than RECORD_STALE_HOURS. The record has its own fetch stamp: the
    quote loop keeps quotes fresh every few minutes, and that must not make
    the fund's distribution history look fresh."""
    now = now or datetime.now(timezone.utc)
    fetched = store.distributions_fetched_at()
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
        if age is None or age > timedelta(hours=RECORD_STALE_HOURS):
            out.append(sym)
    return out


def refresh_distributions(symbols=None, ssl_context=None, force=False, now=None):
    """Refresh quotes and declared distributions for the dividend payers."""
    recs = symbols or []
    now = now or datetime.now(timezone.utc)
    todo = [tmx_symbol(r.get("symbol")) for r in recs if is_canadian_listing(r.get("exchange"), r.get("currency"))] if force else stale_symbols(recs, now=now)
    done = 0
    for sym in todo:
        quote, divs = fetch_tmx(sym, ssl_context)
        if quote:
            store.upsert_quote(sym, quote)
        if divs:
            store.upsert_distributions(sym, divs)
        if quote or divs:
            store.mark_distributions_fetched(sym, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
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
        store.set_meta("market_attempt_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        return {
            "fx": refresh_fx(ssl_context),
            "benchmark": refresh_benchmark(ssl_context),
            "distributions": refresh_distributions(symbols or [], ssl_context),
            "skipped": False,
        }
    finally:
        with _lock:
            _refreshing = False


BOC_PUBLISH_ET = (16, 30)


def fx_day_published_but_missing(now=None):
    """True once the Bank of Canada has published today's rate (16:30 Eastern on a
    weekday) and the stored table does not have it yet, so a trade made today is
    converted at its own day's rate the same afternoon."""
    now = now or datetime.now(timezone.utc)
    et = now.astimezone(ZoneInfo("America/Toronto"))
    if et.weekday() > 4 or (et.hour, et.minute) < BOC_PUBLISH_ET:
        return False
    return (store.fx_last_date() or "") < et.date().isoformat()


# --------------------------------------------------------------------------
# daily price history for the trade chart
# --------------------------------------------------------------------------


def parse_tmx_history(data):
    rows = ((data or {}).get("data") or {}).get("getTimeSeriesData") or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = str(r.get("dateTime") or "")[:10]
        if len(d) == 10:
            out.append({"date": d, "open": r.get("open"), "high": r.get("high"), "low": r.get("low"), "close": r.get("close"), "volume": r.get("volume")})
    out.sort(key=lambda b: b["date"])
    return out


def parse_cboe_ca_history(text):
    rows = (json.loads(text or "{}") or {}).get("data") or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = str(r.get("date") or "")[:10]
        if len(d) == 10:
            out.append({"date": d, "open": r.get("open"), "high": r.get("high"), "low": r.get("low"), "close": r.get("close"), "volume": r.get("volume")})
    out.sort(key=lambda b: b["date"])
    return out


def parse_coingecko_range(text):
    """CoinGecko gives one price per day (no open/high/low): close only."""
    d = json.loads(text or "{}") or {}
    out = {}
    for ts, px in d.get("prices") or []:
        try:
            day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            continue
        if px and px > 0:
            out[day] = {"date": day, "open": None, "high": None, "low": None, "close": px, "volume": None}
    return [out[k] for k in sorted(out)]


def coingecko_id(symbol, ssl_context=None):
    """CoinGecko's id for a crypto symbol, remembered once found."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return ""
    key = "coingecko_id:" + sym
    cached = store.get_meta(key)
    if cached:
        return cached
    try:
        d = json.loads(_get_text(COINGECKO_SEARCH_URL % sym, ssl_context) or "{}") or {}
    except Exception:
        return ""
    hits = [c for c in d.get("coins") or [] if str(c.get("symbol") or "").upper() == sym and c.get("id")]
    hits.sort(key=lambda c: c.get("market_cap_rank") or 10 ** 9)
    if not hits:
        return ""
    store.set_meta(key, hits[0]["id"])
    return hits[0]["id"]


def history_source(rec):
    """(source, key) for daily bars, or None when nothing public covers the instrument."""
    src = quote_source(rec)
    if not src:
        return None
    source, key = src
    if source == "tmx":
        return ("tmx", key)
    if source == "cboe_ca":
        return ("cboe_ca", key)
    if source == "coinbase":
        return ("coingecko", key)
    return None


def fetch_history(rec, start, end, ssl_context=None):
    """Daily bars for one instrument between two dates, oldest first."""
    src = history_source(rec)
    if not src:
        return [], ""
    source, key = src
    try:
        if source == "tmx":
            data = _post_json(TMX_URL, {"operationName": "getTimeSeriesData", "variables": {"symbol": key, "freq": "day", "interval": 1, "start": start, "end": end}, "query": TMX_HISTORY_QUERY}, ssl_context, _TMX_HEADERS)
            return parse_tmx_history(data), source
        if source == "cboe_ca":
            return parse_cboe_ca_history(_get_text(CBOE_CA_HISTORY_URL % key, ssl_context)), source
        if source == "coingecko":
            sym, ccy = key.split("-", 1)
            cid = coingecko_id(sym, ssl_context)
            if not cid:
                return [], ""
            end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            start_dt = max(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc), end_dt - timedelta(days=COINGECKO_MAX_DAYS))
            return parse_coingecko_range(_get_text(COINGECKO_RANGE_URL % (cid, ccy.lower(), int(start_dt.timestamp()), int(end_dt.timestamp())), ssl_context)), source
    except Exception:
        return [], ""
    return [], ""


def ensure_history(rec, start, end, ssl_context=None, now=None):
    """Stored bars for [start, end], fetching when the span was never fetched or
    the copy is older than HISTORY_STALE_HOURS and the span reaches the present."""
    now = now or datetime.now(timezone.utc)
    sym = tmx_symbol(rec.get("symbol"))
    start, end = str(start or "")[:10], str(end or "")[:10]
    if not sym or len(start) != 10 or len(end) != 10:
        return []
    last = store.history_fetch(sym)
    covered = bool(last) and last["start"] <= start
    fresh = False
    if last:
        try:
            fresh = now - datetime.fromisoformat(last["fetchedAt"].replace("Z", "+00:00")) < timedelta(hours=HISTORY_STALE_HOURS)
        except ValueError:
            fresh = False
    today = now.date().isoformat()
    needs_recent = end >= (now.date() - timedelta(days=3)).isoformat()
    if not covered or (needs_recent and not fresh):
        fetch_from = start if not covered else min(start, last["start"])
        bars, source = fetch_history(rec, fetch_from, today, ssl_context)
        if bars:
            store.upsert_price_history(sym, bars, source)
            store.mark_history_fetched(sym, fetch_from, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return store.price_history(sym, start, end)


def refresh_periodic(ssl_context=None, symbols=None, now=None):
    """What the background loop runs every few minutes: USD/CAD and the
    S&P 500 at most every MARKET_ATTEMPT_HOURS, and the declared distribution
    record of every payer whose copy is older than RECORD_STALE_HOURS.
    Never raises; returns row counts written."""
    global _refreshing
    with _lock:
        if _refreshing:
            return {"fx": 0, "benchmark": 0, "distributions": 0, "skipped": True}
        _refreshing = True
    try:
        now = now or datetime.now(timezone.utc)
        out = {"fx": 0, "benchmark": 0, "distributions": 0, "skipped": False}
        last = store.get_meta("market_attempt_at")
        try:
            age = now - datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None
        except ValueError:
            age = None
        if age is None or age > timedelta(hours=MARKET_ATTEMPT_HOURS) or fx_day_published_but_missing(now):
            store.set_meta("market_attempt_at", now.strftime("%Y-%m-%dT%H:%M:%SZ"))
            out["fx"] = refresh_fx(ssl_context)
            out["benchmark"] = refresh_benchmark(ssl_context)
        out["distributions"] = refresh_distributions(symbols or [], ssl_context, now=now)
        return out
    finally:
        with _lock:
            _refreshing = False


def refresh_in_background(ssl_context=None, symbols=None):
    t = threading.Thread(
        target=refresh_all, args=(ssl_context, symbols), name="bagholder-market", daemon=True
    )
    t.start()
    return t
