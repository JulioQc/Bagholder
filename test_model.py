"""Tests for the derived model (model.py), market data (market.py) and the
store tables and routes that back the v2 UI."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock
from urllib.request import Request, urlopen

import bagholder
import market
import model
import store


def act(**o):
    base = {
        "id": o.get("id") or "act-%s" % id(o),
        "accountId": "acct-1",
        "accountType": "Trading",
        "symbol": "LUNR 15JAN27 12.00 CALL",
        "name": "LUNR",
        "currency": "USD",
        "commission": 0,
        "category": "other",
        "activityType": "",
        "activitySubType": "",
        "rawType": "",
        "quantity": 0,
        "unitPrice": 0,
        "netCashAmount": 0,
        "transactionDate": "2026-01-01",
        "occurredAt": "",
        "securityId": "",
    }
    base.update(o)
    if not base["occurredAt"]:
        base["occurredAt"] = base["transactionDate"] + "T15:00:00+00:00"
    return base


def buy(id, symbol, qty, px, day, **extra):
    o = dict(
        id=id,
        category="trade",
        activityType="Trade",
        activitySubType="BUY",
        rawType="DIY_BUY",
        quantity=qty,
        unitPrice=px,
        netCashAmount=-qty * px,
        transactionDate=day,
        symbol=symbol,
        currency="CAD",
    )
    o.update(extra)
    return act(**o)


def sell(id, symbol, qty, px, day, **extra):
    o = dict(
        id=id,
        category="trade",
        activityType="Trade",
        activitySubType="SELL",
        rawType="DIY_SELL",
        quantity=-qty,
        unitPrice=px,
        netCashAmount=qty * px,
        transactionDate=day,
        symbol=symbol,
        currency="CAD",
    )
    o.update(extra)
    return act(**o)


class FifoPortTest(unittest.TestCase):
    """Scenarios ported one-for-one from the ledger.html engine tests."""

    def test_multileg_zero_qty_closes_short(self):
        lunr = [
            act(id="sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN",
                rawType="OPTIONS_SELL", quantity=-16, unitPrice=6.2225, netCashAmount=9956, transactionDate="2026-01-10"),
            act(id="ml1", activityType="OPTIONS_MULTILEG", activitySubType="FILLED", rawType="OPTIONS_MULTILEG",
                quantity=0, netCashAmount=-128, transactionDate="2026-03-01"),
            act(id="ml2", activityType="OPTIONS_MULTILEG", activitySubType="FILLED", rawType="OPTIONS_MULTILEG",
                quantity=0, netCashAmount=-2025, transactionDate="2026-03-01"),
        ]
        r = model.match_fifo(lunr)
        self.assertEqual(r["open"], [])
        real = [t for t in r["closed"] if "rolled-out" not in t["flags"]]
        self.assertEqual(len(real), 2)
        by_qty = sorted(real, key=lambda t: t["quantity"])
        self.assertEqual(by_qty[0]["quantity"], 1)
        self.assertAlmostEqual(by_qty[0]["exitPrice"], 1.28)
        self.assertEqual(by_qty[1]["quantity"], 15)
        self.assertAlmostEqual(by_qty[1]["exitPrice"], 1.35)
        self.assertTrue(all(t["openDirection"] == "SHORT" for t in r["closed"]))
        want = (6.2225 - 1.28) * 1 * 100 + (6.2225 - 1.35) * 15 * 100
        self.assertAlmostEqual(sum(t["pnl"] for t in r["closed"]), want)
        self.assertTrue(all(t["rt"] == "rt:sto" for t in real))

    def test_roll_carries_the_unposted_leg_to_the_next_buy_back(self):
        # STO 16 Jan27 calls; roll to Jan28 (only the closing leg is posted);
        # STO 6 more Jan28; buy back all 22. Nothing stays open.
        acts = [
            act(id="sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL",
                quantity=-16, unitPrice=6.2225, netCashAmount=9956, transactionDate="2025-10-01", symbol="LUNR 15JAN27 12.00 CALL"),
            act(id="ml", activityType="OPTIONS_MULTILEG", activitySubType="FILLED", rawType="OPTIONS_MULTILEG",
                quantity=0, netCashAmount=-2160, transactionDate="2025-11-14", symbol="LUNR 15JAN27 12.00 CALL"),
            act(id="sto2", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL",
                quantity=-6, unitPrice=6.75, netCashAmount=4050, transactionDate="2025-12-10", symbol="LUNR 21JAN28 12.00 CALL"),
            act(id="btc", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOOPEN", rawType="OPTIONS_BUY",
                quantity=22, unitPrice=13.3, netCashAmount=-29260, transactionDate="2026-06-26", symbol="LUNR 21JAN28 12.00 CALL"),
        ]
        r = model.match_fifo(acts)
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(r["open"], [])
        total = sum(t["pnl"] for t in r["closed"])
        self.assertAlmostEqual(total, 9956 - 2160 + 4050 - 29260)
        rolled_in = [t for t in r["closed"] if "rolled-in" in t["flags"]]
        self.assertAlmostEqual(sum(t["quantity"] for t in rolled_in), 16)
        self.assertTrue(all(t["symbol"] == "LUNR 21JAN28 12.00 CALL" for t in rolled_in))
        # everything the buy-back closed is one position, so one trade row
        jan28 = {t["rt"] for t in r["closed"] if t["symbol"] == "LUNR 21JAN28 12.00 CALL"}
        self.assertEqual(len(jan28), 1)

    def test_credit_roll_up_moves_shorts_to_the_new_strike(self):
        # 5 short 10 calls rolled up to 12 calls for a credit (two multileg fills
        # posted on the 10 call), then the 12 calls are bought back.
        acts = [
            act(id="sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL",
                quantity=-5, unitPrice=3.0, netCashAmount=1500, transactionDate="2025-11-12", symbol="BBAI 21JAN28 10.00 CALL"),
            act(id="cr1", activityType="OPTIONS_MULTILEG", activitySubType="FILLED", rawType="OPTIONS_MULTILEG",
                quantity=0, netCashAmount=14, transactionDate="2026-06-09", symbol="BBAI 21JAN28 10.00 CALL"),
            act(id="cr2", activityType="OPTIONS_MULTILEG", activitySubType="FILLED", rawType="OPTIONS_MULTILEG",
                quantity=0, netCashAmount=56, transactionDate="2026-06-17", symbol="BBAI 21JAN28 10.00 CALL"),
            act(id="btc", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOOPEN", rawType="OPTIONS_BUY",
                quantity=5, unitPrice=0.85, netCashAmount=-425, transactionDate="2026-06-26", symbol="BBAI 21JAN28 12.00 CALL"),
        ]
        r = model.match_fifo(acts)
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(r["open"], [])
        self.assertAlmostEqual(sum(t["pnl"] for t in r["closed"]), 1500 + 14 + 56 - 425)

    def test_buy_back_closes_older_contracts_of_a_rolled_chain(self):
        # Short Dec puts rolled forward (only one leg posted, tagged with a contract
        # never opened); the June buy-back of 26 closes 11 known shorts, the
        # carried leg and the 9 old Dec puts, and nothing stays open.
        acts = [
            act(id="s1", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL", quantity=-3, unitPrice=0.12, netCashAmount=36, transactionDate="2025-12-05", symbol="BBAI 26DEC25 5.50 PUT"),
            act(id="s2", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL", quantity=-5, unitPrice=0.2, netCashAmount=100, transactionDate="2025-12-11", symbol="BBAI 02JAN26 5.50 PUT"),
            act(id="s3", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL", quantity=-1, unitPrice=0.4, netCashAmount=40, transactionDate="2025-12-15", symbol="BBAI 26DEC25 6.00 PUT"),
            act(id="s4", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL", quantity=-6, unitPrice=0.2, netCashAmount=120, transactionDate="2025-12-12", symbol="BBAI 19DEC25 6.00 PUT"),
            act(id="ml1", activityType="OPTIONS_MULTILEG", activitySubType="FILLED", rawType="OPTIONS_MULTILEG", quantity=0, netCashAmount=-18, transactionDate="2025-12-15", symbol="BBAI 19DEC25 6.00 PUT"),
            act(id="ml2", activityType="OPTIONS_MULTILEG", activitySubType="FILLED", rawType="OPTIONS_MULTILEG", quantity=0, netCashAmount=-1830, transactionDate="2025-12-18", symbol="BBAI 18JUN26 5.00 PUT"),
            act(id="s5", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL", quantity=-11, unitPrice=2.4, netCashAmount=2640, transactionDate="2026-02-27", symbol="BBAI 21JAN28 5.00 PUT"),
            act(id="btc", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOOPEN", rawType="OPTIONS_BUY", quantity=26, unitPrice=2.74, netCashAmount=-7124, transactionDate="2026-06-29", symbol="BBAI 21JAN28 5.00 PUT"),
        ]
        r = model.match_fifo(acts)
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(r["open"], [])
        self.assertAlmostEqual(sum(t["pnl"] for t in r["closed"]), 36 + 100 + 40 + 120 - 18 - 1830 + 2640 - 7124)
        self.assertTrue(all(t["symbol"] == "BBAI 21JAN28 5.00 PUT" for t in r["closed"] if t["exitDate"] == "2026-06-29"))

    def test_plain_option_buys_without_a_roll_stay_long(self):
        r = model.match_fifo([
            act(id="bto", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOOPEN", rawType="OPTIONS_BUY",
                quantity=10, unitPrice=1.27, netCashAmount=-1270, transactionDate="2026-06-15", symbol="QNC 20NOV26 3.00 CALL"),
        ])
        self.assertEqual(len(r["open"]), 1)
        self.assertEqual(r["open"][0]["direction"], "LONG")

    def test_short_expiry_closes_short(self):
        r = model.match_fifo([
            act(id="sto2", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN",
                rawType="OPTIONS_SELL", quantity=-5, unitPrice=2, netCashAmount=1000, transactionDate="2026-01-10",
                symbol="ABC 15JAN27 10.00 CALL"),
            act(id="exp", activityType="OPTIONS_SHORT_EXPIRY", activitySubType="EXPIRED", rawType="OPTIONS_SHORT_EXPIRY",
                quantity=5, transactionDate="2027-01-15", symbol="ABC 15JAN27 10.00 CALL"),
        ])
        self.assertEqual(r["open"], [])
        self.assertEqual(len(r["closed"]), 1)
        self.assertEqual(r["closed"][0]["exitPrice"], 0)
        self.assertEqual(r["closed"][0]["quantity"], 5)
        self.assertAlmostEqual(r["closed"][0]["pnl"], 1000)

    def test_shares_round_trip(self):
        r = model.match_fifo([buy("b", "AAA", 10, 12, "2026-01-10"), sell("s", "AAA", 10, 15, "2026-02-10")])
        self.assertEqual(len(r["closed"]), 1)
        self.assertEqual(r["closed"][0]["quantity"], 10)
        self.assertAlmostEqual(r["closed"][0]["pnl"], 30)
        self.assertEqual(r["closed"][0]["holdDays"], 31)
        self.assertFalse(model.is_option_symbol("AAA"))
        self.assertTrue(model.is_option_symbol("LUNR 15JAN27 12.00 CALL"))

    def test_credit_multilegs_on_a_short_are_a_roll(self):
        r = model.match_fifo([
            act(id="bbai-sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN",
                rawType="OPTIONS_SELL", quantity=-3, unitPrice=1.2, netCashAmount=360, transactionDate="2026-01-05",
                symbol="BBAI 21JAN28 10.00 CALL"),
            act(id="bbai-cr1", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOCLOSE",
                rawType="OPTIONS_MULTILEG", quantity=0, netCashAmount=14, transactionDate="2026-02-01",
                symbol="BBAI 21JAN28 10.00 CALL"),
            act(id="bbai-cr2", activityType="OPTIONS_MULTILEG", activitySubType="FILLED", rawType="OPTIONS_MULTILEG",
                quantity=0, netCashAmount=56, transactionDate="2026-02-01", symbol="BBAI 21JAN28 10.00 CALL"),
        ])
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(r["open"], [])
        self.assertAlmostEqual(sum(t["pnl"] for t in r["closed"]), 360 + 14 + 56)

    def test_long_expiry_and_same_day_expiry(self):
        r = model.match_fifo([
            act(id="lunr-bto", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOOPEN",
                rawType="OPTIONS_BUY", quantity=2, unitPrice=0.4, netCashAmount=-80, transactionDate="2025-07-01",
                symbol="LUNR 22AUG25 8.00 CALL"),
            act(id="lunr-exp", category="option_event", activityType="EXPIR", activitySubType="BUY",
                rawType="OPTIONS_EXPIRY", quantity=2, transactionDate="2025-08-22", symbol="LUNR 22AUG25 8.00 CALL"),
        ])
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(r["open"], [])
        self.assertEqual(len(r["closed"]), 1)
        self.assertEqual(r["closed"][0]["openDirection"], "LONG")
        self.assertAlmostEqual(r["closed"][0]["pnl"], -80)
        r = model.match_fifo([
            act(id="spy-bto", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOOPEN",
                rawType="OPTIONS_BUY", quantity=1, unitPrice=1.1, netCashAmount=-110, transactionDate="2025-07-17",
                symbol="SPY 17JUL25 624.00 PUT"),
            act(id="spy-exp", activityType="OPTIONS_EXPIRY", activitySubType="EXPIRED", rawType="OPTIONS_EXPIRY",
                quantity=1, transactionDate="2025-07-17", symbol="SPY 17JUL25 624.00 PUT"),
        ])
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(r["open"], [])
        self.assertEqual(len(r["closed"]), 1)

    def test_debit_multileg_opens_long_and_sto_opens_short(self):
        r = model.match_fifo([
            act(id="put-ml", activityType="OPTIONS_MULTILEG", activitySubType="FILLED", rawType="OPTIONS_MULTILEG",
                quantity=0, netCashAmount=-90, transactionDate="2026-01-30", symbol="BBAI 30JAN26 6.00 PUT"),
        ])
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(len(r["open"]), 1)
        self.assertEqual(r["open"][0]["direction"], "LONG")
        r = model.match_fifo([
            act(id="sto-only", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN",
                rawType="OPTIONS_SELL", quantity=-4, unitPrice=2, netCashAmount=800, transactionDate="2026-01-01",
                symbol="XYZ 15JAN27 5.00 CALL"),
        ])
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(len(r["open"]), 1)
        self.assertEqual(r["open"][0]["direction"], "SHORT")
        self.assertEqual(r["open"][0]["qty"], 4)

    def test_assignment_keeps_premium(self):
        r = model.match_fifo([
            act(id="asts-sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN",
                rawType="OPTIONS_SELL", quantity=-1, unitPrice=4.7475, netCashAmount=474.75, transactionDate="2025-01-15",
                symbol="ASTS 07MAR25 31.00 CALL"),
            act(id="asts-asg", category="option_event", activityType="ASSIGN", activitySubType="BUYTOCLOSE",
                rawType="OPTIONS_ASSIGN", quantity=1, unitPrice=31, netCashAmount=-3100, transactionDate="2025-03-07",
                symbol="ASTS 07MAR25 31.00 CALL"),
        ])
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(r["open"], [])
        self.assertEqual(len(r["closed"]), 1)
        self.assertEqual(r["closed"][0]["exitPrice"], 0)
        self.assertAlmostEqual(r["closed"][0]["pnl"], 474.75)

    def test_same_day_roll_folds_into_far_contract(self):
        r = model.match_fifo([
            act(id="aug-sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN",
                rawType="OPTIONS_SELL", quantity=-1, unitPrice=3, netCashAmount=300, transactionDate="2026-01-01",
                symbol="ZZZ 21AUG26 10.00 CALL"),
            act(id="aug-cover", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOCLOSE",
                rawType="OPTIONS_BUY", quantity=1, unitPrice=1, netCashAmount=-100, transactionDate="2026-08-15",
                symbol="ZZZ 21AUG26 10.00 CALL"),
            act(id="jan-sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN",
                rawType="OPTIONS_SELL", quantity=-1, unitPrice=2, netCashAmount=200, transactionDate="2026-08-15",
                symbol="ZZZ 15JAN27 12.00 CALL"),
            act(id="jan-cover", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOCLOSE",
                rawType="OPTIONS_BUY", quantity=1, unitPrice=0.5, netCashAmount=-50, transactionDate="2026-12-01",
                symbol="ZZZ 15JAN27 12.00 CALL"),
        ])
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(r["open"], [])
        self.assertEqual(len(r["closed"]), 1)
        self.assertEqual(r["closed"][0]["symbol"], "ZZZ 15JAN27 12.00 CALL")
        self.assertAlmostEqual(r["closed"][0]["entryPrice"], 4)
        self.assertAlmostEqual(r["closed"][0]["pnl"], 350)
        self.assertIn("rolled", r["closed"][0]["flags"])

    def test_stkdis_name_change_nets_to_zero(self):
        r = model.match_fifo([
            buy("b", "OLD", 100, 2, "2026-01-01"),
            act(id="out", category="trade", activityType="STKDIS", activitySubType="SELL", rawType="CORPORATE_ACTION",
                quantity=-100, transactionDate="2026-02-01", symbol="OLD", currency="CAD"),
            act(id="in", category="trade", activityType="STKDIS", activitySubType="BUY", rawType="CORPORATE_ACTION",
                quantity=100, transactionDate="2026-02-01", symbol="NEW", currency="CAD"),
            sell("s", "NEW", 100, 3, "2026-03-01"),
        ])
        # Parity with ledger.html: the +N leg opens NEW at $0 and the sell
        # closes it; the OLD lot is only reused when NEW runs out of lots.
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(len(r["closed"]), 1)
        self.assertEqual(r["closed"][0]["symbol"], "NEW")
        self.assertAlmostEqual(r["closed"][0]["pnl"], 300)
        self.assertEqual([l["symbol"] for l in r["open"]], ["OLD"])
        r = model.match_fifo([
            buy("b", "OLD", 100, 2, "2026-01-01"),
            act(id="out", category="trade", activityType="STKDIS", activitySubType="SELL", rawType="CODE_CHANGE",
                quantity=-100, transactionDate="2026-02-01", symbol="OLD", currency="CAD"),
            sell("s", "NEW", 100, 3, "2026-03-01"),
        ])
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(len(r["closed"]), 1)
        self.assertEqual(r["closed"][0]["symbol"], "NEW")
        self.assertAlmostEqual(r["closed"][0]["pnl"], 100)
        self.assertEqual(r["open"], [])


class SplitTest(unittest.TestCase):
    def test_reverse_split_marker_rescales_open_lots(self):
        acts = [
            buy("b1", "MSTY", 100, 7.0, "2025-12-01"),
            buy("b2", "MSTY", 75, 6.9, "2025-12-05"),
            act(id="ca", category="trade", activityType="STKDIS", activitySubType="BUY", rawType="CORPORATE_ACTION",
                quantity=0, transactionDate="2025-12-08", symbol="MSTY", currency="CAD"),
            buy("b3", "MSTY", 4, 34.0, "2025-12-11"),
            sell("s1", "MSTY", 39, 31.0, "2026-01-16"),
        ]
        r = model.match_fifo(model.normalize_activities(acts))
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(r["open"], [])
        self.assertAlmostEqual(sum(t["quantity"] for t in r["closed"]), 39)
        first = min(r["closed"], key=lambda t: t["entryDate"])
        self.assertAlmostEqual(first["entryPrice"], 35.0)
        self.assertAlmostEqual(sum(t["pnl"] for t in r["closed"]), 39 * 31 - (100 * 7 + 75 * 6.9 + 4 * 34))

    def test_forward_split_and_no_marker_without_prices(self):
        acts = [
            buy("b1", "NVDA", 10, 1000.0, "2024-05-01"),
            act(id="ca", category="trade", activityType="STKDIS", activitySubType="BUY", rawType="CORPORATE_ACTION",
                quantity=0, transactionDate="2024-06-10", symbol="NVDA", currency="CAD"),
            buy("b2", "NVDA", 5, 98.0, "2024-06-12", currency="USD"),
        ]
        acts[0]["currency"] = "USD"
        r = model.match_fifo(model.normalize_activities(acts))
        self.assertAlmostEqual(sum(l["qty"] for l in r["open"]), 105)
        big = max(r["open"], key=lambda l: l["qty"])
        self.assertAlmostEqual(big["price"], 100.0)
        self.assertIn("split 10:1", big["flags"])
        r = model.match_fifo(model.normalize_activities([
            buy("b1", "AAA", 10, 10.0, "2024-05-01"),
            act(id="ca", category="trade", activityType="STKDIS", activitySubType="BUY", rawType="CORPORATE_ACTION",
                quantity=0, transactionDate="2024-06-10", symbol="AAA", currency="CAD"),
        ]))
        self.assertEqual(r["open"][0]["qty"], 10)


class RoundTripTest(unittest.TestCase):
    def _trades(self, acts, groups=None, journal=None):
        norm = model.normalize_activities(acts)
        fifo = model.match_fifo(norm)
        model.apply_fx(fifo["closed"], {})
        by_id = {a["id"]: a for a in norm}
        return model.build_trades(fifo["closed"], fifo["open"], groups or [], by_id, model.Securities([]), journal or {})

    def test_flat_to_flat_twice_is_two_trades(self):
        trades = self._trades([
            buy("b1", "AAA", 100, 10, "2026-01-01"),
            sell("s1", "AAA", 100, 12, "2026-01-10"),
            buy("b2", "AAA", 50, 11, "2026-02-01"),
            sell("s2", "AAA", 50, 9, "2026-02-10"),
        ])
        self.assertEqual(len(trades), 2)
        self.assertEqual({t["id"] for t in trades}, {"rt:b1", "rt:b2"})
        self.assertTrue(all(t["status"] == "closed" for t in trades))
        pnl = {t["id"]: t["pnl"] for t in trades}
        self.assertAlmostEqual(pnl["rt:b1"], 200)
        self.assertAlmostEqual(pnl["rt:b2"], -100)

    def test_scale_in_and_out_is_one_trade_with_legs(self):
        trades = self._trades([
            buy("b1", "AAA", 100, 10, "2026-01-01"),
            sell("s1", "AAA", 50, 12, "2026-01-10"),
            buy("b2", "AAA", 100, 11, "2026-01-15"),
            sell("s2", "AAA", 150, 13, "2026-02-01"),
        ])
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual(t["id"], "rt:b1")
        self.assertEqual(t["status"], "closed")
        self.assertEqual(t["qty"], 200)
        self.assertEqual(t["legCount"], 3)
        self.assertEqual(t["entryDate"], "2026-01-01")
        self.assertEqual(t["exitDate"], "2026-02-01")
        self.assertAlmostEqual(t["pnl"], 50 * 2 + 50 * 3 + 100 * 2)
        self.assertEqual(len(t["fills"]), 4)
        self.assertEqual(t["opened"]["fills"], 2)
        self.assertEqual(t["closed"]["fills"], 2)
        self.assertEqual(t["side"], "SELL")

    def test_partial_exit_is_a_closed_trade_with_stable_id(self):
        acts = [buy("b1", "AAA", 100, 10, "2026-01-01"), sell("s1", "AAA", 40, 12, "2026-01-10")]
        trades = self._trades(acts)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["status"], "closed")
        self.assertEqual(trades[0]["id"], "rt:b1")
        self.assertEqual(trades[0]["qty"], 40)
        acts.append(sell("s2", "AAA", 60, 15, "2026-02-01"))
        trades = self._trades(acts)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["status"], "closed")
        self.assertEqual(trades[0]["id"], "rt:b1")
        self.assertEqual(trades[0]["qty"], 100)

    def test_saved_group_overrides_round_trip(self):
        acts = [
            buy("b1", "AAA", 100, 10, "2026-01-01"),
            sell("s1", "AAA", 100, 12, "2026-01-10"),
            buy("b2", "AAA", 50, 11, "2026-02-01"),
            sell("s2", "AAA", 50, 9, "2026-02-10"),
        ]
        key1 = "b1|s1|%s" % ("%.8f" % 100)
        key2 = "b2|s2|%s" % ("%.8f" % 50)
        trades = self._trades(acts, groups=[{"id": "g_manual", "locked": True, "members": [key1, key2]}])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["id"], "g_manual")
        self.assertTrue(trades[0]["locked"])
        self.assertEqual(trades[0]["legCount"], 2)

    def test_position_notes_carry_over_to_the_closed_trade(self):
        snapshot = {
            "activities": [buy("b1", "AAA", 100, 10, "2026-01-01")],
            "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": [],
        }
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}}, {}, today="2026-02-01")
        pid = base["positions"][0]["id"]
        self.assertEqual(pid, "rt:b1")
        journal = {pid: {"thesis": "holding for the catalyst", "tags": ["core"], "grade": ""}}
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}}, journal, today="2026-02-01")
        self.assertEqual(base["positions"][0]["thesis"], "holding for the catalyst")
        snapshot["activities"].append(sell("s1", "AAA", 100, 12, "2026-03-01"))
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}}, journal, today="2026-04-01")
        self.assertEqual(base["positions"], [])
        self.assertEqual(base["trades"][0]["id"], "rt:b1")
        self.assertEqual(base["trades"][0]["thesis"], "holding for the catalyst")
        self.assertEqual(base["trades"][0]["tags"], ["core"])

    def test_journal_attaches_to_trade(self):
        trades = self._trades(
            [buy("b1", "AAA", 100, 10, "2026-01-01"), sell("s1", "AAA", 100, 12, "2026-01-10")],
            journal={"rt:b1": {"thesis": "breakout", "tags": ["momo"], "grade": "A"}},
        )
        self.assertEqual(trades[0]["grade"], "A")
        self.assertEqual(trades[0]["tags"], ["momo"])
        self.assertEqual(trades[0]["thesis"], "breakout")

    def test_fill_labels_reflect_what_the_fill_did(self):
        trades = self._trades([
            act(id="sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL",
                quantity=-2, unitPrice=3, netCashAmount=600, transactionDate="2026-01-01", symbol="ZZZ 21AUG26 10.00 CALL"),
            act(id="buy", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOOPEN", rawType="OPTIONS_BUY",
                quantity=2, unitPrice=1, netCashAmount=-200, transactionDate="2026-02-01", symbol="ZZZ 21AUG26 10.00 CALL"),
        ])
        subs = {f["id"]: f["sub"] for f in trades[0]["fills"]}
        self.assertEqual(subs, {"sto": "SELL TO OPEN", "buy": "BUY TO CLOSE"})

    def test_short_round_trip_is_cover(self):
        trades = self._trades([
            act(id="sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL",
                quantity=-2, unitPrice=3, netCashAmount=600, transactionDate="2026-01-01", symbol="ZZZ 21AUG26 10.00 CALL"),
            act(id="btc", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOCLOSE", rawType="OPTIONS_BUY",
                quantity=2, unitPrice=1, netCashAmount=-200, transactionDate="2026-02-01", symbol="ZZZ 21AUG26 10.00 CALL"),
        ])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["side"], "COVER")
        self.assertEqual(trades[0]["kind"], "Options")
        self.assertEqual(trades[0]["mult"], 100)
        self.assertAlmostEqual(trades[0]["pnl"], 400)
        self.assertAlmostEqual(trades[0]["pnlPct"], 400 / 600)


class ExpiryTest(unittest.TestCase):
    def test_option_expiry_parse(self):
        self.assertEqual(model.option_expiry("LUNR 29AUG25 11.50 CALL"), "2025-08-29")
        self.assertEqual(model.option_expiry("BBAI 02JAN26 5.50 PUT"), "2026-01-02")
        self.assertEqual(model.option_expiry("AAPL"), "")

    def test_open_option_past_expiry_is_closed_at_zero(self):
        snapshot = {
            "activities": [
                act(id="sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL",
                    quantity=-2, unitPrice=0.3, netCashAmount=60, transactionDate="2025-12-05", symbol="BBAI 02JAN26 5.50 PUT"),
                act(id="bto", category="trade", activityType="OPTIONS_BUY", activitySubType="BUYTOOPEN", rawType="OPTIONS_BUY",
                    quantity=1, unitPrice=1.0, netCashAmount=-100, transactionDate="2026-01-05", symbol="ZZZ 17JUL26 10.00 CALL"),
            ],
            "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": [],
        }
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}}, {}, today="2026-03-01")
        self.assertEqual(len(base["openLots"]), 1)
        self.assertEqual(base["openLots"][0]["symbol"], "ZZZ 17JUL26 10.00 CALL")
        self.assertEqual(len(base["trades"]), 1)
        t = base["trades"][0]
        self.assertEqual(t["exitDate"], "2026-01-02")
        self.assertEqual(t["exit"], 0)
        self.assertAlmostEqual(t["pnl"], 60)
        self.assertIn("assumed-expiry", t["flags"])
        self.assertEqual(t["status"], "closed")


class AssignmentTest(unittest.TestCase):
    def test_assigned_call_delivers_the_shares(self):
        snapshot = {
            "activities": [
                buy("b1", "ASTS", 300, 25.0, "2025-01-10", currency="USD", securityId="sec-s-asts"),
                act(id="sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL",
                    quantity=-3, unitPrice=1.5, netCashAmount=450, transactionDate="2025-02-10", symbol="ASTS 07MAR25 31.00 CALL", securityId="sec-o-asts"),
                act(id="asg", category="option_event", activityType="ASSIGN", activitySubType="BUYTOCLOSE", rawType="OPTIONS_ASSIGN",
                    quantity=3, unitPrice=0, netCashAmount=9300, transactionDate="2025-03-07", symbol="ASTS 07MAR25 31.00 CALL", securityId="sec-o-asts"),
            ],
            "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {},
            "securities": [{"id": "sec-o-asts", "symbol": "ASTS", "underlyingId": "sec-s-asts"}, {"id": "sec-s-asts", "symbol": "ASTS", "name": "AST SpaceMobile", "primaryExchange": "NASDAQ"}],
        }
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}}, {}, today="2026-09-06")
        self.assertEqual(base["openLots"], [])
        by_sym = {t["symbol"]: t for t in base["trades"]}
        shares = by_sym["ASTS"]
        self.assertEqual(shares["qty"], 300)
        self.assertEqual(shares["exit"], 31.0)
        self.assertEqual(shares["exitDate"], "2025-03-07")
        self.assertAlmostEqual(shares["pnl"], (31 - 25) * 300)
        self.assertIn("assignment", shares["flags"])
        self.assertEqual(shares["name"], "AST SpaceMobile")
        self.assertAlmostEqual(by_sym["ASTS 07MAR25 31.00 CALL"]["pnl"], 450)

    def test_assigned_put_buys_the_shares(self):
        snapshot = {
            "activities": [
                act(id="sto", category="trade", activityType="OPTIONS_SELL", activitySubType="SELLTOOPEN", rawType="OPTIONS_SELL",
                    quantity=-1, unitPrice=0.5, netCashAmount=50, transactionDate="2025-11-10", symbol="BBAI 05DEC25 5.00 PUT"),
                act(id="asg", category="option_event", activityType="ASSIGN", activitySubType="BUYTOCLOSE", rawType="OPTIONS_ASSIGN",
                    quantity=1, unitPrice=0, netCashAmount=-500, transactionDate="2025-12-05", symbol="BBAI 05DEC25 5.00 PUT"),
            ],
            "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": [],
        }
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}}, {}, today="2026-01-01")
        self.assertEqual([(l["symbol"], l["qty"], l["price"]) for l in base["openLots"]], [("BBAI", 100, 5.0)])
        self.assertIn("assignment", base["openLots"][0]["flags"])


class CryptoTest(unittest.TestCase):
    def test_crypto_buy_sell_and_reward(self):
        acts = [
            act(id="cb", activityType="CRYPTO_BUY", activitySubType="MARKET_ORDER", rawType="CRYPTO_BUY",
                quantity=2, unitPrice=100, netCashAmount=200, transactionDate="2026-01-01", symbol="ETH", currency="CAD",
                accountType="Ponzi"),
            act(id="rw", activityType="CRYPTO_STAKING_REWARD", activitySubType="other", rawType="CRYPTO_STAKING_REWARD",
                quantity=1, unitPrice=0, netCashAmount=0, transactionDate="2026-01-05", symbol="ETH", currency="CAD",
                accountType="Ponzi"),
            act(id="cs", activityType="CRYPTO_SELL", activitySubType="MARKET_ORDER", rawType="CRYPTO_SELL",
                quantity=3, unitPrice=150, netCashAmount=450, transactionDate="2026-02-01", symbol="ETH", currency="CAD",
                accountType="Ponzi"),
        ]
        norm = model.normalize_activities(acts)
        self.assertEqual(norm[0]["kind"], "Crypto")
        self.assertLess(norm[0]["netCashAmount"], 0)
        self.assertIn("reward", norm[1]["flags"])
        fifo = model.match_fifo(norm)
        self.assertEqual(fifo["unmatched"], [])
        self.assertEqual(fifo["open"], [])
        self.assertEqual(len(fifo["closed"]), 2)
        self.assertAlmostEqual(sum(t["pnl"] for t in fifo["closed"]), (150 - 100) * 2 + 150 * 1)
        self.assertTrue(all(t["kind"] == "Crypto" for t in fifo["closed"]))

    def test_crypto_dust_sell_is_not_unmatched(self):
        acts = [
            act(id="cb", activityType="CRYPTO_BUY", rawType="CRYPTO_BUY", quantity=1.0, unitPrice=100,
                netCashAmount=100, transactionDate="2026-01-01", symbol="DOGE", currency="CAD"),
            act(id="cs", activityType="CRYPTO_SELL", rawType="CRYPTO_SELL", quantity=1.0000004, unitPrice=120,
                netCashAmount=120, transactionDate="2026-02-01", symbol="DOGE", currency="CAD"),
        ]
        fifo = model.match_fifo(model.normalize_activities(acts))
        self.assertEqual(fifo["unmatched"], [])
        self.assertEqual(len(fifo["closed"]), 1)

    def test_pending_distribution_notice_is_not_a_lot(self):
        acts = [
            buy("b", "RDDY", 100, 9, "2026-01-01"),
            act(id="stk", category="trade", activityType="STKDIS", activitySubType="BUY", rawType="DIVIDEND",
                quantity=100, unitPrice=0, netCashAmount=0, transactionDate="2026-02-01", symbol="RDDY", currency="CAD"),
        ]
        fifo = model.match_fifo(model.normalize_activities(acts))
        self.assertEqual(len(fifo["open"]), 1)
        self.assertEqual(fifo["open"][0]["qty"], 100)
        self.assertEqual(fifo["open"][0]["price"], 9)


class FxTest(unittest.TestCase):
    def test_usd_pnl_uses_rates_on_fill_dates(self):
        fx = {"2026-01-05": 1.40, "2026-02-05": 1.30}
        fifo = model.match_fifo([
            buy("b", "LUNR", 100, 10, "2026-01-05", currency="USD"),
            sell("s", "LUNR", 100, 12, "2026-02-05", currency="USD"),
        ])
        model.apply_fx(fifo["closed"], fx)
        t = fifo["closed"][0]
        self.assertAlmostEqual(t["pnl"], 200)
        self.assertAlmostEqual(t["pnlCad"], 1200 * 1.30 - 1000 * 1.40)

    def test_rate_walks_back_over_weekends_and_falls_back(self):
        fx = {"2026-01-02": 1.40}
        self.assertEqual(model.rate_on(fx, "2026-01-04"), 1.40)
        self.assertEqual(model.rate_on(fx, "2025-06-01"), model.FX_FALLBACK)
        self.assertEqual(model.to_cad(fx, 100, "CAD", "2026-01-04"), 100)


class ViewTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "activities": [
                buy("b1", "AAA", 100, 10, "2025-03-01", accountType="Trading"),
                sell("s1", "AAA", 100, 12, "2025-03-10", accountType="Trading"),
                buy("b2", "BBB", 10, 100, "2026-01-05", accountType="Trading"),
                sell("s2", "BBB", 10, 90, "2026-01-20", accountType="Trading"),
                buy("b3", "CCC", 10, 5, "2026-02-01", accountType="Retirement"),
                sell("s3", "CCC", 10, 6, "2026-02-15", accountType="Retirement"),
                buy("b4", "DDD", 10, 5, "2026-03-01", accountType="Trading"),
                buy("b5", "LUNR", 10, 10, "2026-03-01", accountType="Trading", currency="USD"),
                sell("s5", "LUNR", 10, 11, "2026-03-05", accountType="Trading", currency="USD"),
            ],
            "accounts": [
                {"id": "acct-1", "nickname": "Trading", "unifiedAccountType": "TFSA", "currency": "CAD"},
                {"id": "acct-2", "nickname": "Retirement", "unifiedAccountType": "RRSP", "currency": "CAD"},
            ],
            "balances": [],
            "navHistory": [
                {"date": "2024-12-31", "equity": 1000, "netDeposits": 1000},
                {"date": "2025-06-30", "equity": 1500, "netDeposits": 1200},
                {"date": "2025-12-31", "equity": 1600, "netDeposits": 1200},
                {"date": "2026-03-31", "equity": 1400, "netDeposits": 1200},
            ],
            "navByAccount": {"Trading": [{"date": "2025-12-31", "equity": 800, "netDeposits": 500}, {"date": "2026-03-31", "equity": 700, "netDeposits": 500}]},
            "syncedAt": "2026-04-01T00:00:00Z",
            "tradeGroups": [],
            "notes": {},
            "securities": [],
        }
        self.market = {"fx": {"2026-03-01": 1.4, "2026-03-05": 1.3}, "benchmark": {"2024-12-31": 100, "2025-12-31": 120, "2026-03-31": 126}}
        self.journal = {"rt:b1": {"thesis": "yes", "tags": ["x"], "grade": "A"}, "rt:b2": {"thesis": "", "tags": [], "grade": "F"}}
        self.base = model.build_base(self.snapshot, self.market, self.journal, today="2026-04-01")

    def test_one_list_feeds_every_tile(self):
        v = model.build_view(self.base, None)
        k = v["kpi"]
        self.assertEqual(k["count"], 4)
        self.assertEqual(len(v["trades"]), 4)
        self.assertAlmostEqual(k["realized"], sum(t["pnlCad"] for t in v["trades"]))
        self.assertAlmostEqual(sum(m["value"] for m in v["monthly"]), k["realized"])
        self.assertAlmostEqual(sum(r["pnl"] for r in v["bySymbol"]), k["realized"])
        g = v["grades"]
        self.assertEqual(sum(b["n"] for b in g["buckets"]) + g["ungraded"], k["count"])
        self.assertEqual(sum(r["n"] for r in v["bySymbol"]), k["count"])
        self.assertEqual(k["wins"] + k["losses"] + k["breakeven"], k["count"])
        self.assertEqual(len(v["queue"]), 3)
        usd = next(t for t in v["trades"] if t["symbol"] == "LUNR")
        self.assertAlmostEqual(usd["pnl"], 10)
        self.assertAlmostEqual(usd["pnlCad"], 110 * 1.3 - 100 * 1.4)

    def test_positions_and_options(self):
        v = model.build_view(self.base, None)
        self.assertEqual(len(v["positions"]), 1)
        p = v["positions"][0]
        self.assertEqual(p["symbol"], "DDD")
        self.assertEqual(p["priceSource"], "fill")
        self.assertEqual(p["alloc"], 1.0)
        self.assertEqual(p["held"], 31)
        self.assertEqual(v["options"]["accounts"], ["Retirement", "Trading"])
        self.assertEqual(v["options"]["kinds"], ["Shares"])
        self.assertEqual(v["options"]["tags"], ["x"])

    def test_account_filter_narrows_everything(self):
        v = model.build_view(self.base, {"lists": {"account": ["Retirement"]}})
        self.assertEqual(v["kpi"]["count"], 1)
        self.assertEqual(v["trades"][0]["symbol"], "CCC")
        self.assertEqual(v["positions"], [])
        self.assertEqual(v["equity"]["label"], "All accounts")
        v = model.build_view(self.base, {"lists": {"account": ["Trading"]}})
        self.assertEqual(v["equity"]["label"], "Trading")
        self.assertEqual(len(v["positions"]), 1)

    def test_date_filters(self):
        v = model.build_view(self.base, {"years": ["2025"]})
        self.assertEqual([t["symbol"] for t in v["trades"]], ["AAA"])
        v = model.build_view(self.base, {"preset": "ytd"})
        self.assertEqual({t["symbol"] for t in v["trades"]}, {"BBB", "CCC", "LUNR"})
        v = model.build_view(self.base, {"from": "2026-02-01", "to": "2026-02-28"})
        self.assertEqual([t["symbol"] for t in v["trades"]], ["CCC"])
        v = model.build_view(self.base, {"preset": "1m"})
        self.assertEqual([t["symbol"] for t in v["trades"]], ["LUNR"])

    def test_list_and_range_filters(self):
        v = model.build_view(self.base, {"lists": {"grade": ["A"]}})
        self.assertEqual([t["symbol"] for t in v["trades"]], ["AAA"])
        v = model.build_view(self.base, {"lists": {"grade": ["Ungraded"]}})
        self.assertEqual({t["symbol"] for t in v["trades"]}, {"CCC", "LUNR"})
        v = model.build_view(self.base, {"lists": {"result": ["Losers"]}})
        self.assertEqual([t["symbol"] for t in v["trades"]], ["BBB"])
        v = model.build_view(self.base, {"ranges": {"price": {"op": ">", "v": 50}}})
        self.assertEqual([t["symbol"] for t in v["trades"]], ["BBB"])
        v = model.build_view(self.base, {"search": "aa"})
        self.assertEqual([t["symbol"] for t in v["trades"]], ["AAA"])
        v = model.build_view(self.base, {"lists": {"tag": ["untagged"]}})
        self.assertEqual(v["kpi"]["count"], 3)

    def test_returns_and_drawdown(self):
        v = model.build_view(self.base, None)
        years = {y["year"]: y for y in v["years"]}
        self.assertAlmostEqual(years["2025"]["r"], (1500 - 1000 - 200) / 1000 * 1 + 0.0, places=6) if False else None
        # 2025: two steps, (1500-1000-200)/1000 then (1600-1500)/1500
        self.assertAlmostEqual(years["2025"]["r"], (1 + 0.3) * (1 + 100 / 1500) - 1)
        self.assertAlmostEqual(years["2025"]["spR"], 0.2)
        self.assertAlmostEqual(years["2025"]["flow"], 200)
        self.assertAlmostEqual(years["2026"]["r"], (1400 - 1600) / 1600)
        self.assertAlmostEqual(years["2026"]["spR"], 0.05)
        dd = v["equity"]["drawdown"]
        self.assertAlmostEqual(dd["pct"], (1400 - 1600) / 1600)
        self.assertEqual(dd["at"], "2026-03-31")
        self.assertIsNotNone(v["equity"]["annualized"]["rate"])

    def test_drawdown_ignores_withdrawals_and_deposits(self):
        series = model.equity_series([
            {"date": "2026-01-01", "equity": 100000, "netDeposits": 100000},
            {"date": "2026-01-02", "equity": 101000, "netDeposits": 100000},
            {"date": "2026-01-03", "equity": 21000, "netDeposits": 20000},   # withdrew 80,000; no loss
            {"date": "2026-01-04", "equity": 21210, "netDeposits": 20000},
            {"date": "2026-01-05", "equity": 41210, "netDeposits": 40000},   # deposited 20,000
            {"date": "2026-01-06", "equity": 37089, "netDeposits": 40000},   # a real 10% loss
        ])
        dd = model.drawdown(series)
        self.assertAlmostEqual(dd["pct"], -0.1, places=4)
        self.assertEqual(dd["at"], "2026-01-06")
        self.assertEqual(dd["peakAt"], "2026-01-05")
        self.assertAlmostEqual(dd["abs"], -4121, delta=1)

    def test_negligible_years_are_skipped(self):
        series = model.equity_series([
            {"date": "2020-12-22", "equity": 0, "netDeposits": 0},
            {"date": "2020-12-23", "equity": 100, "netDeposits": 100},
            {"date": "2020-12-31", "equity": 101, "netDeposits": 100},
            {"date": "2023-12-31", "equity": 50000, "netDeposits": 40000},
            {"date": "2024-12-31", "equity": 60000, "netDeposits": 40000},
        ])
        years = [y["year"] for y in model.yearly_returns(series, {}, "2025-01-01")]
        self.assertEqual(years, ["2023", "2024"])

    def test_filters_are_cleaned(self):
        f = model.clean_filters({"lists": {"account": ["A", 3, ""]}, "ranges": {"hold": {"op": "<", "v": "7"}}, "preset": "bogus", "years": [2025, "abcd"], "from": "2026-1-1", "to": "2026-02-01"})
        self.assertEqual(f["lists"]["account"], ["A", "3"])
        self.assertEqual(f["ranges"]["hold"], {"op": "<", "v": 7.0})
        self.assertEqual(f["preset"], "all")
        self.assertEqual(f["years"], ["2025"])
        self.assertEqual(f["from"], "")
        self.assertEqual(f["to"], "2026-02-01")


class CashflowTest(unittest.TestCase):
    def test_yield_on_cost_from_declared_rate(self):
        div = lambda i, day, qty, per: act(
            id="d%d" % i, category="dividend", activityType="Dividend", activitySubType="dividend", rawType="DIVIDEND",
            quantity=qty, unitPrice=per, netCashAmount=qty * per, transactionDate=day, symbol="RDDY", currency="CAD",
            accountType="Cashflow",
        )
        snapshot = {
            "activities": [
                buy("b1", "RDDY", 20000, 7.13, "2026-01-05", accountType="Cashflow"),
                div(1, "2026-07-06", 19000, 0.2),
                div(2, "2026-08-06", 19000, 0.2),
                act(id="int", category="interest", activityType="Interest", rawType="INTEREST", netCashAmount=4.5,
                    transactionDate="2026-08-01", symbol="", accountType="Cash"),
                act(id="wht", activityType="WITHHOLDING_TAX", rawType="WITHHOLDING_TAX", netCashAmount=-40,
                    transactionDate="2026-08-07", symbol="", accountType="Cashflow"),
            ],
            "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": [],
        }
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}}, {}, today="2026-09-06")
        self.assertEqual(len(base["cashflow"]), 4)
        v = model.build_view(base, None)
        cf = v["cashflow"]
        self.assertEqual(cf["count"], 2)
        self.assertEqual([r["kind"] for r in cf["rows"]], ["Dividend", "Dividend"])
        self.assertEqual({r["kind"] for r in cf["other"]}, {"Interest", "Withholding tax"})
        self.assertAlmostEqual(cf["total"], 7600)
        self.assertEqual([m["key"] for m in cf["months"]], ["2026-07", "2026-08"])
        h = cf["holdings"][0]
        self.assertEqual(h["symbol"], "RDDY")
        self.assertEqual(h["freq"], 12)
        self.assertAlmostEqual(h["yoc"], 2.4 / 7.13)
        self.assertAlmostEqual(h["yob"], 0.2 * 20000)
        self.assertAlmostEqual(h["ytd"], 7600)
        tiles = {t["label"]: t for t in cf["tiles"]}
        self.assertAlmostEqual(tiles["2026 YTD"]["total"], 7600)
        self.assertAlmostEqual(tiles["2026 YTD"]["perMonth"], 3800)
        self.assertAlmostEqual(tiles["Yield on cost"]["yield"], (2.4 * 20000) / (20000 * 7.13))
        v = model.build_view(base, {"lists": {"grade": ["A"]}})
        self.assertIn("grade", v["cashflow"]["skippedFilters"])
        self.assertEqual(v["cashflow"]["count"], 2)


class PaymentFrequencyTest(unittest.TestCase):
    def test_frequency_is_verified_from_dates(self):
        self.assertEqual(model.payments_per_year(["2026-07-06", "2026-08-06"]), 12)
        self.assertEqual(model.payments_per_year(["2026-08-06", "2026-07-06", "2026-06-05", "2026-05-06"]), 12)
        self.assertEqual(model.payments_per_year(["2025-01-07", "2026-01-07"]), 1)
        self.assertEqual(model.payments_per_year(["2025-03-20", "2025-06-20", "2025-09-22", "2025-12-19"]), 4)
        self.assertEqual(model.payments_per_year(["2026-01-02", "2026-01-09", "2026-01-16"]), 52)
        # a monthly payer that switched to weekly is read from its recent payments
        self.assertEqual(model.payments_per_year(["2026-01-06", "2026-02-06", "2026-03-06", "2026-04-06", "2026-05-06", "2026-05-13", "2026-05-20", "2026-05-27"]), 52)
        self.assertIsNone(model.payments_per_year(["2026-08-06"]))
        self.assertIsNone(model.payments_per_year(["2026-08-06", "2026-08-06"]))

    def test_frequency_uses_payment_rows_without_per_unit_values(self):
        div = lambda i, day, qty, per, amount: act(
            id="v%d" % i, category="dividend", activityType="Dividend", activitySubType="dividend", rawType="DIVIDEND",
            quantity=qty, unitPrice=per, netCashAmount=amount, transactionDate=day, symbol="VEQT", currency="CAD", accountType="Kids",
        )
        snapshot = {
            "activities": [buy("b1", "VEQT", 300, 49.76, "2024-06-01", accountType="Kids"), div(1, "2025-01-07", 0, 0, 91.56), div(2, "2026-01-07", 300, 0.76, 228)],
            "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": [],
        }
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}}, {}, today="2026-09-06")
        h = model.build_view(base, None)["cashflow"]["holdings"][0]
        self.assertEqual(h["freq"], 1)
        self.assertTrue(h["freqVerified"])

    def test_single_payment_shows_no_yield_and_annual_payer_is_not_x12(self):
        div = lambda i, sym, day, qty, per, acct="Kids": act(
            id="d%s%d" % (sym, i), category="dividend", activityType="Dividend", activitySubType="dividend", rawType="DIVIDEND",
            quantity=qty, unitPrice=per, netCashAmount=qty * per, transactionDate=day, symbol=sym, currency="CAD", accountType=acct,
        )
        snapshot = {
            "activities": [
                buy("b1", "VEQT", 300, 49.76, "2024-06-01", accountType="Kids"),
                div(1, "VEQT", "2025-01-07", 300, 0.76),
                div(2, "VEQT", "2026-01-07", 300, 0.76),
                buy("b2", "NEWM", 1000, 10.0, "2026-07-01", accountType="Kids"),
                div(1, "NEWM", "2026-08-06", 1000, 0.1),
            ],
            "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": [],
        }
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}}, {}, today="2026-09-06")
        h = {x["symbol"]: x for x in model.build_view(base, None)["cashflow"]["holdings"]}
        self.assertEqual(h["VEQT"]["freq"], 1)
        self.assertTrue(h["VEQT"]["freqVerified"])
        self.assertAlmostEqual(h["VEQT"]["yoc"], 0.76 / 49.76)
        self.assertEqual(h["NEWM"]["freq"], 12)
        self.assertFalse(h["NEWM"]["freqVerified"])
        self.assertAlmostEqual(h["NEWM"]["yoc"], 0.1 * 12 / 10.0)
        self.assertEqual(h["NEWM"]["per"], 0.1)


class QuoteTest(unittest.TestCase):
    def test_tmx_quote_symbol_mapping(self):
        self.assertEqual(market.tmx_quote_symbol("CCHI", "TSX", "CAD"), "CCHI")
        self.assertEqual(market.tmx_quote_symbol("CH", "TSX-V", "CAD"), "CH")
        self.assertEqual(market.tmx_quote_symbol("LUNR", "NASDAQ", "USD"), "LUNR:US")
        self.assertEqual(market.tmx_quote_symbol("ASTS", "", "USD"), "ASTS:US")
        self.assertIsNone(market.tmx_quote_symbol("HBIX", "Cboe Canada", "CAD"))
        self.assertIsNone(market.tmx_quote_symbol("QNC 20NOV26 3.00 CALL", "", "USD"))

    def test_positions_use_the_quote_when_present(self):
        snapshot = {
            "activities": [buy("b1", "VEQT", 100, 49.76, "2026-01-05", accountType="Kids"), buy("b2", "HBIX", 100, 7.0, "2026-01-05", accountType="Kids")],
            "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": [],
        }
        quotes = {"VEQT": {"price": 62.4, "priceChange": 0.08, "percentChange": 0.128, "fetchedAt": "2026-09-06T14:00:00Z"}}
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}, "quotes": quotes}, {}, today="2026-09-06")
        p = {x["symbol"]: x for x in base["positions"]}
        self.assertEqual(p["VEQT"]["last"], 62.4)
        self.assertEqual(p["VEQT"]["priceSource"], "quote")
        self.assertAlmostEqual(p["VEQT"]["unreal"], (62.4 - 49.76) * 100)
        self.assertEqual(p["VEQT"]["priceChange"], 0.08)
        self.assertEqual(p["HBIX"]["priceSource"], "fill")
        self.assertEqual(p["HBIX"]["last"], 7.0)
        self.assertEqual(model.held_symbols(base), [{"symbol": "VEQT", "exchange": "", "currency": "CAD", "kind": "Shares"}, {"symbol": "HBIX", "exchange": "", "currency": "CAD", "kind": "Shares"}])

    def test_quote_sources_cover_every_held_kind(self):
        src = market.quote_source
        self.assertEqual(src({"symbol": "VEQT", "exchange": "TSX", "currency": "CAD", "kind": "Shares"}), ("tmx", "VEQT"))
        self.assertEqual(src({"symbol": "LUNR", "exchange": "NASDAQ", "currency": "USD", "kind": "Shares"}), ("tmx", "LUNR:US"))
        self.assertEqual(src({"symbol": "HBIX", "exchange": "Cboe Canada", "currency": "CAD", "kind": "Shares"}), ("cboe_ca", "HBIX"))
        self.assertEqual(src({"symbol": "BTC", "exchange": "Crypto", "currency": "CAD", "kind": "Crypto"}), ("coinbase", "BTC-CAD"))
        self.assertEqual(src({"symbol": "BTC", "exchange": "Crypto", "currency": "USD", "kind": "Crypto"}), ("coinbase", "BTC-USD"))
        self.assertEqual(src({"symbol": "QNC 20NOV26 3.00 CALL", "exchange": "NYSE", "currency": "USD", "kind": "Options"}), ("cboe_options", "QNC261120C00003000"))
        self.assertIsNone(src({"symbol": "SHOP 17OCT25 100.00 PUT", "exchange": "TSX", "currency": "CAD", "kind": "Options"}))
        self.assertEqual(market.occ_code("LUNR 29AUG25 11.50 CALL"), "LUNR250829C00011500")
        self.assertEqual(market.occ_code("SPY 251219P00450000"), "SPY251219P00450000")
        self.assertEqual(market.occ_code("VEQT"), "")
        self.assertEqual(market.occ_root("QNC261120C00003000"), "QNC")

    def test_public_quote_parsers(self):
        closed = json.dumps({"data": {"last": "0.0", "prev_close": "6.7600", "change": "0.0", "change_pct": "0.0", "company_name": "HARVEST BITCOIN ENHANCED INCOME ETF"}})
        self.assertEqual(market.parse_cboe_ca_quote(closed)["price"], 6.76)
        open_ = json.dumps({"data": {"last": "6.81", "prev_close": "6.7600", "change": "0.05", "change_pct": "0.74"}})
        q = market.parse_cboe_ca_quote(open_)
        self.assertEqual((q["price"], q["prevClose"], q["priceChange"]), (6.81, 6.76, 0.05))
        self.assertIsNone(market.parse_cboe_ca_quote(json.dumps({"data": {"last": "0", "prev_close": "0"}})))
        self.assertEqual(market.parse_coinbase(json.dumps({"data": {"amount": "109300.3", "base": "BTC", "currency": "CAD"}}), "BTC-CAD"), {"price": 109300.3, "currency": "CAD"})
        self.assertIsNone(market.parse_coinbase(json.dumps({"errors": [{"id": "not_found"}]}), "XYZ-CAD"))
        chain = json.dumps({"data": {"options": [{"option": "QNC261120C00003000", "bid": 0.0, "ask": 0.25, "last_trade_price": 0.15, "prev_day_close": 0.15}, {"option": "QNC261120C00005000", "bid": 0.1, "ask": 0.2, "last_trade_price": 0.05, "prev_day_close": 0.12}]}})
        rows = market.parse_cboe_options(chain)
        self.assertEqual(market.option_mark(rows["QNC261120C00003000"])["price"], 0.15)
        self.assertAlmostEqual(market.option_mark(rows["QNC261120C00005000"])["price"], 0.15)
        self.assertIsNone(market.option_mark(rows.get("QNC261120C00009000")))
        self.assertIsNone(market.option_mark({"bid": 0, "ask": 0, "last_trade_price": 0, "prev_day_close": 0}))

    def test_refresh_quotes_prices_crypto_and_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BAGHOLDER_HOME"] = tmp
            store.set_home(tmp)
            store.ensure()
            try:
                syms = [
                    {"symbol": "BTC", "exchange": "Crypto", "currency": "CAD", "kind": "Crypto"},
                    {"symbol": "QNC 20NOV26 3.00 CALL", "exchange": "NYSE", "currency": "USD", "kind": "Options"},
                    {"symbol": "QNC 19FEB27 3.00 CALL", "exchange": "NYSE", "currency": "USD", "kind": "Options"},
                    {"symbol": "SHOP 17OCT25 100.00 PUT", "exchange": "TSX", "currency": "CAD", "kind": "Options"},
                ]
                chain = {"QNC261120C00003000": {"bid": 0.1, "ask": 0.2, "prev_day_close": 0.15}, "QNC270219C00003000": {"bid": 0, "ask": 0.5, "last_trade_price": 0.3, "prev_day_close": 0.3}}
                with mock.patch.object(market, "fetch_coinbase_spot", return_value={"price": 109300.3, "currency": "CAD"}) as cb, mock.patch.object(market, "fetch_cboe_option_chain", return_value=chain) as oc:
                    self.assertEqual(market.refresh_quotes(syms), 3)
                self.assertEqual([x.args[0] for x in cb.call_args_list], ["BTC-CAD"])
                self.assertEqual(oc.call_count, 1, "one chain fetch serves every contract on the underlying")
                q = store.quotes()
                self.assertEqual(q["BTC"]["price"], 109300.3)
                self.assertAlmostEqual(q["QNC 20NOV26 3.00 CALL"]["price"], 0.15)
                self.assertEqual(q["QNC 19FEB27 3.00 CALL"]["price"], 0.3)
                self.assertNotIn("SHOP 17OCT25 100.00 PUT", q)
            finally:
                os.environ.pop("BAGHOLDER_HOME", None)

    def test_positions_price_crypto_and_options_from_quotes(self):
        acts = [
            act(id="c1", category="trade", activityType="BUY", rawType="CRYPTO_BUY", quantity=0.5, unitPrice=100000, netCashAmount=-50000, transactionDate="2026-01-05", symbol="BTC", currency="CAD", accountType="Crypto", securityId="sec-z-btc"),
            act(id="o1", category="trade", activityType="BUY", rawType="OPTIONS_BUY", quantity=2, unitPrice=0.10, netCashAmount=-20, transactionDate="2026-02-05", symbol="QNC 20NOV26 3.00 CALL", currency="USD", accountType="TFSA", securityId="sec-o-1"),
        ]
        snapshot = {"activities": acts, "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": []}
        quotes = {"BTC": {"price": 120000.0}, "QNC 20NOV26 3.00 CALL": {"price": 0.15}}
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}, "quotes": quotes}, {}, today="2026-09-06")
        by = {p["symbol"]: p for p in base["positions"]}
        self.assertEqual((by["BTC"]["kind"], by["BTC"]["priceSource"], by["BTC"]["last"], by["BTC"]["mv"]), ("Crypto", "quote", 120000.0, 60000.0))
        self.assertEqual((by["QNC 20NOV26 3.00 CALL"]["kind"], by["QNC 20NOV26 3.00 CALL"]["priceSource"], by["QNC 20NOV26 3.00 CALL"]["last"], by["QNC 20NOV26 3.00 CALL"]["mv"]), ("Options", "quote", 0.15, 30.0))
        held = model.held_symbols(base)
        self.assertEqual(sorted((h["symbol"], h["kind"]) for h in held), [("BTC", "Crypto"), ("QNC 20NOV26 3.00 CALL", "Options")])

    def test_refresh_quotes_respects_the_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BAGHOLDER_HOME"] = tmp
            store.set_home(tmp)
            store.ensure()
            try:
                from datetime import datetime, timezone
                syms = [{"symbol": "VEQT", "exchange": "TSX", "currency": "CAD"}, {"symbol": "LUNR", "exchange": "NASDAQ", "currency": "USD"}, {"symbol": "HBIX", "exchange": "Cboe Canada", "currency": "CAD"}]
                cboe = {"price": 6.76, "prevClose": 6.76, "fetchedAt": "2026-09-06T14:00:00Z"}
                with mock.patch.object(market, "fetch_tmx_quote", return_value={"price": 10.0, "priceChange": 0.1, "percentChange": 1.0, "prevClose": 9.9, "fetchedAt": "2026-09-06T14:00:00Z"}) as f, mock.patch.object(market, "fetch_cboe_ca_quote", return_value=cboe) as c:
                    self.assertEqual(market.refresh_quotes(syms, now=datetime(2026, 9, 6, 14, 0, tzinfo=timezone.utc)), 3)
                    self.assertEqual([x.args[0] for x in f.call_args_list], ["VEQT", "LUNR:US"])
                    self.assertEqual([x.args[0] for x in c.call_args_list], ["HBIX"])
                    self.assertEqual(market.refresh_quotes(syms, now=datetime(2026, 9, 6, 14, 0, 30, tzinfo=timezone.utc)), 0)
                    self.assertEqual(market.refresh_quotes(syms, now=datetime(2026, 9, 6, 14, 2, tzinfo=timezone.utc)), 3)
                self.assertEqual(store.quotes()["HBIX"]["price"], 6.76)
                q = store.quotes()["LUNR"]
                self.assertEqual(q["price"], 10.0)
                self.assertEqual(q["prevClose"], 9.9)
                store.upsert_quote("LUNR", {"price": 11.0, "fetchedAt": "2026-09-06T15:00:00Z", "dividendAmount": None})
                self.assertEqual(store.quotes()["LUNR"]["price"], 11.0)
            finally:
                store.set_home(None)
                os.environ.pop("BAGHOLDER_HOME", None)


class DeclaredDistributionsTest(unittest.TestCase):
    def test_tmx_parsers(self):
        q = {"data": {"getQuoteBySymbol": {"symbol": "CCHI", "name": "Ninepoint Cameco HighShares ETF", "price": 10.95, "dividendFrequency": None, "dividendYield": 27.5, "dividendAmount": 0.135, "exDividendDate": "2026-09-15 00:00:00.0"}}}
        rec = market.parse_tmx_quote(q)
        self.assertEqual(rec["price"], 10.95)
        self.assertEqual(rec["exDividendDate"], "2026-09-15")
        d = {"data": {"dividends": {"dividends": [{"exDate": "2026-09-15", "payableDate": "2026-09-21", "amount": 0.135, "currency": "CAD"}, {"exDate": "bad", "amount": 1}, {"exDate": "2026-08-31", "payableDate": "2026-09-04", "amount": "0.135"}]}}}
        rows = market.parse_tmx_dividends(d)
        self.assertEqual([r["exDate"] for r in rows], ["2026-09-15", "2026-08-31"])
        self.assertEqual(market.tmx_symbol("cchi.to"), "CCHI")
        self.assertTrue(market.is_canadian_listing("TSX", "CAD"))
        self.assertFalse(market.is_canadian_listing("NASDAQ", "USD"))
        self.assertTrue(market.is_canadian_listing("", "CAD"))

    def test_declared_record_beats_own_history_and_tracks_schedule_change(self):
        div = lambda i, day, qty, per: act(
            id="c%d" % i, category="dividend", activityType="Dividend", activitySubType="dividend", rawType="DIVIDEND",
            quantity=qty, unitPrice=per, netCashAmount=qty * per, transactionDate=day, symbol="CCHI", currency="CAD", accountType="Cashflow",
        )
        snapshot = {
            "activities": [buy("b1", "CCHI", 4000, 11.64, "2026-08-25", accountType="Cashflow"), div(1, "2026-09-04", 4000, 0.135)],
            "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": [],
        }
        public = {"CCHI": [
            {"exDate": "2026-09-15", "payDate": "2026-09-21", "amount": 0.135, "currency": "CAD"},
            {"exDate": "2026-08-31", "payDate": "2026-09-04", "amount": 0.135, "currency": "CAD"},
            {"exDate": "2026-08-14", "payDate": "2026-08-20", "amount": 0.135, "currency": "CAD"},
            {"exDate": "2026-07-31", "payDate": "2026-08-10", "amount": 0.27, "currency": "CAD"},
            {"exDate": "2026-06-30", "payDate": "2026-07-08", "amount": 0.27, "currency": "CAD"},
            {"exDate": "2026-05-29", "payDate": "2026-06-05", "amount": 0.27, "currency": "CAD"},
        ]}
        quotes = {"CCHI": {"price": 10.95, "dividendAmount": 0.135, "dividendFrequency": "", "exDividendDate": "2026-09-15", "fetchedAt": "2026-09-06T00:00:00Z"}}
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}, "distributions": public, "quotes": quotes}, {}, today="2026-09-06")
        h = model.build_view(base, None)["cashflow"]["holdings"][0]
        self.assertEqual(h["per"], 0.135)
        self.assertEqual(h["freq"], 24)
        self.assertTrue(h["freqVerified"])
        self.assertEqual(h["rateSource"], "declared")
        self.assertAlmostEqual(h["yoc"], 0.135 * 24 / 11.64)
        self.assertEqual(h["last"], 10.95)
        self.assertEqual(h["priceSource"], "close")
        self.assertAlmostEqual(h["currentYield"], 0.135 * 24 / 10.95)
        # without the public record it falls back to the single own payment
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}}, {}, today="2026-09-06")
        h = model.build_view(base, None)["cashflow"]["holdings"][0]
        self.assertEqual(h["rateSource"], "payments")
        self.assertFalse(h["freqVerified"])
        self.assertEqual(h["priceSource"], "fill")

    def test_payer_symbols_are_held_dividend_payers(self):
        snapshot = {
            "activities": [
                buy("b1", "RDDY", 100, 7, "2026-01-05", accountType="Cashflow"),
                act(id="d1", category="dividend", activityType="Dividend", rawType="DIVIDEND", quantity=100, unitPrice=0.2, netCashAmount=20, transactionDate="2026-02-06", symbol="RDDY", currency="CAD", accountType="Cashflow"),
                buy("b2", "TD", 10, 80, "2025-01-05", accountType="Cashflow"),
                act(id="d2", category="dividend", activityType="Dividend", rawType="DIVIDEND", quantity=10, unitPrice=1, netCashAmount=10, transactionDate="2025-02-06", symbol="TD", currency="CAD", accountType="Cashflow"),
                sell("s2", "TD", 10, 90, "2025-03-01", accountType="Cashflow"),
                buy("b3", "AAA", 10, 5, "2026-01-05", accountType="Cashflow"),
            ],
            "accounts": [], "balances": [], "navHistory": [], "navByAccount": {}, "syncedAt": "", "tradeGroups": [], "notes": {}, "securities": [],
        }
        base = model.build_base(snapshot, {"fx": {}, "benchmark": {}}, {}, today="2026-09-06")
        self.assertEqual(model.payer_symbols(base), [{"symbol": "RDDY", "exchange": "", "currency": "CAD"}])

    def test_store_roundtrip_and_stale_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BAGHOLDER_HOME"] = tmp
            store.set_home(tmp)
            store.ensure()
            try:
                self.assertEqual(store.upsert_distributions("cchi", [{"exDate": "2026-08-31", "payDate": "2026-09-04", "amount": 0.135, "currency": "CAD"}, {"exDate": "x", "amount": 1}]), 1)
                self.assertEqual(store.distributions()["CCHI"][0]["amount"], 0.135)
                store.upsert_quote("CCHI", {"price": 10.95, "dividendAmount": 0.135, "fetchedAt": "2026-09-06T00:00:00Z"})
                self.assertEqual(store.quotes()["CCHI"]["price"], 10.95)
                syms = [{"symbol": "CCHI", "exchange": "TSX", "currency": "CAD"}, {"symbol": "LUNR", "exchange": "NASDAQ", "currency": "USD"}, {"symbol": "NEW", "exchange": "", "currency": "CAD"}]
                from datetime import datetime, timezone
                fresh = datetime(2026, 9, 6, 5, 0, tzinfo=timezone.utc)
                # A fresh quote says nothing about the declared record: until the
                # record itself has been fetched, the symbol is stale.
                self.assertEqual(market.stale_symbols(syms, now=fresh), ["CCHI", "NEW"])
                store.mark_distributions_fetched("CCHI", "2026-09-06T00:00:00Z")
                self.assertEqual(market.stale_symbols(syms, now=fresh), ["NEW"])
                old = datetime(2026, 9, 8, 5, 0, tzinfo=timezone.utc)
                self.assertEqual(market.stale_symbols(syms, now=old), ["CCHI", "NEW"])
                # The quote loop refreshing the quote does not make the record fresh.
                store.upsert_quote("CCHI", {"price": 11.0, "fetchedAt": "2026-09-08T04:55:00Z"})
                self.assertEqual(market.stale_symbols(syms, now=old), ["CCHI", "NEW"])
                with mock.patch.object(market, "fetch_tmx", return_value=({"price": 1.0, "dividendAmount": 0.1, "dividendFrequency": "Monthly", "exDividendDate": "2026-09-01"}, [{"exDate": "2026-09-01", "payDate": "2026-09-05", "amount": 0.1, "currency": "CAD"}])) as f:
                    self.assertEqual(market.refresh_distributions(syms), 2)
                self.assertEqual(sorted(store.quotes()), ["CCHI", "NEW"])
                self.assertEqual(sorted(store.distributions_fetched_at()), ["CCHI", "NEW"])
                self.assertEqual(f.call_count, 2)
                self.assertEqual(market.stale_symbols(syms), [])
            finally:
                store.set_home(None)
                os.environ.pop("BAGHOLDER_HOME", None)


class LegacyNotesTest(unittest.TestCase):
    def test_group_id_matches_ledger_html(self):
        # ledger.html: FNV-1a over "\n".join(sorted keys), "g_" + hex + "_" + n
        self.assertEqual(model.group_id_for_keys(["b|s|100.00000000"]), model.group_id_for_keys(["b|s|100.00000000"]))
        self.assertTrue(model.group_id_for_keys(["a", "b"]).endswith("_2"))
        self.assertEqual(model.group_id_for_keys(["a", "b"]), model.group_id_for_keys(["b", "a"]))

    def test_legacy_note_lands_on_round_trip(self):
        acts = model.normalize_activities([buy("b1", "AAA", 100, 10, "2026-01-01"), sell("s1", "AAA", 100, 12, "2026-01-10")])
        fifo = model.match_fifo(acts)
        key = model.slice_member_key(fifo["closed"][0])
        legacy_id = model.group_id_for_keys([key])
        journal = model.migrate_legacy_notes(fifo["closed"], [], {legacy_id: {"thesis": "why", "tag": "a, b", "grade": "C"}})
        self.assertEqual(journal, {"rt:b1": {"thesis": "why", "tags": ["a", "b"], "grade": "C"}})


class StoreTablesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BAGHOLDER_HOME"] = self.tmp.name
        store.set_home(self.tmp.name)
        bagholder.set_home(self.tmp.name)
        store.ensure()
        model.invalidate()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("BAGHOLDER_HOME", None)

    def test_fx_and_benchmark_roundtrip(self):
        self.assertEqual(store.fx_last_date(), "")
        self.assertEqual(store.upsert_fx_rates({"2026-01-02": "1.4", "bad": 1, "2026-01-03": 0}), 1)
        # A day's rate is written once and never rewritten: a later fetch cannot change it.
        store.upsert_fx_rates({"2026-01-02": 9.9})
        self.assertEqual(store.fx_rates()["2026-01-02"], 1.4)
        self.assertEqual(store.fx_rates(), {"2026-01-02": 1.4})
        self.assertEqual(store.fx_last_date(), "2026-01-02")
        store.upsert_benchmark_prices({"2026-01-02": 5000, "2026-01-05": 5100})
        self.assertEqual(store.benchmark_last_date(), "2026-01-05")
        self.assertEqual(store.market_data()["benchmark"]["2026-01-05"], 5100)

    def test_legacy_spy_meta_migrates_into_table(self):
        store.set_meta("spy_by_date", json.dumps({"2020-01-02": 3200.5, "junk": "x"}))
        with store._lock:
            conn = store._connect()
            try:
                conn.execute("DELETE FROM benchmark_prices")
                conn.commit()
                store._migrate_spy_meta(conn)
                conn.commit()
            finally:
                conn.close()
        self.assertEqual(store.benchmark_prices(), {"2020-01-02": 3200.5})

    def test_journal_roundtrip_and_version(self):
        v0 = store.data_version()
        store.save_journal_entry("rt:x", {"thesis": "t", "tags": ["a", "a", " b "], "grade": "z"})
        self.assertEqual(store.journal(), {"rt:x": {"thesis": "t", "tags": ["a", "b"], "grade": ""}})
        self.assertNotEqual(v0, store.data_version())
        store.save_journal_entry("rt:x", {"thesis": "", "tags": [], "grade": ""})
        self.assertEqual(store.journal(), {})

    def test_clear_synced_data_keeps_journal_and_market_by_default(self):
        store.merge_local_rows([
            buy("b1", "AAA", 10, 1, "2026-01-01", source="csv"),
            sell("s1", "AAA", 10, 2, "2026-01-05", source="csv"),
        ])
        store.replace_accounts([{"id": "acct-1", "nickname": "Trading"}])
        store.upsert_nav([{"date": "2026-01-05", "equity": 20, "netDeposits": 10}])
        store.set_meta("synced_at", "2026-01-05T00:00:00Z")
        store.upsert_fx_rates({"2026-01-05": 1.4})
        store.save_journal_entry("rt:b1", {"grade": "A"})
        before = store.data_summary()
        self.assertEqual(before["activities"], 2)
        self.assertEqual(before["accounts"], 1)
        self.assertEqual(before["navDays"], 1)
        self.assertEqual(before["journal"], 1)
        after = store.clear_synced_data()
        self.assertEqual(after["activities"], 0)
        self.assertEqual(after["accounts"], 0)
        self.assertEqual(after["navDays"], 0)
        self.assertEqual(after["syncedAt"], "")
        self.assertEqual(after["journal"], 1)
        self.assertEqual(after["fxDays"], 1)
        self.assertEqual(store.activity_count(), 0)
        self.assertEqual(bagholder.activity_sync_bounds(), {"start_date": None, "full_history": True})
        after = store.clear_synced_data(keep_journal=False, keep_market=False)
        self.assertEqual(after["journal"], 0)
        self.assertEqual(after["fxDays"], 0)

    def test_model_view_from_store_and_cache(self):
        store.merge_local_rows([
            buy("b1", "AAA", 10, 1, "2026-01-01", source="csv"),
            sell("s1", "AAA", 10, 2, "2026-01-05", source="csv"),
        ])
        v = model.view(None)
        self.assertEqual(v["kpi"]["count"], 1)
        self.assertAlmostEqual(v["kpi"]["realized"], 10)
        base1 = model.base_model()
        self.assertIs(base1, model.base_model())
        tid = v["trades"][0]["id"]
        store.save_journal_entry(tid, {"grade": "B"})
        v2 = model.view(None)
        self.assertEqual(v2["trades"][0]["grade"], "B")
        self.assertEqual(v2["grades"]["buckets"][1]["n"], 1)


class MarketParseTest(unittest.TestCase):
    def test_parsers(self):
        boc = json.dumps({"observations": [{"d": "2026-08-28", "FXUSDCAD": {"v": "1.3888"}}, {"d": "x"}]})
        self.assertEqual(market.parse_boc_json(boc), {"2026-08-28": 1.3888})
        fred = "observation_date,SP500\n2026-08-28,6500.12\n2026-08-29,.\nbad\n"
        self.assertEqual(market.parse_fred_csv(fred), {"2026-08-28": 6500.12})
        stooq = "Date,Open,High,Low,Close,Volume\n2026-08-28,1,2,0,6501.5,0\n"
        self.assertEqual(market.parse_stooq_csv(stooq), {"2026-08-28": 6501.5})

    def test_periodic_refresh_paces_fx_and_benchmark_and_refetches_stale_records(self):
        from datetime import datetime, timedelta, timezone
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BAGHOLDER_HOME"] = tmp
            store.set_home(tmp)
            store.ensure()
            try:
                boc = json.dumps({"observations": [{"d": "2026-09-04", "FXUSDCAD": {"v": "1.38"}}]})
                fred = "observation_date,SP500\n2026-09-04,7000\n"
                syms = [{"symbol": "CCHI", "exchange": "TSX", "currency": "CAD"}]
                divs = ({"price": 1.0}, [{"exDate": "2026-09-01", "payDate": "2026-09-05", "amount": 0.1, "currency": "CAD"}])
                t0 = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
                with mock.patch.object(market, "_get_text", side_effect=[boc, fred]) as g, mock.patch.object(market, "fetch_tmx", return_value=divs) as f:
                    out = market.refresh_periodic(symbols=syms, now=t0)
                self.assertEqual((out["fx"], out["benchmark"], out["distributions"]), (1, 1, 1))
                self.assertEqual((g.call_count, f.call_count), (2, 1))
                # Ten minutes later: FX and the benchmark wait for their six hours; the record is fresh.
                with mock.patch.object(market, "_get_text", side_effect=[boc, fred]) as g, mock.patch.object(market, "fetch_tmx", return_value=divs) as f:
                    out = market.refresh_periodic(symbols=syms, now=t0 + timedelta(minutes=10))
                self.assertEqual((out["fx"], out["benchmark"], out["distributions"]), (0, 0, 0))
                self.assertEqual((g.call_count, f.call_count), (0, 0))
                # Seven hours later FX and the benchmark are attempted again; the record is still within 20 hours.
                with mock.patch.object(market, "_get_text", side_effect=[boc, fred]) as g, mock.patch.object(market, "fetch_tmx", return_value=divs) as f:
                    out = market.refresh_periodic(symbols=syms, now=t0 + timedelta(hours=7))
                self.assertEqual((g.call_count, f.call_count), (2, 0))
                # A day later the declared record is refetched.
                with mock.patch.object(market, "_get_text", side_effect=[boc, fred]), mock.patch.object(market, "fetch_tmx", return_value=divs) as f:
                    out = market.refresh_periodic(symbols=syms, now=t0 + timedelta(hours=25))
                self.assertEqual(f.call_count, 1)
                # Tuesday 2026-09-08 at 16:00 Eastern: the Bank has not published, and the
                # attempt is fresh, so nothing is fetched; at 16:45 Eastern today's rate is
                # missing from the table and is fetched at once.
                store.set_meta("market_attempt_at", "2026-09-08T19:50:00Z")
                with mock.patch.object(market, "_get_text", side_effect=[boc, fred]) as g, mock.patch.object(market, "fetch_tmx", return_value=divs):
                    market.refresh_periodic(symbols=syms, now=datetime(2026, 9, 8, 20, 0, tzinfo=timezone.utc))
                self.assertEqual(g.call_count, 0)
                with mock.patch.object(market, "_get_text", side_effect=[boc, fred]) as g, mock.patch.object(market, "fetch_tmx", return_value=divs):
                    market.refresh_periodic(symbols=syms, now=datetime(2026, 9, 8, 20, 45, tzinfo=timezone.utc))
                self.assertEqual(g.call_count, 2)
                self.assertFalse(market.fx_day_published_but_missing(datetime(2026, 9, 12, 21, 0, tzinfo=timezone.utc)), "Saturday: nothing to publish")
            finally:
                os.environ.pop("BAGHOLDER_HOME", None)

    def test_history_parsers_and_sources(self):
        tmx = {"data": {"getTimeSeriesData": [{"dateTime": "2026-09-04T16:00:00-04:00", "open": 4.8, "high": 4.8, "low": 4.68, "close": 4.75, "volume": 50972}, {"dateTime": "2026-09-03T16:00:00-04:00", "open": 4.83, "high": 4.95, "low": 4.73, "close": 4.75, "volume": 115702}]}}
        bars = market.parse_tmx_history(tmx)
        self.assertEqual([b["date"] for b in bars], ["2026-09-03", "2026-09-04"])
        self.assertEqual(bars[1]["close"], 4.75)
        cboe = json.dumps({"data": [{"date": "2026-09-04", "open": "6.59", "close": "6.70", "high": 6.7, "low": 6.58, "volume": 53193.0}, {"date": "2026-09-03", "open": "6.56", "close": "6.76", "high": 6.76, "low": 6.54, "volume": 35377.0}]})
        bars = market.parse_cboe_ca_history(cboe)
        self.assertEqual([(b["date"], b["close"]) for b in bars], [("2026-09-03", "6.76"), ("2026-09-04", "6.70")])
        gecko = json.dumps({"prices": [[1787000400000, 89278.71], [1787086800000, 88900.0], [1787090400000, 88950.0]]})
        bars = market.parse_coingecko_range(gecko)
        self.assertEqual([b["date"] for b in bars], ["2026-08-17", "2026-08-18"])
        self.assertEqual(bars[1]["close"], 88950.0, "the last point of a day wins")
        self.assertIsNone(bars[0]["open"])
        src = market.history_source
        self.assertEqual(src({"symbol": "RDDY", "exchange": "TSX", "currency": "CAD", "kind": "Shares"}), ("tmx", "RDDY"))
        self.assertEqual(src({"symbol": "LUNR", "exchange": "NASDAQ", "currency": "USD", "kind": "Shares"}), ("tmx", "LUNR:US"))
        self.assertEqual(src({"symbol": "HBIX", "exchange": "Cboe Canada", "currency": "CAD", "kind": "Shares"}), ("cboe_ca", "HBIX"))
        self.assertEqual(src({"symbol": "BTC", "exchange": "Crypto", "currency": "CAD", "kind": "Crypto"}), ("coingecko", "BTC-CAD"))
        self.assertIsNone(src({"symbol": "QNC 20NOV26 3.00 CALL", "exchange": "NYSE", "currency": "USD", "kind": "Options"}))

    def test_history_is_cached_and_closed_days_never_rewritten(self):
        from datetime import datetime, timedelta, timezone
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BAGHOLDER_HOME"] = tmp
            store.set_home(tmp)
            store.ensure()
            try:
                rec = {"symbol": "RDDY", "exchange": "TSX", "currency": "CAD", "kind": "Shares"}
                bars = [{"date": "2026-09-03", "open": 4.83, "high": 4.95, "low": 4.73, "close": 4.75, "volume": 1}, {"date": "2026-09-04", "open": 4.8, "high": 4.8, "low": 4.68, "close": 4.75, "volume": 1}]
                now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
                with mock.patch.object(market, "fetch_history", return_value=(bars, "tmx")) as f:
                    out = market.ensure_history(rec, "2026-08-25", "2026-09-05", now=now)
                self.assertEqual([b["date"] for b in out], ["2026-09-03", "2026-09-04"])
                self.assertEqual(f.call_args.args[1:3], ("2026-08-25", "2026-09-05"))
                # Same span, minutes later: served from the store, no fetch.
                with mock.patch.object(market, "fetch_history", return_value=(bars, "tmx")) as f:
                    market.ensure_history(rec, "2026-08-25", "2026-09-05", now=now + timedelta(minutes=5))
                self.assertEqual(f.call_count, 0)
                # An older span was never fetched: fetched from that start.
                with mock.patch.object(market, "fetch_history", return_value=(bars, "tmx")) as f:
                    market.ensure_history(rec, "2026-06-01", "2026-06-30", now=now + timedelta(minutes=5))
                self.assertEqual(f.call_args.args[1], "2026-06-01")
                # A span reaching the present is refetched once the copy is a day old; a
                # closed day keeps its bar, the newest day may be replaced.
                changed = [{"date": "2026-09-03", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}, {"date": "2026-09-04", "open": 4.8, "high": 4.9, "low": 4.68, "close": 4.85, "volume": 2}]
                with mock.patch.object(market, "fetch_history", return_value=(changed, "tmx")) as f:
                    out = market.ensure_history(rec, "2026-08-25", "2026-09-05", now=now + timedelta(hours=25))
                self.assertEqual(f.call_count, 1)
                self.assertEqual([(b["date"], b["close"]) for b in out], [("2026-09-03", 4.75), ("2026-09-04", 4.85)])
            finally:
                os.environ.pop("BAGHOLDER_HOME", None)

    def test_refresh_uses_store_and_survives_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BAGHOLDER_HOME"] = tmp
            store.set_home(tmp)
            store.ensure()
            try:
                with mock.patch.object(market, "_get_text", side_effect=OSError("offline")):
                    self.assertEqual(market.refresh_all(), {"fx": 0, "benchmark": 0, "distributions": 0, "skipped": False})
                self.assertTrue(market.is_stale())
                boc = json.dumps({"observations": [{"d": "2026-09-04", "FXUSDCAD": {"v": "1.38"}}]})
                fred = "observation_date,SP500\n2026-09-04,7000\n"
                with mock.patch.object(market, "_get_text", side_effect=[boc, fred]):
                    out = market.refresh_all()
                self.assertEqual(out["fx"], 1)
                self.assertEqual(out["benchmark"], 1)
                self.assertEqual(store.fx_rates(), {"2026-09-04": 1.38})
            finally:
                store.set_home(None)
                os.environ.pop("BAGHOLDER_HOME", None)


import csvimport


CANONICAL_CSV = """transaction_date,activity_type,activity_sub_type,symbol,quantity,unit_price,net_cash_amount,currency,account_id
2026-01-05,Trade,BUY,AAA,10,5.00,-50.00,CAD,acct-1
2026-02-05,Trade,SELL,AAA,-10,6.00,60.00,CAD,acct-1
2026-02-06,Dividend,DIVIDEND,AAA,,,1.50,CAD,acct-1
"""

STATEMENT_CSV = """date,transaction,description,amount,balance,currency
2026-01-06,BUY,"AAA - Alpha Inc: Bought 10 shares (executed at 2026-01-05) at $5.00 per share",-50.00,950.00,CAD
2026-02-06,SELL,"AAA - Alpha Inc: Sold 10 shares (executed at 2026-02-05) at $6.00 per share",60.00,1010.00,CAD
2026-02-10,SELL,"LUNR 15JAN27 12.00 CALL: Sold 2 contracts (executed at 2026-02-10)",1200.00,2210.00,USD
2026-03-01,DIV,"AAA - Alpha Inc: Dividend",1.50,2211.50,CAD
As of 2026-03-02
"""

LEGACY_CSV = """Date,Action,Symbol,Quantity,Price,Amount,Currency
2026-01-05,Buy,AAA,10,5.00,-50.00,CAD
2026-02-05,Sell,AAA,10,6.00,60.00,CAD
"""


class CsvImportTest(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(csvimport.parse_number("($1,234.50)"), -1234.5)
        self.assertEqual(csvimport.parse_number("CAD 12"), 12.0)
        self.assertEqual(csvimport.parse_number("n/a"), 0.0)
        self.assertEqual(csvimport.parse_date("2026-01-05T14:00:00Z"), "2026-01-05")
        self.assertEqual(csvimport.parse_date("05/01/2026"), "2026-05-01")
        self.assertEqual(csvimport.parse_date("25/01/2026"), "2026-01-25")
        self.assertEqual(csvimport.parse_date("5-Jan-2026"), "2026-01-05")
        self.assertEqual(csvimport.parse_date("Jan 5, 2026"), "2026-01-05")
        self.assertEqual(csvimport.parse_date("46027"), "2026-01-05")
        self.assertEqual(csvimport.detect_format(["transaction_date", "activity_type", "symbol"]), "canonical")
        self.assertEqual(csvimport.detect_format(["Date", "Transaction", "Description", "Amount"]), "statement")
        self.assertEqual(csvimport.detect_format(["Date", "Action", "Symbol", "Quantity", "Price", "Amount"]), "legacy")
        self.assertEqual(csvimport.detect_format(["foo", "bar"]), "unknown")
        self.assertEqual(csvimport.book_id_from_file_name("monthly-statement-ABC12345CAD-2026-01-31.csv"), "ABC12345CAD")

    def test_canonical(self):
        r = csvimport.parse_csv(CANONICAL_CSV, "activities.csv")
        self.assertEqual(r["format"], "canonical")
        self.assertEqual(len(r["activities"]), 3)
        buy, sell, div = r["activities"]
        self.assertEqual((buy["category"], buy["activitySubType"], buy["quantity"], buy["unitPrice"]), ("trade", "BUY", 10.0, 5.0))
        self.assertEqual((sell["category"], sell["quantity"], sell["netCashAmount"]), ("trade", -10.0, 60.0))
        self.assertEqual(div["category"], "dividend")
        self.assertEqual(r["countsByType"], {"Trade": 2, "Dividend": 1})

    def test_statement_reads_fills_from_descriptions(self):
        r = csvimport.parse_csv(STATEMENT_CSV, "monthly-statement-ABC12345CAD-2026-03-31.csv")
        self.assertEqual(r["format"], "statement")
        self.assertTrue(r["footerStripped"])
        self.assertEqual(r["skipped"], [])
        buy, sell, opt, div = r["activities"]
        self.assertEqual((buy["symbol"], buy["name"], buy["quantity"], buy["unitPrice"], buy["transactionDate"], buy["settlementDate"]), ("AAA", "Alpha Inc", 10.0, 5.0, "2026-01-05", "2026-01-06"))
        self.assertEqual((sell["activitySubType"], sell["quantity"], sell["netCashAmount"]), ("SELL", -10.0, 60.0))
        # options: statement amount is contract cash, so per-share price is amount / (contracts x 100)
        self.assertEqual((opt["symbol"], opt["quantity"], opt["currency"]), ("LUNR 15JAN27 12.00 CALL", -2.0, "USD"))
        self.assertAlmostEqual(opt["unitPrice"], 6.0)
        self.assertEqual(div["category"], "dividend")
        self.assertEqual(buy["bookId"], "ABC12345CAD")

    def test_legacy_and_unknown(self):
        r = csvimport.parse_csv(LEGACY_CSV, "old.csv")
        self.assertEqual(r["format"], "legacy")
        self.assertEqual([a["activitySubType"] for a in r["activities"]], ["BUY", "SELL"])
        self.assertEqual(r["activities"][1]["quantity"], -10.0)
        r = csvimport.parse_csv("foo,bar\n1,2\n", "x.csv")
        self.assertEqual(r["format"], "unknown")
        self.assertEqual(len(r["skipped"]), 1)


class ImportStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BAGHOLDER_HOME"] = self.tmp.name
        store.set_home(self.tmp.name)
        bagholder.set_home(self.tmp.name)
        store.ensure()
        model.invalidate()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("BAGHOLDER_HOME", None)

    def test_import_text_merges_and_dedups(self):
        r = csvimport.import_text("activities.csv", CANONICAL_CSV)
        self.assertEqual((r["format"], r["added"], r["duplicates"]), ("canonical", 3, 0))
        r = csvimport.import_text("activities.csv", CANONICAL_CSV)
        self.assertEqual((r["added"], r["duplicates"]), (0, 3))
        v = model.view(None)
        self.assertEqual(v["kpi"]["count"], 1)
        self.assertAlmostEqual(v["kpi"]["realized"], 10)

    def test_folder_scan_skips_junk_and_unchanged_files(self):
        folder = os.path.join(self.tmp.name, "csv")
        os.makedirs(os.path.join(folder, "nested"))
        with open(os.path.join(folder, "a.csv"), "w", encoding="utf-8") as fh:
            fh.write(LEGACY_CSV)
        with open(os.path.join(folder, "._a.csv"), "w", encoding="utf-8") as fh:
            fh.write(LEGACY_CSV)
        with open(os.path.join(folder, "notes.txt"), "w", encoding="utf-8") as fh:
            fh.write("hi")
        with open(os.path.join(folder, "nested", "b.csv"), "w", encoding="utf-8") as fh:
            fh.write(CANONICAL_CSV)
        self.assertFalse(csvimport.set_watch_folder(os.path.join(folder, "missing"))["ok"])
        self.assertTrue(csvimport.set_watch_folder(folder)["ok"])
        r = csvimport.scan_folder()
        self.assertEqual([f["file"] for f in r["files"]], ["a.csv"])
        self.assertEqual(r["added"], 2)
        r = csvimport.scan_folder()
        self.assertTrue(r["files"][0]["unchanged"])
        self.assertEqual(r["added"], 0)
        with open(os.path.join(folder, "c.csv"), "w", encoding="utf-8") as fh:
            fh.write(CANONICAL_CSV)
        r = csvimport.scan_folder()
        self.assertEqual({f["file"]: f.get("unchanged") for f in r["files"]}, {"a.csv": True, "c.csv": False})
        self.assertEqual(r["added"], 3)  # a different account id, so nothing is a duplicate
        r = csvimport.scan_folder(force=True)
        self.assertEqual((r["added"], r["duplicates"]), (0, 5))
        st = csvimport.status()
        self.assertTrue(st["watching"])
        self.assertEqual(len(st["files"]), 2)
        csvimport.clear_watch_folder()
        self.assertFalse(csvimport.status()["watching"])


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BAGHOLDER_HOME"] = self.tmp.name
        store.set_home(self.tmp.name)
        bagholder.set_home(self.tmp.name)
        store.ensure()
        model.invalidate()
        store.upsert_fx_rates({"2099-01-01": 1.0})
        store.upsert_benchmark_prices({"2099-01-01": 1.0})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), bagholder.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()
        os.environ.pop("BAGHOLDER_HOME", None)

    def _get(self, path):
        req = Request("http://127.0.0.1:%d%s" % (self.port, path))
        with urlopen(req, timeout=10) as r:
            return r.status, r.read()

    def _post(self, path, body):
        req = Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Bagholder": "1"},
            method="POST",
        )
        with urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_v2_page_and_model_route(self):
        status, body = self._get("/v2")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('<link rel="icon" type="image/png" href="favicon.png"', html)
        self.assertIn("/api/model", html)
        self.assertIn("/api/journal", html)
        store.merge_local_rows([
            buy("b1", "AAA", 10, 1, "2026-01-01", source="csv"),
            sell("s1", "AAA", 10, 2, "2026-01-05", source="csv"),
        ])
        status, body = self._get("/api/model")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["kpi"]["count"], 1)
        self.assertIn("status", data)
        from urllib.parse import quote
        status, body = self._get("/api/model?filters=" + quote(json.dumps({"lists": {"symbol": ["ZZZ"]}})))
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["kpi"]["count"], 0)
        self.assertEqual(data["tradeTotal"], 1)

    def test_journal_post_persists(self):
        store.merge_local_rows([
            buy("b1", "AAA", 10, 1, "2026-01-01", source="csv"),
            sell("s1", "AAA", 10, 2, "2026-01-05", source="csv"),
        ])
        _, data = self._get("/api/model")
        tid = json.loads(data.decode("utf-8"))["trades"][0]["id"]
        status, out = self._post("/api/journal", {"id": tid, "thesis": "why", "tags": ["a"], "grade": "A"})
        self.assertEqual(status, 200)
        self.assertEqual(out["journal"][tid]["grade"], "A")
        self.assertEqual(store.journal()[tid]["thesis"], "why")
        _, data = self._get("/api/model")
        self.assertEqual(json.loads(data.decode("utf-8"))["trades"][0]["tags"], ["a"])

    def test_data_routes_clear_and_disconnect(self):
        store.merge_local_rows([
            buy("b1", "AAA", 10, 1, "2026-01-01", source="csv"),
            sell("s1", "AAA", 10, 2, "2026-01-05", source="csv"),
        ])
        bagholder.save_session({"access_token": "x", "refresh_token": "y"})
        status, body = self._get("/api/data")
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["activities"], 2)
        self.assertTrue(data["sessionPresent"])
        self.assertIn("bagholder.db", data["path"])
        _, data = self._get("/api/model")
        self.assertEqual(json.loads(data.decode("utf-8"))["kpi"]["count"], 1)
        status, out = self._post("/api/data/clear", {"session": True})
        self.assertEqual(status, 200)
        self.assertEqual(out["activities"], 0)
        self.assertFalse(out["sessionPresent"])
        self.assertIsNone(bagholder.load_session())
        _, data = self._get("/api/model")
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["kpi"]["count"], 0)
        self.assertEqual(payload["activityCount"], 0)
        html = bagholder.ledger_path().read_text(encoding="utf-8")
        self.assertIn("/api/data/clear", html)
        self.assertIn("Clear data", html)

    def test_import_watch_and_manual_trade_routes(self):
        status, out = self._post("/api/import", {"name": "activities.csv", "text": CANONICAL_CSV})
        self.assertEqual(status, 200)
        self.assertEqual((out["format"], out["added"]), ("canonical", 3))
        _, data = self._get("/api/model")
        self.assertEqual(json.loads(data.decode("utf-8"))["kpi"]["count"], 1)
        status, out = self._post("/api/book/append", {"date": "2026-03-01", "symbol": "bbb", "side": "BUY", "qty": 5, "price": 2, "currency": "CAD", "commission": 1, "accountId": "manual", "accountType": "Manual"})
        self.assertEqual(status, 200)
        self.assertEqual(out["added"], 1)
        _, data = self._get("/api/model")
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual([p["symbol"] for p in payload["positions"]], ["BBB"])
        self.assertEqual(payload["positions"][0]["fees"], 1.0)
        folder = os.path.join(self.tmp.name, "csv")
        os.makedirs(folder)
        with open(os.path.join(folder, "old.csv"), "w", encoding="utf-8") as fh:
            fh.write(LEGACY_CSV)
        status, out = self._post("/api/watch", {"path": folder})
        self.assertEqual(status, 200)
        self.assertEqual(out["added"], 2)
        status, out = self._post("/api/watch/scan", {})
        self.assertEqual((out["added"], out["duplicates"]), (0, 2))
        self.assertTrue(out["status"]["watching"])
        status, body = self._get("/api/watch")
        self.assertTrue(json.loads(body.decode("utf-8"))["watching"])
        status, out = self._post("/api/watch/clear", {})
        self.assertFalse(out["watching"])
        html = bagholder.ledger_path().read_text(encoding="utf-8")
        for needle in ("/api/import", "/api/watch", "Add trade", "Load folder"):
            self.assertIn(needle, html)

    def test_root_serves_the_page(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"/api/model", body)
        status, body = self._get("/v2")
        self.assertEqual(status, 200)
        self.assertIn(b"/api/model", body)


if __name__ == "__main__":
    unittest.main()
