"""Write the shared model cases: activity rows in, the figures the spec says
they produce out, as JSON every implementation (Python, Swift, Kotlin) runs
through its own model. The Python model is the reference: run this after an
intended model change, review the diff of fixtures/cases, commit both.

    python3 fixtures/make_fixtures.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import model  # noqa: E402
from test_model import act, buy, sell  # noqa: E402

TRADE_KEYS = ("symbol", "kind", "currency", "side", "qty", "mult", "entry", "exit", "entryDate", "exitDate", "holdDays", "pnl", "pnlCad", "pnlPct", "status", "fees")
KPI_KEYS = ("count", "wins", "losses", "winRate", "realized", "expectancy", "profitFactor", "avgHold", "avgWin", "avgLoss")
POSITION_KEYS = ("symbol", "kind", "currency", "qty", "avg", "cost")
HOLDING_KEYS = ("symbol", "qty", "per", "freq", "freqVerified", "annual", "yoc", "ytd", "ttm", "all", "nextExDate", "nextPayDate", "exPast", "payPast")
TILE_KEYS = ("label", "total", "perMonth", "count", "yield", "earned", "book")


def snapshot(acts, securities=None):
    return {"activities": acts, "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": securities or []}


def dividend(id, symbol, qty, per, day, account="Cashflow"):
    return act(id=id, category="dividend", activityType="Dividend", rawType="DIVIDEND", quantity=qty, unitPrice=per, netCashAmount=round(qty * per, 2), transactionDate=day, symbol=symbol, currency="CAD", accountType=account)


def sto(id, symbol, qty, px, day, **extra):
    o = dict(id=id, category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL", quantity=-qty, unitPrice=px, netCashAmount=qty * px * 100, transactionDate=day, symbol=symbol)
    o.update(extra)
    return act(**o)


def btc(id, symbol, qty, px, day, sub="BUYTOCLOSE", **extra):
    o = dict(id=id, category="trade", activityType="OPTIONS_BUY", activitySubType=sub, rawType="OPTIONS_BUY", quantity=qty, unitPrice=px, netCashAmount=-qty * px * 100, transactionDate=day, symbol=symbol)
    o.update(extra)
    return act(**o)


def multileg(id, symbol, cash, day):
    """A Wealthsimple multileg fill as posted: quantity 0, only the cash."""
    return act(id=id, activityType="OPTIONS_MULTILEG", activitySubType="FILLED", rawType="OPTIONS_MULTILEG", quantity=0, netCashAmount=cash, transactionDate=day, symbol=symbol)


def crypto(id, kind, symbol, qty, px, day, account="Crypto"):
    raw = {"buy": "CRYPTO_BUY", "sell": "CRYPTO_SELL", "reward": "CRYPTO_STAKING_REWARD"}[kind]
    return act(id=id, activityType=raw, activitySubType="MARKET_ORDER" if kind != "reward" else "other", rawType=raw, quantity=qty, unitPrice=px, netCashAmount=qty * px, transactionDate=day, symbol=symbol, currency="CAD", accountType=account)


CASES = {
    # two share round trips in CAD: a win, then a loss, one account
    "shares_two_round_trips": {
        "today": "2026-03-01",
        "activities": [
            buy("b1", "AAA", 100, 10.0, "2026-01-05"), sell("s1", "AAA", 100, 12.0, "2026-01-20"),
            buy("b2", "AAA", 50, 12.0, "2026-02-02"), sell("s2", "AAA", 50, 11.0, "2026-02-10"),
        ],
        "market": {"fx": {}, "benchmark": {}},
    },
    # a short option sold to open and bought to close, USD, contract multiplier 100
    "option_short_then_cover": {
        "today": "2026-03-01",
        "activities": [
            act(id="sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL", quantity=-2, unitPrice=3, netCashAmount=600, transactionDate="2026-01-01", symbol="ZZZ 21AUG26 10.00 CALL"),
            act(id="btc", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOCLOSE", rawType="OPTIONS_BUY", quantity=2, unitPrice=1, netCashAmount=-200, transactionDate="2026-02-01", symbol="ZZZ 21AUG26 10.00 CALL"),
        ],
        "market": {"fx": {"2026-01-01": 1.40, "2026-02-01": 1.35}, "benchmark": {}},
    },
    # an open position with two lots, no sale yet
    "shares_open_position_two_lots": {
        "today": "2026-03-01",
        "activities": [buy("b1", "BBB", 100, 5.0, "2026-01-05"), buy("b2", "BBB", 100, 7.0, "2026-02-05")],
        "market": {"fx": {}, "benchmark": {}},
    },
    # an income holding with a declared distribution record: rate, projection, ex-div and pay day
    "cashflow_holding_with_declared_record": {
        "today": "2026-09-07",
        "activities": [
            buy("b1", "RDDY", 4000, 11.64, "2026-05-01", accountType="Cashflow"),
            dividend("d1", "RDDY", 4000, 0.15, "2026-08-06"),
            dividend("d2", "RDDY", 4000, 0.15, "2026-09-04"),
        ],
        "market": {"fx": {}, "benchmark": {},
                   "distributions": {"RDDY": [{"exDate": "2026-07-31", "payDate": "2026-08-06", "amount": 0.15, "currency": "CAD"},
                                              {"exDate": "2026-08-31", "payDate": "2026-09-04", "amount": 0.15, "currency": "CAD"},
                                              {"exDate": "2026-09-30", "payDate": "2026-10-06", "amount": 0.15, "currency": "CAD"}]}},
    },
    # a short call covered and re-sold on the same day is a roll: the cover's P&L
    # folds into the far contract's basis and only the far contract is a trade
    "option_roll_same_day_folds": {
        "today": "2027-01-01",
        "activities": [
            sto("aug-sto", "ZZZ 21AUG26 10.00 CALL", 1, 3, "2026-01-01"),
            btc("aug-cover", "ZZZ 21AUG26 10.00 CALL", 1, 1, "2026-08-15"),
            sto("jan-sto", "ZZZ 15JAN27 12.00 CALL", 1, 2, "2026-08-15"),
            btc("jan-cover", "ZZZ 15JAN27 12.00 CALL", 1, 0.5, "2026-12-01"),
        ],
        "market": {"fx": {"2026-01-01": 1.40, "2026-08-15": 1.38, "2026-12-01": 1.36}, "benchmark": {}},
    },
    # a multileg roll posts only the closing leg, with quantity 0: 16 short Jan27
    # calls rolled to Jan28, 6 more sold, all 22 bought back; nothing stays open
    "option_multileg_roll_carries_the_leg": {
        "today": "2026-09-01",
        "activities": [
            sto("sto", "LUNR 15JAN27 12.00 CALL", 16, 6.2225, "2025-10-01"),
            multileg("ml", "LUNR 15JAN27 12.00 CALL", -2160, "2025-11-14"),
            sto("sto2", "LUNR 21JAN28 12.00 CALL", 6, 6.75, "2025-12-10"),
            btc("btc", "LUNR 21JAN28 12.00 CALL", 22, 13.3, "2026-06-26", sub="BUYTOOPEN"),
        ],
        "market": {"fx": {}, "benchmark": {}},
    },
    # a credit roll up: two multileg credits on the 10 call move 5 shorts to
    # the 12 call, then the 12 calls are bought back
    "option_credit_roll_up": {
        "today": "2026-09-01",
        "activities": [
            sto("sto", "BBAI 21JAN28 10.00 CALL", 5, 3.0, "2025-11-12"),
            multileg("cr1", "BBAI 21JAN28 10.00 CALL", 14, "2026-06-09"),
            multileg("cr2", "BBAI 21JAN28 10.00 CALL", 56, "2026-06-17"),
            btc("btc", "BBAI 21JAN28 12.00 CALL", 5, 0.85, "2026-06-26", sub="BUYTOOPEN"),
        ],
        "market": {"fx": {}, "benchmark": {}},
    },
    # a posted short expiry closes the short at zero and keeps the premium
    "option_short_expiry_posted": {
        "today": "2027-02-01",
        "activities": [
            sto("sto", "ABC 15JAN27 10.00 CALL", 5, 2, "2026-01-10"),
            act(id="exp", activityType="OPTIONS_SHORT_EXPIRY", activitySubType="EXPIRED", rawType="OPTIONS_SHORT_EXPIRY", quantity=5, transactionDate="2027-01-15", symbol="ABC 15JAN27 10.00 CALL"),
        ],
        "market": {"fx": {}, "benchmark": {}},
    },
    # Wealthsimple posted no expiry row: a lot still open after its expiry date
    # closes at zero on that date; a contract not yet expired stays open
    "option_expiry_assumed": {
        "today": "2026-03-01",
        "activities": [
            sto("sto", "BBAI 02JAN26 5.50 PUT", 2, 0.3, "2025-12-05"),
            btc("bto", "ZZZ 17JUL26 10.00 CALL", 1, 1.0, "2026-01-05", sub="BUYTOOPEN"),
        ],
        "market": {"fx": {}, "benchmark": {}},
    },
    # a long option that expired worthless, posted as a long expiry
    "option_long_expiry_posted": {
        "today": "2025-09-01",
        "activities": [
            btc("bto", "LUNR 22AUG25 8.00 CALL", 2, 0.4, "2025-07-01", sub="BUYTOOPEN"),
            act(id="exp", category="option_event", activityType="EXPIR", activitySubType="BUY", rawType="OPTIONS_EXPIRY", quantity=2, transactionDate="2025-08-22", symbol="LUNR 22AUG25 8.00 CALL"),
        ],
        "market": {"fx": {}, "benchmark": {}},
    },
    # an assigned covered call: the option keeps its premium and the shares are
    # sold at the strike; the share leg is derived, Wealthsimple posts only the option
    "option_assignment_call_delivers_shares": {
        "today": "2026-09-06",
        "activities": [
            buy("b1", "ASTS", 300, 25.0, "2025-01-10", currency="USD", securityId="sec-s-asts"),
            sto("sto", "ASTS 07MAR25 31.00 CALL", 3, 1.5, "2025-02-10", securityId="sec-o-asts"),
            act(id="asg", category="option_event", activityType="ASSIGN", activitySubType="BUYTOCLOSE", rawType="OPTIONS_ASSIGN", quantity=3, unitPrice=0, netCashAmount=9300, transactionDate="2025-03-07", symbol="ASTS 07MAR25 31.00 CALL", securityId="sec-o-asts"),
        ],
        "securities": [{"id": "sec-o-asts", "symbol": "ASTS", "underlyingId": "sec-s-asts"}, {"id": "sec-s-asts", "symbol": "ASTS", "name": "AST SpaceMobile", "primaryExchange": "NASDAQ"}],
        "market": {"fx": {"2025-01-10": 1.44, "2025-02-10": 1.43, "2025-03-07": 1.43}, "benchmark": {}},
    },
    # an assigned short put buys the shares at the strike: a new open position
    "option_assignment_put_buys_shares": {
        "today": "2026-01-01",
        "activities": [
            sto("sto", "BBAI 05DEC25 5.00 PUT", 1, 0.5, "2025-11-10"),
            act(id="asg", category="option_event", activityType="ASSIGN", activitySubType="BUYTOCLOSE", rawType="OPTIONS_ASSIGN", quantity=1, unitPrice=0, netCashAmount=-500, transactionDate="2025-12-05", symbol="BBAI 05DEC25 5.00 PUT"),
        ],
        "market": {"fx": {}, "benchmark": {}},
    },
    # crypto bought, a staking reward (a lot at zero cost), then everything sold
    "crypto_buy_reward_sell": {
        "today": "2026-03-01",
        "activities": [
            crypto("cb", "buy", "ETH", 2, 100, "2026-01-01"),
            crypto("rw", "reward", "ETH", 1, 0, "2026-01-05"),
            crypto("cs", "sell", "ETH", 3, 150, "2026-02-01"),
        ],
        "market": {"fx": {}, "benchmark": {}},
    },
    # a monthly payer between ex-date and pay day: the distribution still to be
    # paid is the one shown, its ex-date passed, its pay day not
    "cashflow_between_ex_date_and_pay_day": {
        "today": "2026-09-07",
        "activities": [
            buy("b1", "EASY", 1000, 20.0, "2026-05-01", accountType="Cashflow"),
            dividend("d1", "EASY", 1000, 0.20, "2026-07-08"),
            dividend("d2", "EASY", 1000, 0.20, "2026-08-08"),
        ],
        "market": {"fx": {}, "benchmark": {},
                   "distributions": {"EASY": [{"exDate": "2026-06-30", "payDate": "2026-07-08", "amount": 0.20, "currency": "CAD"},
                                              {"exDate": "2026-07-31", "payDate": "2026-08-08", "amount": 0.20, "currency": "CAD"},
                                              {"exDate": "2026-08-31", "payDate": "2026-09-08", "amount": 0.21, "currency": "CAD"}]}},
    },
    # no declared record: the rate and frequency come from the payments received
    # (quarterly, read from the gaps), the ex-date from the quote, the pay day
    # from the last payment
    "cashflow_holding_from_payments_only": {
        "today": "2026-09-07",
        "activities": [
            buy("b1", "QQQQ", 200, 50.0, "2025-10-01", accountType="Cashflow"),
            dividend("d1", "QQQQ", 200, 0.30, "2025-12-15"),
            dividend("d2", "QQQQ", 200, 0.30, "2026-03-16"),
            dividend("d3", "QQQQ", 200, 0.32, "2026-06-15"),
        ],
        "market": {"fx": {}, "benchmark": {}, "distributions": {}, "quotes": {"QQQQ": {"exDividendDate": "2026-09-15"}}},
    },
}


def rounded(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, dict):
        return {k: rounded(x) for k, x in v.items()}
    if isinstance(v, list):
        return [rounded(x) for x in v]
    return v


def pick(d, keys):
    return {k: d[k] for k in keys if k in d}


def expect_from(snap, market, today, filters):
    """What every implementation must produce for one case."""
    base = model.build_base(snap, market, {}, today=today)
    view = model.build_view(base, filters)
    trades = sorted(view["trades"], key=lambda t: (t["entryDate"], t["exitDate"], t["symbol"]))
    out = {
        "kpi": pick(view["kpi"], KPI_KEYS),
        "trades": [dict(pick(t, TRADE_KEYS), fills=[f["sub"] for f in sorted(t["fills"], key=lambda f: f["when"])]) for t in trades],
        "positions": [pick(p, POSITION_KEYS) for p in sorted(view["positions"], key=lambda p: p["symbol"])],
    }
    if any(a.get("category") == "dividend" for a in snap.get("activities") or []):
        out["cashflowHoldings"] = [pick(h, HOLDING_KEYS) for h in sorted(view["cashflow"]["holdings"], key=lambda h: h["symbol"])]
        out["cashflowTiles"] = [pick(t, TILE_KEYS) for t in view["cashflow"]["tiles"]]
    return rounded(out)


def expect(case):
    return expect_from(snapshot(case["activities"], case.get("securities")), case["market"], case["today"], {})


def main():
    for name, case in CASES.items():
        doc = {"today": case["today"], "snapshot": snapshot(case["activities"], case.get("securities")), "market": case["market"], "filters": {}, "expect": expect(case)}
        path = os.path.join(HERE, "cases", name + ".json")
        with open(path, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
        print("wrote", os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
