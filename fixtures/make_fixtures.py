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
HOLDING_KEYS = ("symbol", "qty", "per", "annual", "yoc", "nextExDate", "nextPayDate", "exPast", "payPast")


def snapshot(acts):
    return {"activities": acts, "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": []}


def dividend(id, symbol, qty, per, day, account="Cashflow"):
    return act(id=id, category="dividend", activityType="Dividend", rawType="DIVIDEND", quantity=qty, unitPrice=per, netCashAmount=round(qty * per, 2), transactionDate=day, symbol=symbol, currency="CAD", accountType=account)


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


def expect(case):
    base = model.build_base(snapshot(case["activities"]), case["market"], {}, today=case["today"])
    view = model.build_view(base, {})
    trades = sorted(view["trades"], key=lambda t: (t["entryDate"], t["exitDate"], t["symbol"]))
    out = {
        "kpi": pick(view["kpi"], KPI_KEYS),
        "trades": [dict(pick(t, TRADE_KEYS), fills=[f["sub"] for f in sorted(t["fills"], key=lambda f: f["when"])]) for t in trades],
        "positions": [pick(p, POSITION_KEYS) for p in sorted(view["positions"], key=lambda p: p["symbol"])],
    }
    if case["market"].get("distributions"):
        out["cashflowHoldings"] = [pick(h, HOLDING_KEYS) for h in sorted(view["cashflow"]["holdings"], key=lambda h: h["symbol"])]
    return rounded(out)


def main():
    for name, case in CASES.items():
        doc = {"today": case["today"], "snapshot": snapshot(case["activities"]), "market": case["market"], "filters": {}, "expect": expect(case)}
        path = os.path.join(HERE, "cases", name + ".json")
        with open(path, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
        print("wrote", os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
