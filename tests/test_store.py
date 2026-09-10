#!/usr/bin/env python3
"""SQLite store and Wealthsimple sync bounds. Synthetic rows only."""

from __future__ import annotations

import gzip
import io
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from unittest import mock

import bagholder
import market
import store

# Fake Wealthsimple production clientId for scrape tests. Not a real id.
FAKE_CLIENT_ID = "ab" * 32


class _FakeHTTPResp:
    def __init__(self, body, headers=None, status=200):
        if isinstance(body, (bytes, bytearray)):
            self._body = bytes(body)
        else:
            self._body = str(body).encode("utf-8")
        self.headers = headers or {}
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ws_item(**overrides):
    item = {
        "occurredAt": "2024-06-15T13:45:22.123Z",
        "canonicalId": "ws-cid-aaa-001",
        "status": "POSTED",
        "type": "DIY_BUY",
        "subType": "BUY",
        "assetSymbol": "AAA",
        "assetQuantity": 10,
        "amount": 100,
        "accountId": "acct-1",
        "currency": "CAD",
    }
    item.update(overrides)
    return item


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        os.environ["BAGHOLDER_HOME"] = self.home
        store.set_home(self.home)
        bagholder.set_home(self.home)
        store.ensure()
        with bagholder._lock:
            bagholder._state["connected"] = False
            bagholder._state["error"] = ""
            bagholder._state["syncing"] = False
            bagholder._state["capturing"] = False
            bagholder._state["email"] = ""

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("BAGHOLDER_HOME", None)

    def test_status_carries_the_data_version_so_the_page_can_reload(self):
        v0 = bagholder.status_payload()["dataVersion"]
        self.assertTrue(v0)
        store.upsert_quote("RDDY", {"price": 4.75, "fetchedAt": "2026-09-07T15:00:00Z"})
        v1 = bagholder.status_payload()["dataVersion"]
        self.assertNotEqual(v0, v1)
        store.upsert_distributions("RDDY", [{"exDate": "2026-09-30", "payDate": "2026-10-05", "amount": 0.2, "currency": "CAD"}])
        self.assertNotEqual(v1, bagholder.status_payload()["dataVersion"])

    def test_status_version_changes_with_the_date_so_the_page_refetches_at_midnight(self):
        with mock.patch.object(bagholder.model, "today_local", return_value="2026-12-31"):
            a = bagholder.status_payload()["dataVersion"]
        with mock.patch.object(bagholder.model, "today_local", return_value="2027-01-01"):
            b = bagholder.status_payload()["dataVersion"]
        self.assertNotEqual(a, b)

    def test_page_and_server_agree_on_the_protocol_stamp(self):
        page = (bagholder.ledger_path()).read_text(encoding="utf-8")
        m = re.search(r'const PROTOCOL = "([^"]+)"', page)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), bagholder.PROTOCOL)
        self.assertEqual(bagholder.status_payload()["protocol"], bagholder.PROTOCOL)

    def test_port_can_be_chosen_for_a_second_instance(self):
        with mock.patch.dict(os.environ, {"BAGHOLDER_PORT": "8799"}):
            self.assertEqual(bagholder.port_choices(), (8799,))
        with mock.patch.dict(os.environ, {"BAGHOLDER_PORT": "80"}):
            self.assertEqual(bagholder.port_choices(), bagholder.PORTS, "a privileged or nonsense port is ignored")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BAGHOLDER_PORT", None)
            self.assertEqual(bagholder.port_choices(), bagholder.PORTS)

    def test_update_check_flags_only_a_newer_release(self):
        from datetime import datetime, timedelta, timezone
        self.assertIsNotNone(bagholder.parse_version(bagholder.APP_VERSION), "APP_VERSION must be MAJOR.MINOR.PATCH")
        self.assertEqual(bagholder.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(bagholder.parse_version("1.10.0"), (1, 10, 0))
        self.assertGreater(bagholder.parse_version("v1.10.0"), bagholder.parse_version("v1.9.9"))
        self.assertIsNone(bagholder.parse_version("latest"))
        now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
        mine = bagholder.parse_version(bagholder.APP_VERSION)
        newer = "v%d.%d.%d" % (mine[0], mine[1], mine[2] + 1)
        older = "v%d.%d.%d" % (0, 9, 0)
        with mock.patch.object(bagholder, "_http_json", return_value={"tag_name": "v" + bagholder.APP_VERSION, "html_url": "https://github.com/x/y/releases/tag/v1"}):
            rec = bagholder.check_for_update(now)
        self.assertEqual((rec["ok"], rec["updateAvailable"]), (True, False), "same release: no flag")
        with mock.patch.object(bagholder, "_http_json", return_value={"tag_name": older, "html_url": "u"}):
            self.assertFalse(bagholder.check_for_update(now)["updateAvailable"], "an older release never flags")
        with mock.patch.object(bagholder, "_http_json", return_value={"tag_name": newer, "html_url": "https://github.com/ProfessorBagholder/Bagholder/releases/tag/" + newer}) as g:
            rec = bagholder.check_for_update_if_due(now + timedelta(minutes=30))
            self.assertEqual(g.call_count, 0, "checked half an hour ago: GitHub is not asked again")
            rec = bagholder.check_for_update_if_due(now + timedelta(hours=2))
        self.assertEqual((rec["updateAvailable"], rec["latest"]), (True, newer))
        st = bagholder.status_payload()
        self.assertEqual((st["version"], st["latestVersion"], st["updateAvailable"], st["updateUrl"]), (bagholder.APP_VERSION, newer, True, rec["url"]))
        with mock.patch.object(bagholder, "_http_json", side_effect=OSError("offline")):
            rec = bagholder.check_for_update(now + timedelta(hours=50))
        self.assertEqual((rec["ok"], rec["updateAvailable"]), (False, False), "offline: silent, no flag")
        with mock.patch.object(bagholder, "_http_json", return_value={"message": "Not Found"}):
            self.assertFalse(bagholder.check_for_update(now)["updateAvailable"], "no release published yet: nothing to flag")

    def test_history_endpoint_validates_and_serves_bars(self):
        self.assertFalse(bagholder.history_payload("symbol=RDDY")["ok"])
        bars = [{"date": "2026-09-04", "open": 4.8, "high": 4.8, "low": 4.68, "close": 4.75, "volume": 1}]
        with mock.patch.object(market, "fetch_history", return_value=(bars, "tmx")):
            out = bagholder.history_payload("symbol=RDDY&exchange=TSX&currency=CAD&kind=Shares&from=2026-08-25&to=2026-09-05")
        self.assertEqual((out["ok"], out["source"], out["tf"], out["available"], [b["close"] for b in out["bars"]]), (True, "tmx", "1d", ["1h", "4h", "1d", "1w", "1M"], [4.75]))
        with mock.patch.object(market, "fetch_history", return_value=(bars, "tmx")):
            weekly = bagholder.history_payload("symbol=RDDY&exchange=TSX&currency=CAD&kind=Shares&from=2026-08-25&to=2026-09-05&tf=1w")
        self.assertEqual([b["date"] for b in weekly["bars"]], ["2026-08-31"])
        self.assertFalse(bagholder.history_payload("symbol=RDDY&exchange=TSX&currency=CAD&kind=Shares&from=2026-08-25&to=2026-09-05&tf=2h")["ok"])
        with mock.patch.object(market, "fetch_history", return_value=(bars, "tmx")):
            out = bagholder.history_payload("symbol=QNC%2020NOV26%203.00%20CALL&exchange=NYSE&currency=USD&kind=Options&from=2026-06-01&to=2026-09-05")
        self.assertEqual((out["ok"], out["source"], out["chartSymbol"], [b["close"] for b in out["bars"]]), (True, "tmx", "QNC", [4.75]), "an option is charted on its underlying")
        # intraday not stored yet: the request returns at once, pending, and starts the fetch
        with mock.patch.object(market, "ensure_intraday_in_background") as bg:
            out = bagholder.history_payload("symbol=RDDY&exchange=TSX&currency=CAD&kind=Shares&from=2026-08-25&to=2026-09-05&tf=1h")
        self.assertEqual((out["pending"], out["bars"]), (True, []))
        self.assertEqual(bg.call_count, 1)
        # a request for the contract itself still charts the underlying: no source keeps option history
        with mock.patch.object(market, "fetch_history", return_value=(bars, "tmx")):
            out = bagholder.history_payload("symbol=QNC%2020NOV26%203.00%20CALL&exchange=NYSE&currency=USD&kind=Options&from=2026-06-01&to=2026-09-05&tf=1d&basis=contract")
        self.assertEqual((out["chartSymbol"], [b["close"] for b in out["bars"]]), ("QNC", [4.75]))
        self.assertNotIn("basis", out)

    def test_options_sell_maps_as_sell_to_open(self):
        item = _ws_item(
            type="OPTIONS_SELL",
            subType="LIMIT_ORDER",
            assetSymbol="QNC",
            contractType="CALL",
            strikePrice=3,
            expiryDate="2027-02-19",
            assetQuantity=35,
            amount=1050,
            amountSign="positive",
        )
        row = bagholder.map_activity(item)
        self.assertEqual(row["activitySubType"], "SELLTOOPEN")
        self.assertEqual(row["category"], "trade")
        self.assertEqual(row["quantity"], -35)
        self.assertEqual(row["netCashAmount"], 1050)
        self.assertEqual(row["symbol"], "QNC 19FEB27 3.00 CALL")

    def test_cash_dividend_without_status_is_kept(self):
        item = {
            "type": "DIVIDEND",
            "subType": "CASH_DIVIDEND",
            "status": None,
            "amount": "3660.00",
            "amountSign": "positive",
            "assetQuantity": "18300.0",
            "assetSymbol": "RDDY",
            "currency": "CAD",
            "occurredAt": "2026-06-05T14:53:21.630000+00:00",
            "accountId": "non-registered-x",
            "canonicalId": "div-1",
        }
        self.assertFalse(bagholder.skip_activity(item))
        rec = bagholder.map_activity(item)
        self.assertEqual(rec["category"], "dividend")
        self.assertEqual(rec["symbol"], "RDDY")
        self.assertAlmostEqual(rec["netCashAmount"], 3660.0)
        self.assertAlmostEqual(rec["unitPrice"], 0.2)
        self.assertEqual(rec["transactionDate"], "2026-06-05")
        item["type"] = "DIY_BUY"
        self.assertTrue(bagholder.skip_activity(item))

    def test_margin_interest_charge_without_status_is_kept(self):
        item = {
            "type": "INTEREST_CHARGE",
            "subType": "MARGIN_INTEREST",
            "status": None,
            "amount": "412.10",
            "amountSign": "negative",
            "currency": "CAD",
            "occurredAt": "2026-06-01T04:00:00.000000+00:00",
            "accountId": "non-registered-x",
            "canonicalId": "int-1",
        }
        self.assertFalse(bagholder.skip_activity(item))
        rec = bagholder.map_activity(item)
        self.assertEqual(rec["activityType"], "INTEREST_CHARGE")
        self.assertAlmostEqual(rec["netCashAmount"], -412.10)
        self.assertEqual(rec["transactionDate"], "2026-06-01")

    def test_options_buy_maps_as_buy_to_open(self):
        item = _ws_item(
            type="OPTIONS_BUY",
            subType="LIMIT_ORDER",
            assetSymbol="QNC",
            contractType="CALL",
            strikePrice=3,
            expiryDate="2027-02-19",
            assetQuantity=5,
            amount=150,
            amountSign="negative",
        )
        row = bagholder.map_activity(item)
        self.assertEqual(row["activitySubType"], "BUYTOOPEN")
        self.assertEqual(row["category"], "trade")
        self.assertEqual(row["quantity"], 5)
        self.assertEqual(row["netCashAmount"], -150)

    def test_map_activity_options_multileg_debit_is_buy_to_close(self):
        row = bagholder.map_activity(
            _ws_item(
                type="OPTIONS_MULTILEG",
                subType="FILLED",
                status="FILLED",
                assetSymbol="LUNR",
                contractType="CALL",
                strikePrice=12,
                expiryDate="2027-01-15",
                assetQuantity=None,
                amount=128,
                amountSign="negative",
                currency="USD",
            )
        )
        self.assertEqual(row["category"], "trade")
        self.assertEqual(row["activityType"], "OPTIONS_BUY")
        self.assertEqual(row["activitySubType"], "BUYTOCLOSE")
        self.assertEqual(row["quantity"], 0)
        self.assertEqual(row["unitPrice"], 0)
        self.assertEqual(row["netCashAmount"], -128)
        self.assertEqual(row["symbol"], "LUNR 15JAN27 12.00 CALL")

    def test_map_activity_options_multileg_credit_is_sell_to_open(self):
        row = bagholder.map_activity(
            _ws_item(
                type="OPTIONS_MULTILEG",
                subType="FILLED",
                status="FILLED",
                assetSymbol="BBAI",
                contractType="CALL",
                strikePrice=10,
                expiryDate="2028-01-21",
                assetQuantity=None,
                amount=56,
                amountSign="positive",
                currency="USD",
            )
        )
        self.assertEqual(row["category"], "trade")
        self.assertEqual(row["activityType"], "OPTIONS_SELL")
        self.assertEqual(row["activitySubType"], "SELLTOOPEN")
        self.assertEqual(row["quantity"], 0)
        self.assertEqual(row["unitPrice"], 0)
        self.assertEqual(row["netCashAmount"], 56)
        self.assertEqual(row["symbol"], "BBAI 21JAN28 10.00 CALL")

    def test_map_activity_options_short_expiry_covers_short(self):
        row = bagholder.map_activity(
            _ws_item(
                type="OPTIONS_SHORT_EXPIRY",
                subType="EXPIRED",
                status="POSTED",
                assetSymbol="LUNR",
                contractType="CALL",
                strikePrice=12,
                expiryDate="2027-01-15",
                assetQuantity=16,
                amount=0,
                amountSign="negative",
                currency="USD",
            )
        )
        self.assertEqual(row["category"], "option_event")
        self.assertEqual(row["activityType"], "EXPIR")
        self.assertEqual(row["activitySubType"], "BUY")
        self.assertEqual(row["quantity"], 16)
        self.assertEqual(row["unitPrice"], 0)
        self.assertEqual(row["netCashAmount"], 0)

    def test_map_activity_options_expiry_sells_long_assign_covers_short(self):
        expiry = bagholder.map_activity(
            _ws_item(
                type="OPTIONS_EXPIRY",
                subType="EXPIRED",
                assetSymbol="LUNR",
                contractType="CALL",
                strikePrice=12,
                expiryDate="2025-08-22",
                assetQuantity=4,
                amount=0,
            )
        )
        self.assertEqual(expiry["category"], "option_event")
        self.assertEqual(expiry["activityType"], "EXPIR")
        self.assertEqual(expiry["activitySubType"], "SELL")
        self.assertEqual(expiry["quantity"], -4)
        self.assertEqual(expiry["unitPrice"], 0)
        assign = bagholder.map_activity(
            _ws_item(
                type="OPTIONS_ASSIGN",
                subType="ASSIGNED",
                assetSymbol="ASTS",
                contractType="CALL",
                strikePrice=31,
                expiryDate="2025-03-07",
                assetQuantity=1,
                amount=3100,
                amountSign="negative",
                currency="USD",
            )
        )
        self.assertEqual(assign["category"], "option_event")
        self.assertEqual(assign["activityType"], "ASSIGN")
        self.assertEqual(assign["activitySubType"], "BUYTOCLOSE")
        self.assertEqual(assign["quantity"], 1)
        self.assertEqual(assign["unitPrice"], 0)
        self.assertEqual(assign["symbol"], "ASTS 07MAR25 31.00 CALL")

    def test_map_activity_option_unit_price_is_per_share(self):
        cheap = bagholder.map_activity(
            _ws_item(
                type="OPTIONS_SELL",
                subType="LIMIT_ORDER",
                assetSymbol="DRAM",
                contractType="CALL",
                strikePrice=1,
                expiryDate="2027-02-19",
                assetQuantity=10,
                amount=112.5,
                amountSign="positive",
            )
        )
        self.assertAlmostEqual(cheap["unitPrice"], 0.1125)
        pricey = bagholder.map_activity(
            _ws_item(
                type="OPTIONS_SELL",
                subType="LIMIT_ORDER",
                assetSymbol="SOXL",
                contractType="CALL",
                strikePrice=20,
                expiryDate="2027-02-19",
                assetQuantity=10,
                amount=13300,
                amountSign="positive",
            )
        )
        self.assertAlmostEqual(pricey["unitPrice"], 13.3)
        share_item = _ws_item(amount=100, assetQuantity=10)
        share = bagholder.map_activity(share_item)
        self.assertFalse(bagholder._is_option(share_item))
        self.assertAlmostEqual(share["unitPrice"], 10.0)

    def test_scale_stored_option_unit_price_missing_multiplier(self):
        store.apply_wealthsimple_mapped(
            [
                {
                    "canonicalId": "opt-cheap-1",
                    "occurredAt": "2026-08-31T14:16:58Z",
                    "transactionDate": "2026-08-31",
                    "accountId": "acct-1",
                    "accountType": "Trading",
                    "activityType": "OPTIONS_SELL",
                    "activitySubType": "SELLTOOPEN",
                    "symbol": "DRAM 19FEB27 1.00 CALL",
                    "currency": "USD",
                    "quantity": -10,
                    "unitPrice": 11.25,
                    "netCashAmount": 112.5,
                    "category": "trade",
                    "source": "wealthsimple",
                    "rawType": "OPTIONS_SELL",
                },
                {
                    "canonicalId": "opt-ok-1",
                    "occurredAt": "2026-08-31T14:17:58Z",
                    "transactionDate": "2026-08-31",
                    "accountId": "acct-1",
                    "accountType": "Trading",
                    "activityType": "OPTIONS_SELL",
                    "activitySubType": "SELLTOOPEN",
                    "symbol": "SOXL 19FEB27 20.00 CALL",
                    "currency": "USD",
                    "quantity": -10,
                    "unitPrice": 13.3,
                    "netCashAmount": 13300,
                    "category": "trade",
                    "source": "wealthsimple",
                    "rawType": "OPTIONS_SELL",
                },
                {
                    "canonicalId": "share-ok-1",
                    "occurredAt": "2026-08-31T14:18:58Z",
                    "transactionDate": "2026-08-31",
                    "accountId": "acct-1",
                    "accountType": "Trading",
                    "activityType": "Trade",
                    "activitySubType": "BUY",
                    "symbol": "AAA",
                    "currency": "CAD",
                    "quantity": 10,
                    "unitPrice": 10.0,
                    "netCashAmount": -100,
                    "category": "trade",
                    "source": "wealthsimple",
                    "rawType": "DIY_BUY",
                },
            ]
        )
        # setUp already ran ensure() on an empty DB and stamped the one-shot key.
        conn = sqlite3.connect(str(store.db_path()))
        try:
            conn.execute(
                "DELETE FROM meta WHERE key = ?",
                (store.OPTION_UNIT_PRICE_SCALE_META,),
            )
            conn.commit()
        finally:
            conn.close()
        store.ensure()
        by_id = {a["canonicalId"]: a for a in store.snapshot()["activities"]}
        self.assertAlmostEqual(by_id["opt-cheap-1"]["unitPrice"], 0.1125)
        self.assertAlmostEqual(by_id["opt-ok-1"]["unitPrice"], 13.3)
        self.assertAlmostEqual(by_id["share-ok-1"]["unitPrice"], 10.0)
        self.assertEqual(store.get_meta(store.OPTION_UNIT_PRICE_SCALE_META), "1")
        with mock.patch.object(store, "_scale_option_unit_prices") as scale:
            store.ensure()
            scale.assert_not_called()
        again = {a["canonicalId"]: a for a in store.snapshot()["activities"]}
        self.assertAlmostEqual(again["opt-cheap-1"]["unitPrice"], 0.1125)
        self.assertAlmostEqual(again["opt-ok-1"]["unitPrice"], 13.3)
        self.assertAlmostEqual(again["share-ok-1"]["unitPrice"], 10.0)

    def test_relabel_stored_options_sell(self):
        store.apply_wealthsimple_mapped(
            [
                {
                    "canonicalId": "opt-sell-1",
                    "occurredAt": "2026-08-31T14:16:58Z",
                    "transactionDate": "2026-08-31",
                    "accountId": "acct-1",
                    "accountType": "Trading",
                    "activityType": "OPTIONS_SELL",
                    "activitySubType": "LIMIT_ORDER",
                    "symbol": "QNC 19FEB27 3.00 CALL",
                    "currency": "USD",
                    "quantity": 35,
                    "unitPrice": 0.3,
                    "netCashAmount": 1050,
                    "category": "other",
                    "source": "wealthsimple",
                    "rawType": "OPTIONS_SELL",
                }
            ]
        )
        store.ensure()
        snap = store.snapshot()
        row = [a for a in snap["activities"] if a.get("canonicalId") == "opt-sell-1"][0]
        self.assertEqual(row["activitySubType"], "SELLTOOPEN")
        self.assertEqual(row["category"], "trade")
        self.assertEqual(row["quantity"], -35)
        self.assertEqual(row["netCashAmount"], 1050)

    def test_relabel_stored_options_multileg_and_expiry(self):
        store.apply_wealthsimple_mapped(
            [
                {
                    "canonicalId": "opt-ml-1",
                    "occurredAt": "2026-08-31T14:16:58Z",
                    "transactionDate": "2026-08-31",
                    "accountId": "acct-1",
                    "accountType": "Trading",
                    "activityType": "OPTIONS_MULTILEG",
                    "activitySubType": "FILLED",
                    "symbol": "LUNR 15JAN27 12.00 CALL",
                    "currency": "USD",
                    "quantity": 0,
                    "unitPrice": 0,
                    "netCashAmount": -128,
                    "category": "other",
                    "source": "wealthsimple",
                    "rawType": "OPTIONS_MULTILEG",
                },
                {
                    "canonicalId": "opt-ml-credit",
                    "occurredAt": "2026-08-31T14:16:59Z",
                    "transactionDate": "2026-08-31",
                    "accountId": "acct-1",
                    "accountType": "Trading",
                    "activityType": "OPTIONS_SELL",
                    "activitySubType": "SELLTOCLOSE",
                    "symbol": "BBAI 21JAN28 10.00 CALL",
                    "currency": "USD",
                    "quantity": 0,
                    "unitPrice": 0,
                    "netCashAmount": 56,
                    "category": "trade",
                    "source": "wealthsimple",
                    "rawType": "OPTIONS_MULTILEG",
                },
                {
                    "canonicalId": "opt-exp-1",
                    "occurredAt": "2026-08-31T14:17:58Z",
                    "transactionDate": "2026-08-31",
                    "accountId": "acct-1",
                    "accountType": "Trading",
                    "activityType": "OPTIONS_SHORT_EXPIRY",
                    "activitySubType": "EXPIRED",
                    "symbol": "LUNR 15JAN27 12.00 CALL",
                    "currency": "USD",
                    "quantity": 5,
                    "unitPrice": 0,
                    "netCashAmount": 0,
                    "category": "other",
                    "source": "wealthsimple",
                    "rawType": "OPTIONS_SHORT_EXPIRY",
                },
                {
                    "canonicalId": "opt-long-exp",
                    "occurredAt": "2026-08-31T14:17:59Z",
                    "transactionDate": "2026-08-31",
                    "accountId": "acct-1",
                    "accountType": "Trading",
                    "activityType": "EXPIR",
                    "activitySubType": "BUY",
                    "symbol": "LUNR 22AUG25 12.00 CALL",
                    "currency": "USD",
                    "quantity": 4,
                    "unitPrice": 0,
                    "netCashAmount": 0,
                    "category": "option_event",
                    "source": "wealthsimple",
                    "rawType": "OPTIONS_EXPIRY",
                },
                {
                    "canonicalId": "opt-asg-1",
                    "occurredAt": "2026-08-31T14:18:58Z",
                    "transactionDate": "2026-08-31",
                    "accountId": "acct-1",
                    "accountType": "Trading",
                    "activityType": "OPTIONS_ASSIGN",
                    "activitySubType": "ASSIGNED",
                    "symbol": "LUNR 15JAN27 12.00 CALL",
                    "currency": "USD",
                    "quantity": -2,
                    "unitPrice": 0,
                    "netCashAmount": 0,
                    "category": "other",
                    "source": "wealthsimple",
                    "rawType": "OPTIONS_ASSIGN",
                },
                {
                    "canonicalId": "opt-asg-strike",
                    "occurredAt": "2025-03-07T21:00:00Z",
                    "transactionDate": "2025-03-07",
                    "accountId": "acct-1",
                    "accountType": "Trading",
                    "activityType": "ASSIGN",
                    "activitySubType": "BUYTOCLOSE",
                    "symbol": "ASTS 07MAR25 31.00 CALL",
                    "currency": "USD",
                    "quantity": 1,
                    "unitPrice": 31,
                    "netCashAmount": -3100,
                    "category": "option_event",
                    "source": "wealthsimple",
                    "rawType": "OPTIONS_ASSIGN",
                },
            ]
        )
        store.ensure()
        by_id = {a["canonicalId"]: a for a in store.snapshot()["activities"]}
        ml = by_id["opt-ml-1"]
        self.assertEqual(ml["category"], "trade")
        self.assertEqual(ml["activityType"], "OPTIONS_BUY")
        self.assertEqual(ml["activitySubType"], "BUYTOCLOSE")
        self.assertEqual(ml["quantity"], 0)
        self.assertEqual(ml["netCashAmount"], -128)
        credit = by_id["opt-ml-credit"]
        self.assertEqual(credit["category"], "trade")
        self.assertEqual(credit["activityType"], "OPTIONS_SELL")
        self.assertEqual(credit["activitySubType"], "SELLTOOPEN")
        self.assertEqual(credit["netCashAmount"], 56)
        exp = by_id["opt-exp-1"]
        self.assertEqual(exp["category"], "option_event")
        self.assertEqual(exp["activityType"], "EXPIR")
        self.assertEqual(exp["activitySubType"], "BUY")
        self.assertEqual(exp["quantity"], 5)
        long_exp = by_id["opt-long-exp"]
        self.assertEqual(long_exp["category"], "option_event")
        self.assertEqual(long_exp["activityType"], "EXPIR")
        self.assertEqual(long_exp["activitySubType"], "SELL")
        self.assertEqual(long_exp["quantity"], -4)
        asg = by_id["opt-asg-1"]
        self.assertEqual(asg["category"], "option_event")
        self.assertEqual(asg["activityType"], "ASSIGN")
        self.assertEqual(asg["activitySubType"], "BUYTOCLOSE")
        self.assertEqual(asg["quantity"], 2)
        strike = by_id["opt-asg-strike"]
        self.assertEqual(strike["unitPrice"], 0)
        self.assertEqual(strike["activitySubType"], "BUYTOCLOSE")

    def test_insert_if_new_by_canonical_id(self):
        row = bagholder.map_activity(_ws_item())
        first = store.apply_wealthsimple_mapped([row])
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(store.activity_count(), 1)
        again = store.apply_wealthsimple_mapped([row])
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(again["skipped"], 1)
        self.assertEqual(store.activity_count(), 1)

    def test_a_row_wealthsimple_revises_replaces_the_stored_copy(self):
        original = bagholder.map_activity(_ws_item())
        store.apply_wealthsimple_mapped([original])
        stored_id = store.snapshot()["activities"][0]["id"]
        changed = bagholder.map_activity(_ws_item(amount=999, assetQuantity=10))
        changed["description"] = "revised by Wealthsimple"
        result = store.apply_wealthsimple_mapped([changed])
        self.assertEqual((result["inserted"], result["revised"], result["skipped"]), (0, 1, 0))
        stored = store.snapshot()["activities"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["canonicalId"], "ws-cid-aaa-001")
        self.assertEqual(stored[0]["id"], stored_id, "the stored id, and so the journal key, survives the revision")
        self.assertEqual(stored[0]["description"], "revised by Wealthsimple")
        self.assertAlmostEqual(stored[0]["netCashAmount"], changed["netCashAmount"])
        same_again = store.apply_wealthsimple_mapped([changed])
        self.assertEqual((same_again["revised"], same_again["skipped"]), (0, 1), "an unchanged row is not rewritten")

    def test_placeholder_dividend_becomes_the_paid_dividend(self):
        """2026-09-08: EASY's dividend arrived on the record date as a zero-cash placeholder
        dated August 31, then Wealthsimple revised the same row into the paid dividend on the 8th."""
        placeholder = bagholder.map_activity(_ws_item(canonicalId="div_E002026619494", occurredAt="2026-08-31T04:00:00.000Z", amount=0, assetQuantity=4000))
        store.apply_wealthsimple_mapped([placeholder])
        paid = bagholder.map_activity(_ws_item(canonicalId="div_E002026619494", occurredAt="2026-09-08T14:02:11.000Z", amount=1020, assetQuantity=4000))
        result = store.apply_wealthsimple_mapped([paid])
        self.assertEqual(result["revised"], 1)
        rows = store.snapshot()["activities"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["transactionDate"], "2026-09-08")
        self.assertAlmostEqual(rows[0]["netCashAmount"], paid["netCashAmount"])
        self.assertAlmostEqual(abs(rows[0]["netCashAmount"]), 1020.0)

    def test_manual_has_no_canonical_id(self):
        result = bagholder.append_manual(
            {
                "date": "2024-07-01",
                "symbol": "ZZZ",
                "side": "BUY",
                "qty": 3,
                "price": 12.5,
                "currency": "CAD",
                "accountId": "manual",
            }
        )
        act = result["activity"]
        self.assertTrue(act["id"])
        self.assertFalse(store.looks_like_homemade_id(act["id"]))
        self.assertIn(act.get("canonicalId"), (None, "", False))
        stored = store.snapshot()["activities"][0]
        self.assertIsNone(stored.get("canonicalId"))
        self.assertEqual(stored["source"], "manual")

    def test_csv_has_no_canonical_id(self):
        saved = store.insert_local(
            {
                "transactionDate": "2024-07-02",
                "occurredAt": "2024-07-02",
                "accountId": "acct-1",
                "symbol": "ZZZ",
                "quantity": 4,
                "unitPrice": 8,
                "netCashAmount": -32,
                "activityType": "Trade",
                "activitySubType": "BUY",
                "source": "csv",
                "canonicalId": "do-not-keep-this",
            }
        )
        self.assertIsNone(saved.get("canonicalId"))
        self.assertEqual(saved["source"], "csv")
        self.assertFalse(store.looks_like_homemade_id(saved["id"]))

    def test_occurred_at_not_cut_to_date_for_wealthsimple_row(self):
        row = bagholder.map_activity(_ws_item())
        self.assertEqual(row["occurredAt"], "2024-06-15T13:45:22.123Z")
        self.assertEqual(row["transactionDate"], "2024-06-15")
        self.assertNotIn("id", row)
        store.apply_wealthsimple_mapped([row])
        stored = store.snapshot()["activities"][0]
        self.assertEqual(stored["occurredAt"], "2024-06-15T13:45:22.123Z")
        self.assertTrue("T" in stored["occurredAt"])

    def test_activity_pull_due_weekdays_at_2pm_mountain(self):
        mt = ZoneInfo("America/Edmonton")
        monday_1359 = datetime(2026, 8, 31, 13, 59, tzinfo=mt)
        monday_1400 = datetime(2026, 8, 31, 14, 0, tzinfo=mt)
        monday_1500 = datetime(2026, 8, 31, 15, 0, tzinfo=mt)
        saturday = datetime(2026, 8, 29, 15, 0, tzinfo=mt)
        self.assertFalse(store.activity_pull_due(now=monday_1359))
        self.assertTrue(store.activity_pull_due(now=monday_1400))
        self.assertTrue(store.activity_pull_due(now=monday_1500))
        self.assertFalse(store.activity_pull_due(now=saturday))
        store.mark_activity_pulled("2026-08-31T20:05:00Z")
        self.assertFalse(store.activity_pull_due(now=monday_1500))
        tuesday_1400 = datetime(2026, 9, 1, 14, 0, tzinfo=mt)
        self.assertTrue(store.activity_pull_due(now=tuesday_1400))

    def test_daily_path_does_not_page_whole_history_when_rows_exist(self):
        store.apply_wealthsimple_mapped([bagholder.map_activity(_ws_item())])
        bounds = bagholder.activity_sync_bounds()
        self.assertFalse(bounds["full_history"])
        self.assertTrue(bounds["start_date"])
        self.assertEqual(bounds["start_date"][:10], "2024-06-01", "fourteen days before the newest stored row")

        calls = []

        def fake_graphql(sess, operation, variables):
            calls.append(variables)
            return {
                "activityFeedItems": {
                    "edges": [
                        {
                            "node": _ws_item(
                                canonicalId="ws-cid-aaa-001",
                                occurredAt="2024-06-15T13:45:22.123Z",
                            )
                        }
                    ],
                    # the server bounds the walk by startDate; every page it returns is read
                    "pageInfo": {"hasNextPage": len(calls) < 2, "endCursor": "cursor-page-2"},
                }
            }

        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql):
            bagholder.fetch_activities_for_account(
                {"access_token": "x"},
                "acct-1",
                start_date=bounds["start_date"],
                known_canonical_ids=store.canonical_ids(),
            )

        self.assertEqual(len(calls), 2, "a page of known rows does not end the walk")
        cond = calls[0]["condition"]
        self.assertIn("startDate", cond)
        self.assertTrue(str(cond["startDate"]).startswith("2024-06-01"))

    def test_daily_window_reaches_back_past_rows_filed_under_a_later_day(self):
        """2026-09-08: a card purchase from the evening of the 8th was stored under the 9th (UTC),
        so a window starting at the newest stored day skipped the dividend paid on the 8th."""
        late = _ws_item()
        late["occurredAt"] = "2026-09-09T01:11:38.000Z"
        late["canonicalId"] = "ws-cid-card-0909"
        late["id"] = "ws-card-0909"
        store.apply_wealthsimple_mapped([bagholder.map_activity(late)])
        bounds = bagholder.activity_sync_bounds()
        self.assertEqual(bounds["start_date"], "2026-08-26")
        cond = bagholder.activity_fetch_condition("acct-1", start_date=bounds["start_date"])
        self.assertLess(cond["startDate"], "2026-09-08T04:00:00.000Z", "a dividend filed under the 8th is inside the window")

    def test_empty_table_full_history_omits_start_date(self):
        self.assertEqual(store.activity_count(), 0)
        bounds = bagholder.activity_sync_bounds()
        self.assertTrue(bounds["full_history"])
        self.assertIsNone(bounds["start_date"])
        cond = bagholder.activity_fetch_condition("acct-1", start_date=bounds["start_date"])
        self.assertNotIn("startDate", cond)

    def test_existing_rows_make_daily_sync_incremental(self):
        store.apply_wealthsimple_mapped([bagholder.map_activity(_ws_item())])
        store.insert_local(
            {
                "transactionDate": "2024-07-01",
                "occurredAt": "2024-07-01",
                "accountId": "manual",
                "symbol": "ZZZ",
                "quantity": 1,
                "unitPrice": 2,
                "netCashAmount": -2,
                "activityType": "Trade",
                "activitySubType": "BUY",
                "source": "manual",
            }
        )
        self.assertEqual(store.activity_count(), 2)
        ws = [a for a in store.snapshot()["activities"] if a["source"] == "wealthsimple"][0]
        self.assertEqual(ws["canonicalId"], "ws-cid-aaa-001")
        self.assertFalse(store.looks_like_homemade_id(ws["id"]))
        manual = [a for a in store.snapshot()["activities"] if a["source"] == "manual"][0]
        self.assertIsNone(manual.get("canonicalId"))
        bounds = bagholder.activity_sync_bounds()
        self.assertFalse(bounds["full_history"])
        self.assertTrue(bounds["start_date"])

    def test_token_refresh_needed_uses_expires_at(self):
        now = 1_700_000_000
        sess = {"expires_at": now + 60, "refresh_token": "r"}
        self.assertTrue(bagholder.token_refresh_needed(sess, now=now))
        sess_ok = {"expires_at": now + 3600, "refresh_token": "r"}
        self.assertFalse(bagholder.token_refresh_needed(sess_ok, now=now))
        sess_missing = {"refresh_token": "r"}
        self.assertTrue(bagholder.token_refresh_needed(sess_missing, now=now))

    def test_ensure_fresh_token_does_not_pull_activity(self):
        called = {"graphql": 0, "token": 0}

        def fake_refresh(sess):
            called["token"] += 1
            return True

        def fake_fail(sess):
            called["token"] += 1
            return False

        def fake_graphql(*args, **kwargs):
            called["graphql"] += 1
            return {}

        sess = {
            "refresh_token": "r",
            "expires_at": time_now_minus(),
        }
        bagholder.save_session(sess)
        with bagholder._lock:
            bagholder._state["connected"] = False
        with mock.patch.object(bagholder, "refresh_session", side_effect=fake_refresh):
            with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql):
                ok = bagholder.ensure_fresh_token(sess)
        self.assertTrue(ok)
        self.assertTrue(bagholder._state["connected"])
        self.assertEqual(bagholder._state["error"], "")
        self.assertEqual(called["token"], 1)
        self.assertEqual(called["graphql"], 0)

        called["token"] = 0
        with bagholder._lock:
            bagholder._state["connected"] = False
            bagholder._state["error"] = ""
        with mock.patch.object(bagholder, "refresh_session", side_effect=fake_fail):
            with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql):
                ok = bagholder.ensure_fresh_token(sess)
        self.assertFalse(ok)
        self.assertFalse(bagholder._state["connected"])
        self.assertTrue(bagholder._state["error"])
        self.assertTrue(bagholder.SESSION_PATH.exists())
        self.assertEqual(called["graphql"], 0)

    def test_link_single_manual_match_stamps_canonical_id(self):
        bagholder.append_manual(
            {
                "date": "2024-06-15",
                "symbol": "AAA",
                "side": "BUY",
                "qty": 10,
                "price": 10,
                "currency": "CAD",
                "accountId": "acct-1",
            }
        )
        self.assertEqual(store.activity_count(), 1)
        store.apply_wealthsimple_mapped([bagholder.map_activity(_ws_item())])
        rows = store.snapshot()["activities"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["canonicalId"], "ws-cid-aaa-001")
        self.assertEqual(rows[0]["source"], "manual")

    def test_map_activity_copies_security_id(self):
        row = bagholder.map_activity(_ws_item(securityId="sec-s-abc123"))
        self.assertEqual(row["securityId"], "sec-s-abc123")

    def test_margin_rows_round_trip_and_clear_with_the_synced_data(self):
        store.replace_margin([
            {"accountId": "acct-1", "buyingPower": 6817.33, "currency": "CAD"},
            {"accountId": "acct-2", "buyingPower": None, "currency": "CAD", "unavailable": "UnavailableSecurities (2 securities)"},
            {"accountId": "", "buyingPower": 1.0},
        ])
        rows = store.snapshot()["margin"]
        self.assertEqual([(r["accountId"], r["buyingPower"], r["unavailable"]) for r in rows],
                         [("acct-1", 6817.33, ""), ("acct-2", None, "UnavailableSecurities (2 securities)")])
        self.assertTrue(all(r["fetchedAt"] for r in rows))
        v1 = store.data_version()
        store.replace_margin([{"accountId": "acct-1", "buyingPower": 6900.0, "currency": "CAD"}])
        self.assertNotEqual(v1, store.data_version(), "a new reading changes the model fingerprint")
        store.clear_synced_data()
        self.assertEqual(store.snapshot()["margin"], [])

    def test_second_sync_stamps_security_id_and_takes_the_revision(self):
        row = bagholder.map_activity(_ws_item())
        store.apply_wealthsimple_mapped([row])
        later = dict(row)
        later["securityId"] = "sec-s-later"
        later["quantity"] = 999
        later["netCashAmount"] = 1
        again = store.apply_wealthsimple_mapped([later])
        self.assertEqual((again["inserted"], again["revised"], again["skipped"]), (0, 1, 0))
        got = store.snapshot()["activities"][0]
        self.assertEqual(got["securityId"], "sec-s-later")
        self.assertEqual(got["quantity"], 999)
        unchanged = dict(later)
        unchanged["securityId"] = "sec-s-other"
        again = store.apply_wealthsimple_mapped([unchanged])
        self.assertEqual((again["revised"], again["skipped"]), (0, 1))
        self.assertEqual(store.snapshot()["activities"][0]["securityId"], "sec-s-later", "a security id already stored is kept")
        self.assertEqual(got["netCashAmount"], 1)

    def test_snapshot_includes_securities(self):
        store.upsert_securities(
            [
                {
                    "id": "sec-s-ch",
                    "symbol": "CH",
                    "name": "Charbone Corporation",
                    "primaryExchange": "TSX Venture Exchange",
                    "primaryMic": "XTSV",
                    "currency": "CAD",
                }
            ]
        )
        secs = store.snapshot()["securities"]
        self.assertEqual(len(secs), 1)
        self.assertEqual(secs[0]["id"], "sec-s-ch")
        self.assertEqual(secs[0]["name"], "Charbone Corporation")
        self.assertEqual(secs[0]["primaryMic"], "XTSV")

    def test_fetch_securities_batches_ids(self):
        calls = []

        def fake_graphql(sess, operation, variables, query=None):
            calls.append((operation, list(variables.get("ids") or [])))
            rows = []
            for sid in variables["ids"]:
                if sid == "sec-s-missing":
                    rows.append(None)
                elif sid.startswith("sec-o-"):
                    rows.append({"id": sid, "currency": "USD", "stock": {"symbol": "LUNR", "name": ""},
                                 "optionDetails": {"underlyingSecurity": {"id": "sec-s-under", "currency": "USD"}}})
                else:
                    rows.append({"id": sid, "currency": "CAD", "stock": {"symbol": "NSAV", "name": "Ninepoint", "primaryExchange": "TSX", "primaryMic": "XTSE"}, "optionDetails": None})
            return {"securities": rows}

        ids = ["sec-s-%d" % i for i in range(60)] + ["sec-o-1", "sec-s-missing", "sec-s-1"]
        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql):
            recs = bagholder.fetch_securities({"access_token": "t"}, ids)
        self.assertEqual([c[0] for c in calls], ["FetchSecurities", "FetchSecurities"])
        self.assertEqual(len(calls[0][1]), 50)
        self.assertEqual(len(calls[1][1]), 12)
        self.assertEqual(len(recs), 61)
        opt = next(r for r in recs if r["id"] == "sec-o-1")
        self.assertEqual(opt["underlyingId"], "sec-s-under")
        self.assertEqual(recs[0]["primaryExchange"], "TSX")

    def test_fill_listings_uses_batches_and_follows_underlyings(self):
        store.merge_local_rows([
            {"transactionDate": "2026-01-02", "symbol": "LUNR 15JAN27 12.00 CALL", "quantity": 1, "unitPrice": 1,
             "netCashAmount": -100, "category": "trade", "activityType": "OPTIONS_BUY", "activitySubType": "BUYTOOPEN",
             "currency": "USD", "securityId": "sec-o-1", "source": "csv"},
        ])
        store.set_meta("security_id_backfill_done", "1")
        calls = []

        def fake_graphql(sess, operation, variables, query=None):
            calls.append(list(variables.get("ids") or []))
            rows = []
            for sid in variables["ids"]:
                if sid == "sec-o-1":
                    rows.append({"id": sid, "currency": "USD", "stock": {"symbol": "LUNR"},
                                 "optionDetails": {"underlyingSecurity": {"id": "sec-s-under", "currency": "USD"}}})
                else:
                    rows.append({"id": sid, "currency": "USD", "stock": {"symbol": "LUNR", "name": "Intuitive Machines", "primaryExchange": "NASDAQ"}})
            return {"securities": rows}

        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql):
            self.assertTrue(bagholder.fill_listings({"access_token": "t"}))
        self.assertEqual(calls, [["sec-o-1"], ["sec-s-under"]])
        by_id = {s["id"]: s for s in store.list_securities()}
        self.assertEqual(by_id["sec-o-1"]["underlyingId"], "sec-s-under")
        self.assertEqual(by_id["sec-s-under"]["name"], "Intuitive Machines")

    def test_fetch_security_reads_stock_fields(self):
        def fake_graphql(sess, operation, variables, query=None):
            self.assertEqual(operation, "FetchSecurity")
            self.assertEqual(variables["securityId"], "sec-s-ch")
            return {
                "security": {
                    "id": "sec-s-ch",
                    "currency": "CAD",
                    "stock": {
                        "name": "Charbone Corporation",
                        "primaryExchange": "TSX Venture Exchange",
                        "primaryMic": "XTSV",
                        "symbol": "CH",
                    },
                    "optionDetails": {},
                }
            }

        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql):
            rec = bagholder.fetch_security({"access_token": "t"}, "sec-s-ch")
        self.assertEqual(rec["name"], "Charbone Corporation")
        self.assertEqual(rec["symbol"], "CH")
        self.assertEqual(rec["primaryMic"], "XTSV")
        self.assertEqual(rec["currency"], "CAD")












def time_now_minus():
    return datetime.now(timezone.utc).timestamp() - 10


def _login_html(js_url="https://assets.wealthsimple.com/app-abc123.js"):
    return '<html><script src="%s"></script></html>' % js_url


def _app_js(client_id):
    return 'var cfg={production:{env:"prod",clientId:"%s"}};' % client_id


class HistorySourceMigrationTest(unittest.TestCase):
    def test_replaced_sources_are_refetched_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BAGHOLDER_HOME"] = tmp
            store.set_home(tmp)
            store.ensure()
            try:
                store.upsert_price_history("DOT", [{"date": "2026-02-02", "open": None, "high": None, "low": None, "close": 9.5, "volume": None}], "coingecko")
                store.mark_history_fetched("DOT", "2026-02-02", "2026-09-07T00:00:00Z")
                store.upsert_price_history("MAXQ", [{"date": "2026-06-09", "open": 0.4, "high": 0.4, "low": 0.4, "close": 0.4, "volume": 1}], "cboe_ca")
                store.mark_history_fetched("MAXQ", "2025-10-14", "2026-09-07T00:00:00Z")
                store.upsert_price_history("RDDY", [{"date": "2026-02-02", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}], "tmx")
                store.mark_history_fetched("RDDY", "2026-02-02", "2026-09-07T00:00:00Z")
                store.upsert_price_history("USDC", [{"date": "2026-02-25", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}], "coinbase")
                store.mark_history_fetched("USDC", "2026-01-10", "2026-09-07T00:00:00Z")   # claimed January, has late February
                store.upsert_price_bars("USDC", "1h", [{"time": 1772000000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0}], "coinbase")   # 2026-02-25
                store.mark_bars_fetched("USDC", "1h", 1768000000, "2026-09-07T00:00:00Z")   # claimed from 2026-01-10
                store.upsert_price_bars("RDDY", "1h", [{"time": 1768003200, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0}], "tmx")
                store.mark_bars_fetched("RDDY", "1h", 1768000000, "2026-09-07T00:00:00Z")
                conn = store._connect()
                try:
                    conn.execute("DELETE FROM meta WHERE key = 'history_sources_migrated'")
                    conn.commit()
                    store._init_schema(conn)
                finally:
                    conn.close()
                self.assertEqual(store.price_history("DOT"), [], "close-only bars are gone")
                self.assertIsNone(store.history_fetch("DOT"), "and their fetch stamp, so the chart refetches")
                self.assertEqual(len(store.price_history("MAXQ")), 1, "Cboe's real bars stay")
                self.assertIsNone(store.history_fetch("MAXQ"), "but the span is refetched from TMX, which reaches further back")
                self.assertEqual(len(store.price_history("RDDY")), 1, "TMX candles stay")
                self.assertIsNotNone(store.history_fetch("RDDY"))
                self.assertEqual(len(store.price_history("USDC")), 1, "real bars stay")
                self.assertIsNone(store.history_fetch("USDC"), "a stamp claiming days its bars do not reach is dropped")
                self.assertIsNone(store.bar_fetch("USDC", "1h"), "the same for intraday stamps")
                self.assertIsNotNone(store.bar_fetch("RDDY", "1h"), "an honest intraday stamp stays")
                # Runs once: rows added afterwards under an old source name are left alone.
                store.upsert_price_history("DOT", [{"date": "2026-02-03", "open": None, "high": None, "low": None, "close": 9.6, "volume": None}], "coingecko")
                conn = store._connect()
                try:
                    store._init_schema(conn)
                finally:
                    conn.close()
                self.assertEqual(len(store.price_history("DOT")), 1)
            finally:
                os.environ.pop("BAGHOLDER_HOME", None)


class LoginBrowserTest(unittest.TestCase):
    """The login window is opened once, brought forward on a second Connect,
    closed by Cancel, and never relaunched by the app."""

    class _Proc:
        def __init__(self):
            self.returncode = None
            self.terminated = False
        def poll(self):
            return self.returncode
        def wait(self, timeout=None):
            if self.returncode is None:
                raise TimeoutError()
            return self.returncode
        def terminate(self):
            self.terminated = True
            self.returncode = -15
        @property
        def pid(self):
            return 4242

    def test_a_closed_window_is_noticed_even_when_chrome_lingers(self):
        import bagholder
        from unittest import mock
        proc = self._Proc()
        clock = [1000.0]
        def now():
            clock[0] += 5
            return clock[0]
        closed = []
        captured = []
        bagholder._state["capturing"] = True
        bagholder._state["error"] = ""
        bagholder._state["chrome_proc"] = proc
        bagholder._state["login_attempt"] = 7
        # Chrome is still running (only a service worker answers on the debug port), the window is gone.
        with mock.patch.object(bagholder, "_cdp_list", return_value=[{"type": "service_worker", "id": "SW", "webSocketDebuggerUrl": "ws://x"}]), \
             mock.patch.object(bagholder, "_try_capture_from_cdp", side_effect=lambda port: captured.append(1)), \
             mock.patch.object(bagholder, "_close_login_browser", side_effect=lambda only=None: closed.append(only)), \
             mock.patch.object(bagholder.threading, "Thread") as thread, \
             mock.patch.object(bagholder.time, "time", side_effect=now), mock.patch.object(bagholder.time, "sleep", lambda s: None):
            bagholder._poll_chrome_session(proc, 18765, attempt=7)
            self.assertEqual(thread.call_args.kwargs.get("target"), bagholder._capture_loop, "the capture runs beside the watcher, never delaying it")
        self.assertFalse(bagholder._state["capturing"], "waiting stopped")
        self.assertIn("closed before a session", bagholder._state["error"])
        self.assertEqual(closed, [proc], "and the app closes the instance it was watching; nothing is relaunched")
        self.assertEqual(captured, [], "no capture call is made against a window that is not there")
        # A watcher from an earlier attempt exits without touching the newer window.
        bagholder._state["capturing"] = True
        bagholder._state["error"] = ""
        bagholder._state["login_attempt"] = 8
        closed.clear()
        with mock.patch.object(bagholder, "_cdp_list", return_value=[]), mock.patch.object(bagholder, "_close_login_browser", side_effect=lambda only=None: closed.append(only)), \
             mock.patch.object(bagholder.threading, "Thread"), \
             mock.patch.object(bagholder.time, "time", side_effect=now), mock.patch.object(bagholder.time, "sleep", lambda s: None):
            bagholder._poll_chrome_session(proc, 18765, attempt=7)
        self.assertTrue(bagholder._state["capturing"], "the newer attempt is still waiting")
        self.assertEqual(bagholder._state["error"], "")
        self.assertEqual(closed, [], "and nothing was closed")

    def test_second_connect_reuses_the_window_and_cancel_closes_it(self):
        import bagholder
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BAGHOLDER_HOME"] = tmp
            bagholder.HOME = __import__("pathlib").Path(tmp)
            proc = self._Proc()
            calls = []
            fake_ws = type("WS", (), {"close": lambda self: None})()
            with mock.patch.object(bagholder, "find_chrome", return_value="/fake/chrome"), \
                 mock.patch.object(bagholder.subprocess, "Popen", return_value=proc) as popen, \
                 mock.patch.object(bagholder.threading, "Thread") as thread, \
                 mock.patch.object(bagholder, "_login_browser_ws", return_value="ws://127.0.0.1:18765/devtools/browser/x"), \
                 mock.patch.object(bagholder, "_ws_connect", return_value=fake_ws), \
                 mock.patch.object(bagholder, "_cdp_call", side_effect=lambda ws, m, p=None: calls.append(m) or {"id": 1, "result": {}}), \
                 mock.patch.object(bagholder, "_cdp_list", return_value=[{"type": "page", "id": "T1", "webSocketDebuggerUrl": "ws://x"}]):
                bagholder._state["chrome_proc"] = None
                bagholder._state["capturing"] = False
                bagholder._state["login_attempt"] = 0
                self.assertEqual(bagholder.start_login_browser(), {"ok": True})
                self.assertEqual(popen.call_count, 1)
                self.assertTrue(bagholder._state["capturing"])
                self.assertEqual(bagholder._state["login_attempt"], 1, "each launch is a new attempt; earlier watchers stand down")
                # Connect again while the window is up: no second Chrome, the window is brought forward.
                self.assertEqual(bagholder.start_login_browser(), {"ok": True, "reused": True})
                self.assertEqual(popen.call_count, 1, "never a second window")
                self.assertIn("Target.activateTarget", calls)
                self.assertNotIn("Target.createTarget", calls, "the app never opens a window inside a running Chrome")
                # Cancel: the wait ends and the app closes the window it opened.
                self.assertEqual(bagholder.cancel_login(), {"ok": True, "cancelled": True})
                self.assertFalse(bagholder._state["capturing"])
                self.assertIn("Browser.close", calls)
                self.assertTrue(proc.terminated, "a lingering process is ended")
                self.assertIsNone(bagholder._state["chrome_proc"])
                # A Connect after that opens a fresh window: the old one is not reused.
                proc2 = self._Proc()
                popen.return_value = proc2
                with mock.patch.object(bagholder, "_login_browser_ws", return_value=None):
                    self.assertEqual(bagholder.start_login_browser(), {"ok": True})
                self.assertEqual(popen.call_count, 2)
                # Connect while Chrome lingers with no window: that leftover is closed and one fresh window launched.
                bagholder._state["capturing"] = False
                with mock.patch.object(bagholder, "_cdp_list", return_value=[{"type": "service_worker", "id": "SW", "webSocketDebuggerUrl": "ws://x"}]):
                    proc3 = self._Proc()
                    popen.return_value = proc3
                    self.assertEqual(bagholder.start_login_browser(), {"ok": True})
                self.assertEqual(popen.call_count, 3)
                self.assertTrue(proc2.terminated, "the windowless leftover was closed first")
                self.assertNotIn("Target.createTarget", calls)
                bagholder.cancel_login()
            os.environ.pop("BAGHOLDER_HOME", None)


class InAppUpdateTest(unittest.TestCase):
    """The supervisor restarts the server on request, rolls back a bad update,
    and the update itself only swaps files that check out."""

    class _Child:
        def __init__(self, code, runs_for=0):
            self.code, self.runs_for, self.returncode = code, runs_for, None
        def wait(self, timeout=None):
            if timeout is not None and self.runs_for > timeout:
                self.runs_for -= timeout
                raise subprocess.TimeoutExpired("child", timeout)
            self.returncode = self.code
            return self.code
        def terminate(self):
            self.returncode = -15

    def test_supervisor_restarts_on_request_and_rolls_back_a_dead_update(self):
        import bagholder
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as app:
            bagholder.HOME = Path(home)
            bagholder.APP_DIR = Path(app)
            (Path(app) / "bagholder.py").write_text("new")
            # plain restart request, then a clean exit
            children = [self._Child(bagholder.RESTART_CODE), self._Child(0)]
            spawned = []
            def spawn():
                c = children.pop(0); spawned.append(c); return c
            self.assertEqual(bagholder.supervise(spawn=spawn, healthy_sec=5), 0)
            self.assertEqual(len(spawned), 2, "restart code means start again; a clean exit ends it")
            # an update is pending and the new server dies at once: previous files come back, the old version runs again
            (Path(home) / "previous").mkdir()
            (Path(home) / "previous" / "bagholder.py").write_text("old")
            (Path(home) / "update-pending").write_text("v9.9.9")
            children[:] = [self._Child(1), self._Child(0)]
            spawned.clear()
            self.assertEqual(bagholder.supervise(spawn=spawn, healthy_sec=5), 0)
            self.assertEqual(len(spawned), 2)
            self.assertEqual((Path(app) / "bagholder.py").read_text(), "old", "rolled back")
            self.assertFalse((Path(home) / "update-pending").exists())
            # an update is pending and the new server stays up: the marker and the backup go
            (Path(home) / "previous").mkdir()
            (Path(home) / "previous" / "bagholder.py").write_text("older")
            (Path(home) / "update-pending").write_text("v9.9.9")
            children[:] = [self._Child(0, runs_for=30)]
            spawned.clear()
            self.assertEqual(bagholder.supervise(spawn=spawn, healthy_sec=5), 0)
            self.assertEqual((Path(app) / "bagholder.py").read_text(), "old", "the running files were kept")
            self.assertFalse((Path(home) / "update-pending").exists())
            self.assertFalse((Path(home) / "previous").exists())

    def test_release_assets_take_the_web_archive_by_name_and_ignore_the_rest(self):
        import bagholder
        def rel(*names):
            return {"tag_name": "v2.0.0", "assets": [{"name": n, "browser_download_url": "https://x/" + n} for n in names]}
        # the platform-named archive, with the Android build beside it
        got = bagholder.release_assets(rel("bagholder-v2.0.0-android.apk", "bagholder-v2.0.0-web.zip", "bagholder-v2.0.0-web.zip.sha256"))
        self.assertEqual(got, {"zip": "https://x/bagholder-v2.0.0-web.zip", "sha": "https://x/bagholder-v2.0.0-web.zip.sha256"})
        # a release from before the name carried a platform
        got = bagholder.release_assets(rel("bagholder-v2.0.0.zip", "bagholder-v2.0.0.zip.sha256"))
        self.assertEqual(got, {"zip": "https://x/bagholder-v2.0.0.zip", "sha": "https://x/bagholder-v2.0.0.zip.sha256"})
        # the web archive wins when both names are present; nothing without its checksum
        got = bagholder.release_assets(rel("bagholder-v2.0.0.zip", "bagholder-v2.0.0.zip.sha256", "bagholder-v2.0.0-web.zip", "bagholder-v2.0.0-web.zip.sha256"))
        self.assertEqual(got["zip"], "https://x/bagholder-v2.0.0-web.zip")
        self.assertEqual(bagholder.release_assets(rel("bagholder-v2.0.0-web.zip", "bagholder-v2.0.0-android.apk")), {})

    def test_release_update_checks_the_archive_before_swapping_files(self):
        import bagholder, zipfile, hashlib
        from unittest import mock
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as app, tempfile.TemporaryDirectory() as rel:
            bagholder.HOME = Path(home)
            bagholder.APP_DIR = Path(app)
            (Path(app) / "bagholder.py").write_text("APP_VERSION = '1.0.0'\n")
            (Path(app) / "ledger.html").write_text("<old>")
            good = Path(rel) / "bagholder-v9.9.9.zip"
            with zipfile.ZipFile(good, "w") as z:
                z.writestr("bagholder.py", "APP_VERSION = '9.9.9'\n")
                z.writestr("ledger.html", "<new>")
                z.writestr("../evil.py", "x = 1")
            sha = Path(rel) / "good.sha256"
            sha.write_text(hashlib.sha256(good.read_bytes()).hexdigest() + "  bagholder-v9.9.9.zip\n")
            bad = Path(rel) / "bad.zip"
            with zipfile.ZipFile(bad, "w") as z:
                z.writestr("bagholder.py", "def broken(:\n")
            badsha = Path(rel) / "bad.sha256"
            badsha.write_text(hashlib.sha256(bad.read_bytes()).hexdigest() + "\n")
            files = {"zip": good, "sha": sha}
            def download(url, dest, max_bytes=0):
                shutil.copy(files[url], dest)
            restarts = []
            with mock.patch.object(bagholder, "update_mode", return_value="release"), mock.patch.object(bagholder, "_download", side_effect=download), \
                 mock.patch.object(bagholder, "request_restart", side_effect=lambda: restarts.append(1)):
                bagholder._state["updateError"] = ""
                # a broken archive: nothing changes, the error is reported
                files.update({"zip": bad, "sha": badsha})
                bagholder.perform_update("v9.9.9", {"assets": {"zip": "zip", "sha": "sha"}})
                self.assertIn("Update failed", bagholder._state["updateError"])
                self.assertEqual((Path(app) / "ledger.html").read_text(), "<old>")
                self.assertEqual(restarts, [])
                # a wrong checksum: nothing changes
                files.update({"zip": good, "sha": badsha})
                bagholder.perform_update("v9.9.9", {"assets": {"zip": "zip", "sha": "sha"}})
                self.assertIn("checksum", bagholder._state["updateError"])
                self.assertEqual((Path(app) / "ledger.html").read_text(), "<old>")
                # the real thing: files swapped, previous kept, marker written, restart requested
                files.update({"zip": good, "sha": sha})
                bagholder._state["updateError"] = ""
                bagholder.perform_update("v9.9.9", {"assets": {"zip": "zip", "sha": "sha"}})
                self.assertEqual(bagholder._state["updateError"], "")
                self.assertEqual((Path(app) / "ledger.html").read_text(), "<new>")
                self.assertIn("9.9.9", (Path(app) / "bagholder.py").read_text())
                self.assertEqual((Path(home) / "previous" / "ledger.html").read_text(), "<old>")
                self.assertEqual((Path(home) / "update-pending").read_text(), "v9.9.9")
                self.assertFalse((Path(app).parent / "evil.py").exists(), "a path that escapes the app folder is ignored")
                self.assertEqual(restarts, [1])
                bagholder._state["updating"] = ""

    def test_a_swap_that_fails_part_way_puts_every_file_back(self):
        import bagholder
        from unittest import mock
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as app, tempfile.TemporaryDirectory() as stage:
            bagholder.HOME = Path(home)
            bagholder.APP_DIR = Path(app)
            (Path(app) / "a.py").write_text("old a")
            (Path(app) / "b.py").write_text("old b")
            (Path(stage) / "a.py").write_text("new a")
            (Path(stage) / "b.py").write_text("new b")
            real = os.replace
            def flaky(src, dst):
                if str(dst).endswith("b.py"):
                    raise PermissionError("held open")
                real(src, dst)
            with mock.patch.object(bagholder.os, "replace", side_effect=flaky):
                with self.assertRaises(PermissionError):
                    bagholder._install_files(Path(stage), ["a.py", "b.py"], "v9.9.9")
            self.assertEqual((Path(app) / "a.py").read_text(), "old a", "the file already swapped is back")
            self.assertEqual((Path(app) / "b.py").read_text(), "old b")
            self.assertFalse((Path(home) / "update-pending").exists())

    def test_a_container_copy_binds_wide_keeps_the_host_check_and_never_updates(self):
        import bagholder
        from unittest import mock
        from datetime import datetime, timezone

        class Peer:
            def __init__(self, ip, host, port=8765):
                self.client_address = (ip, 50000)
                self.headers = {"Host": host}
                self.server = type("S", (), {"server_address": ("0.0.0.0", port)})()
        local, host_ok = bagholder.Handler._local, bagholder.Handler._host_ok
        # the desktop: loopback peers only, the Host as bound
        self.assertTrue(local(Peer("127.0.0.1", "127.0.0.1:8765")))
        self.assertFalse(local(Peer("172.18.0.1", "127.0.0.1:8765")))
        self.assertTrue(host_ok(Peer("127.0.0.1", "127.0.0.1:8765")))
        self.assertFalse(host_ok(Peer("127.0.0.1", "127.0.0.1:8798")), "the desktop's Host names its own port")
        with mock.patch.object(bagholder, "BIND_HOST", "0.0.0.0"):
            # the container: the peer is the bridge; the name must still be 127.0.0.1, under any published port
            self.assertTrue(local(Peer("172.18.0.1", "127.0.0.1:8798")))
            self.assertTrue(host_ok(Peer("172.18.0.1", "127.0.0.1:8798")))
            self.assertFalse(host_ok(Peer("172.18.0.1", "localhost:8765")))
            self.assertFalse(host_ok(Peer("172.18.0.1", "bagholder.example:8765")))
        # the container still hears of a release; it is told to pull, never installs into itself
        mine = bagholder.parse_version(bagholder.APP_VERSION)
        newer = "v%d.%d.%d" % (mine[0], mine[1], mine[2] + 1)
        with mock.patch.object(bagholder, "UPDATES_OFF", True), \
             mock.patch.object(bagholder, "_http_json", return_value={"tag_name": newer, "html_url": "https://github.com/x/y/releases/tag/" + newer, "assets": [{"name": "bagholder-%s-web.zip" % newer, "browser_download_url": "u"}]}):
            rec = bagholder.check_for_update(datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))
            self.assertEqual((rec["ok"], rec["updateAvailable"], rec["latest"]), (True, True, newer))
            self.assertFalse(bagholder.can_update(rec), "seen, not installable")
            self.assertEqual((bagholder.status_payload()["updateBy"], bagholder.status_payload()["updateUrl"]), ("image", bagholder.IMAGE_PAGE), "told of the release, sent to the image")
            out = bagholder.start_update()
            self.assertEqual((out["ok"], out["error"]), (False, bagholder.UPDATES_OFF_MESSAGE))
        self.assertEqual(bagholder.status_payload()["updateBy"], "app")

    def test_the_login_window_in_the_page_serves_frames_and_takes_input(self):
        import bagholder
        from unittest import mock
        calls = []
        class FakeWS:
            closed = False
            def close(self): self.closed = True
        ws = FakeWS()
        def cdp(sock, method, params=None, timeout=8):
            calls.append((method, params))
            return {"result": {"data": "/9j/AAAA"}} if method == "Page.captureScreenshot" else {"result": {}}
        page = [{"type": "page", "id": "P1", "webSocketDebuggerUrl": "ws://127.0.0.1:18765/devtools/page/P1"}]
        bagholder._login_view_drop()
        bagholder._state["capturing"] = True
        with mock.patch.object(bagholder, "_cdp_pages", return_value=page), mock.patch.object(bagholder, "_ws_connect", return_value=ws) as connect, \
             mock.patch.object(bagholder, "_cdp_call", side_effect=cdp):
            self.assertEqual(bagholder.login_frame(), b"\xff\xd8\xff\x00\x00\x00", "the window's screenshot, decoded")
            self.assertTrue(bagholder.login_input({"kind": "click", "x": 40, "y": 50})["ok"])
            self.assertTrue(bagholder.login_input({"kind": "text", "text": "me@example.com"})["ok"])
            self.assertTrue(bagholder.login_input({"kind": "text", "text": "7"})["ok"])
            self.assertTrue(bagholder.login_input({"kind": "text", "text": "123456"})["ok"], "a pasted code")
            self.assertTrue(bagholder.login_input({"kind": "key", "key": "Enter"})["ok"])
            self.assertTrue(bagholder.login_input({"kind": "wheel", "x": 1, "y": 2, "deltaY": 120})["ok"])
            self.assertFalse(bagholder.login_input({"kind": "key", "key": "F13"})["ok"])
            self.assertEqual(connect.call_count, 1, "one socket, kept across calls")
        methods = [m for m, _ in calls]
        self.assertEqual(methods[:4], ["Page.captureScreenshot", "Input.dispatchMouseEvent", "Input.dispatchMouseEvent", "Input.dispatchMouseEvent"])
        self.assertEqual([p["type"] for m, p in calls if m == "Input.dispatchMouseEvent"][:3], ["mouseMoved", "mousePressed", "mouseReleased"])
        self.assertIn(("Input.insertText", {"text": "me@example.com"}), calls, "an address is inserted as a block")
        typed = [(p["type"], p["key"], p.get("windowsVirtualKeyCode")) for m, p in calls if m == "Input.dispatchKeyEvent" and p["key"] in "1234567"]
        self.assertEqual(typed[:2], [("keyDown", "7", 55), ("keyUp", "7", 55)], "a keystroke is a real key event")
        self.assertEqual(len(typed), 2 + 12, "a pasted six-digit code is six keystrokes")
        enter = [p for m, p in calls if m == "Input.dispatchKeyEvent" and p["key"] == "Enter"]
        self.assertEqual([(p["type"], p["key"], p["windowsVirtualKeyCode"]) for p in enter], [("keyDown", "Enter", 13), ("keyUp", "Enter", 13)])
        self.assertEqual([p for m, p in calls if m == "Input.dispatchMouseEvent" and p["type"] == "mouseWheel"][0]["deltaY"], 120.0)
        # no window: no frame, and input says so
        with mock.patch.object(bagholder, "_cdp_pages", return_value=[]):
            self.assertIsNone(bagholder.login_frame())
            self.assertFalse(bagholder.login_input({"kind": "click", "x": 1, "y": 1})["ok"])
        self.assertTrue(ws.closed, "the socket is dropped with the window")
        bagholder._state["capturing"] = False
        self.assertIsNone(bagholder.login_frame(), "not waiting for a login: nothing to show")

    def test_the_container_launches_chromium_on_its_display_at_the_view_size(self):
        import bagholder
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BAGHOLDER_HOME"] = tmp
            store.set_home(tmp)
            bagholder.set_home(tmp) if hasattr(bagholder, "set_home") else None
            seen = {}
            class P:
                pid = 4242
                def poll(self): return None
            def popen(args, **kw):
                seen["args"] = args
                return P()
            bagholder._state["capturing"] = False
            bagholder._state["chrome_proc"] = None
            with mock.patch.object(bagholder, "LOGIN_VIEW", True), mock.patch.object(bagholder, "find_chrome", return_value="/usr/bin/chromium"), \
                 mock.patch.object(bagholder, "_login_browser_alive", return_value=False), mock.patch.object(bagholder, "_close_login_browser"), \
                 mock.patch.object(bagholder.subprocess, "Popen", side_effect=popen), mock.patch.object(bagholder.threading, "Thread"):
                self.assertTrue(bagholder.start_login_browser()["ok"])
            args = seen["args"]
            self.assertEqual(args[0], "/usr/bin/chromium")
            for flag in ("--no-sandbox", "--window-size=960,1000"):
                self.assertIn(flag, args)
            self.assertNotIn("--headless=new", args, "a real window on the virtual display: headless is turned away by Wealthsimple")
            self.assertEqual(args[-1], bagholder.LOGIN_URL, "the login page last, after the flags")
            bagholder._state["capturing"] = False
            bagholder._state["chrome_proc"] = None
        with mock.patch.dict(os.environ, {"BAGHOLDER_CHROME": "/definitely/not/there"}):
            self.assertNotEqual(bagholder.find_chrome(), "/definitely/not/there", "an explicit path is used only when it exists")

    def test_update_button_refuses_during_a_sync(self):
        import bagholder
        from unittest import mock
        with mock.patch.object(bagholder, "update_status", return_value={"updateAvailable": True, "latest": "v9.9.9", "assets": {"zip": "z", "sha": "s"}}):
            bagholder._state["syncing"] = True
            bagholder._state["updating"] = ""
            self.assertFalse(bagholder.start_update()["ok"])
            bagholder._state["syncing"] = False
            with mock.patch.object(bagholder, "update_status", return_value={"updateAvailable": False}):
                self.assertFalse(bagholder.start_update()["ok"], "nothing to install")


class WealthsimpleHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        os.environ["BAGHOLDER_HOME"] = self.home
        store.set_home(self.home)
        bagholder.set_home(self.home)
        store.ensure()
        with bagholder._lock:
            bagholder._state["connected"] = False
            bagholder._state["error"] = ""
            bagholder._state["syncing"] = False
            bagholder._state["capturing"] = False

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("BAGHOLDER_HOME", None)

    def _urlopen_for_js(self, js_body, html_body=None, js_headers=None, html_headers=None):
        html = html_body if html_body is not None else _login_html()
        if not isinstance(html, (bytes, bytearray)):
            html = html.encode("utf-8")

        def fake_urlopen(req, timeout=None, context=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "app-" in url and ".js" in url:
                return _FakeHTTPResp(js_body, headers=js_headers)
            return _FakeHTTPResp(html, headers=html_headers)

        return fake_urlopen

    def test_scrape_client_id_from_gzip_js(self):
        js = _app_js(FAKE_CLIENT_ID)
        gz = gzip.compress(js.encode("utf-8"))
        self.assertEqual(gz[:2], b"\x1f\x8b")
        fake = self._urlopen_for_js(
            gz,
            js_headers={"Content-Encoding": "gzip"},
        )
        with mock.patch.object(bagholder, "urlopen", side_effect=fake):
            cid = bagholder.scrape_client_id()
        self.assertEqual(cid, FAKE_CLIENT_ID)
        self.assertEqual(bagholder.CLIENT_ID_PATH.read_text(encoding="utf-8").strip(), FAKE_CLIENT_ID)

    def test_scrape_client_id_from_uncompressed_js(self):
        js = _app_js(FAKE_CLIENT_ID)
        fake = self._urlopen_for_js(js.encode("utf-8"))
        with mock.patch.object(bagholder, "urlopen", side_effect=fake):
            cid = bagholder.scrape_client_id()
        self.assertEqual(cid, FAKE_CLIENT_ID)

    def test_scrape_client_id_from_gzip_login_html(self):
        html_gz = gzip.compress(_login_html().encode("utf-8"))
        js = _app_js(FAKE_CLIENT_ID)
        fake = self._urlopen_for_js(
            js.encode("utf-8"),
            html_body=html_gz,
            html_headers={"Content-Encoding": "gzip"},
        )
        with mock.patch.object(bagholder, "urlopen", side_effect=fake):
            cid = bagholder.scrape_client_id()
        self.assertEqual(cid, FAKE_CLIENT_ID)

    def test_session_client_id_is_written_to_disk(self):
        sess = {"client_id": FAKE_CLIENT_ID}
        found = bagholder.client_id_for(sess)
        self.assertEqual(found, FAKE_CLIENT_ID)
        self.assertTrue(bagholder.CLIENT_ID_PATH.exists())
        self.assertEqual(bagholder.CLIENT_ID_PATH.read_text(encoding="utf-8").strip(), FAKE_CLIENT_ID)

    def test_token_info_uid_is_stored(self):
        sess = {"access_token": "tok", "refresh_token": "r"}
        info = {"application_uid": FAKE_CLIENT_ID}
        found = bagholder.apply_token_info_client_id(sess, info)
        self.assertEqual(found, FAKE_CLIENT_ID)
        self.assertEqual(sess.get("client_id"), FAKE_CLIENT_ID)
        self.assertEqual(bagholder.CLIENT_ID_PATH.read_text(encoding="utf-8").strip(), FAKE_CLIENT_ID)

        sess2 = {"access_token": "tok"}
        nested = bagholder.client_id_from_token_info({"application": {"uid": FAKE_CLIENT_ID}})
        self.assertEqual(nested, FAKE_CLIENT_ID)
        bagholder.apply_token_info_client_id(sess2, {"application": {"uid": FAKE_CLIENT_ID}})
        self.assertEqual(sess2.get("client_id"), FAKE_CLIENT_ID)

    def test_boot_stores_client_id_from_token_info_without_refresh(self):
        bagholder.save_session({
            "access_token": "tok",
            "refresh_token": "r",
            "expires_at": time_now_minus(),
        })
        with mock.patch.object(
            bagholder,
            "token_info",
            return_value={"application_uid": FAKE_CLIENT_ID},
        ):
            with mock.patch.object(bagholder, "refresh_session") as refresh:
                with mock.patch.object(bagholder, "scrape_client_id") as scrape:
                    bagholder.boot_session()
        scrape.assert_not_called()
        refresh.assert_not_called()
        saved = bagholder.load_session()
        self.assertEqual(saved.get("client_id"), FAKE_CLIENT_ID)
        self.assertTrue(bagholder._state["connected"])
        self.assertEqual(bagholder.CLIENT_ID_PATH.read_text(encoding="utf-8").strip(), FAKE_CLIENT_ID)

    def test_capture_stores_client_id_from_token_info_uid(self):
        with mock.patch.object(
            bagholder,
            "token_info",
            return_value={"application_uid": FAKE_CLIENT_ID, "identity_canonical_id": "ident-1"},
        ):
            with mock.patch.object(bagholder, "scrape_client_id") as scrape:
                with mock.patch.object(bagholder, "refresh_session", return_value=True):
                    with mock.patch.object(bagholder.threading, "Thread"):
                        result = bagholder.capture_tokens({
                            "access_token": "tok",
                            "refresh_token": "r",
                        })
        self.assertTrue(result.get("ok"))
        scrape.assert_not_called()
        saved = bagholder.load_session()
        self.assertEqual(saved.get("client_id"), FAKE_CLIENT_ID)
        self.assertEqual(bagholder.CLIENT_ID_PATH.read_text(encoding="utf-8").strip(), FAKE_CLIENT_ID)



    def test_refresh_now_posts_when_expiry_is_not_near(self):
        sess = {
            "refresh_token": "r",
            "client_id": FAKE_CLIENT_ID,
            "expires_at": "2099-01-01T00:00:00.000Z",
        }
        bagholder.save_session(sess)
        with bagholder._lock:
            bagholder._state["connected"] = True
            bagholder._state["error"] = ""
        with mock.patch.object(
            bagholder,
            "refresh_session",
            return_value=True,
        ) as refresh:
            result = bagholder.refresh_now()
        refresh.assert_called_once()
        self.assertTrue(result.get("ok"))
        self.assertTrue(bagholder._state["connected"])
        self.assertEqual(bagholder._state["error"], "")

    def test_refresh_session_without_client_id_does_not_scrape_or_post(self):
        bagholder.save_session({"refresh_token": "r"})
        self.assertFalse(bagholder.CLIENT_ID_PATH.exists())
        with mock.patch.object(bagholder, "scrape_client_id") as scrape:
            with mock.patch.object(bagholder, "_http_json") as http:
                ok = bagholder.refresh_session({"refresh_token": "r"})
        self.assertFalse(ok)
        scrape.assert_not_called()
        http.assert_not_called()
        self.assertEqual(bagholder._state["error"], "session has no client id")
        self.assertTrue(bagholder.SESSION_PATH.exists())
        self.assertEqual(bagholder.load_session().get("refresh_token"), "r")

    def test_only_open_margin_accounts_are_asked_for_buying_power(self):
        accounts = [
            {"id": "tfsa-1", "unifiedAccountType": "SELF_DIRECTED_TFSA", "status": "open"},
            {"id": "nr-1", "unifiedAccountType": "SELF_DIRECTED_NON_REGISTERED_MARGIN", "status": "open"},
            {"id": "nr-2", "unifiedAccountType": "SELF_DIRECTED_JOINT_NON_REGISTERED_MARGIN", "status": "closed"},
            {"id": "cash-1", "unifiedAccountType": "CASH", "status": "open"},
            {"id": "", "unifiedAccountType": "SELF_DIRECTED_NON_REGISTERED_MARGIN", "status": "open"},
        ]
        self.assertEqual(bagholder.margin_account_ids(accounts), ["nr-1"], "a TFSA's buying power is cash, not margin; a closed margin account holds nothing")

    def test_parse_margin_and_fetch_margin(self):
        available = {"account": {"financials": {"current": {"marginV3": {"trading": {"buyingPower": {"__typename": "BuyingPowerMetricAvailable", "total": {"amount": "6817.33", "currency": "CAD"}, "restrictions": []}}}}}}}
        unavailable = {"account": {"financials": {"current": {"marginV3": {"trading": {"buyingPower": {"__typename": "BuyingPowerMetricUnavailable", "reason": {"__typename": "UnavailableSecurities", "securities": [{"securityId": "s1", "status": "x"}, {"securityId": "s2", "status": "x"}]}}}}}}}}
        none = {"account": {"financials": {"current": {"marginV3": None}}}}
        self.assertEqual(bagholder.parse_margin(available), {"buyingPower": 6817.33, "currency": "CAD", "unavailable": ""})
        self.assertEqual(bagholder.parse_margin(unavailable), {"buyingPower": None, "currency": "CAD", "unavailable": "UnavailableSecurities (2 securities)"})
        self.assertIsNone(bagholder.parse_margin(none))
        self.assertIsNone(bagholder.parse_margin({}))
        answers = {"acct-1": available, "acct-2": none, "acct-3": unavailable}
        calls = []

        def fake_graphql(sess, operation, variables, query=None):
            calls.append((operation, variables["accountId"], variables["currency"]))
            return answers[variables["accountId"]]

        with mock.patch.object(bagholder, "graphql", fake_graphql):
            rows = bagholder.fetch_margin({"access_token": "x"}, ["acct-1", "acct-2", "acct-3", ""])
        self.assertEqual([c[0] for c in calls], ["FetchAccountCurrentMarginBuyingPowerV2"] * 3)
        self.assertEqual([c[2] for c in calls], ["CAD"] * 3)
        self.assertEqual([(r["accountId"], r["buyingPower"], r["unavailable"]) for r in rows],
                         [("acct-1", 6817.33, ""), ("acct-3", None, "UnavailableSecurities (2 securities)")], "an account without margin figures is not a row")
        self.assertTrue(all(r["fetchedAt"] for r in rows))

    def test_refresh_session_uses_cached_client_id_file(self):
        bagholder.save_client_id(FAKE_CLIENT_ID)
        sess = {"refresh_token": "r"}
        with mock.patch.object(bagholder, "scrape_client_id") as scrape:
            with mock.patch.object(
                bagholder,
                "_http_json",
                return_value={"access_token": "tok", "expires_in": 3600},
            ) as http:
                ok = bagholder.refresh_session(sess)
        self.assertTrue(ok)
        scrape.assert_not_called()
        http.assert_called_once()
        self.assertEqual(sess.get("client_id"), FAKE_CLIENT_ID)
        self.assertIsInstance(sess.get("expires_at"), str)
        self.assertIn("T", sess.get("expires_at"))
        self.assertTrue(sess.get("expires_at").endswith("Z"))

    def test_refresh_session_sets_http_and_oauth_error(self):
        sess = {"refresh_token": "r", "client_id": FAKE_CLIENT_ID}
        bagholder.save_session(sess)
        with mock.patch.object(
            bagholder,
            "_http_json",
            return_value={"error": "invalid_client", "_http_status": 401},
        ):
            ok = bagholder.refresh_session(sess)
        self.assertFalse(ok)
        err = bagholder._state["error"]
        self.assertIn("HTTP 401", err)
        self.assertIn("invalid_client", err)
        self.assertTrue(err.startswith("Wealthsimple token refresh HTTP 401"))
        self.assertNotIn(FAKE_CLIENT_ID, err)
        self.assertNotIn("r", err.split())
        self.assertTrue(bagholder.SESSION_PATH.exists())
        saved = bagholder.load_session()
        self.assertEqual(saved.get("refresh_token"), "r")

    def test_refresh_session_sets_http_error(self):
        sess = {"refresh_token": "r", "client_id": FAKE_CLIENT_ID}
        bagholder.save_session(sess)
        with mock.patch.object(
            bagholder,
            "_http_json",
            return_value={"error": "invalid_grant", "_http_status": 400},
        ):
            ok = bagholder.refresh_session(sess)
        self.assertFalse(ok)
        self.assertEqual(bagholder._state["error"], bagholder.REFUSED_LOGIN_MESSAGE)
        self.assertTrue(bagholder.SESSION_PATH.exists())
        saved = bagholder.load_session()
        self.assertEqual(saved.get("refresh_token"), "r")

    def test_refresh_session_sets_oauth_error_text(self):
        sess = {"refresh_token": "r", "client_id": FAKE_CLIENT_ID}
        with mock.patch.object(bagholder, "_http_json", return_value={"error": "invalid_grant"}):
            ok = bagholder.refresh_session(sess)
        self.assertFalse(ok)
        self.assertEqual(bagholder._state["error"], bagholder.REFUSED_LOGIN_MESSAGE)

    def test_ensure_fresh_token_sets_error_on_failed_refresh(self):
        sess = {"refresh_token": "r", "expires_at": time_now_minus()}
        bagholder.save_session(sess)
        with mock.patch.object(bagholder, "refresh_session", return_value=False):
            ok = bagholder.ensure_fresh_token(sess)
        self.assertFalse(ok)
        self.assertFalse(bagholder._state["connected"])
        self.assertTrue(bagholder._state["error"])
        self.assertTrue(bagholder.SESSION_PATH.exists())

    def test_boot_session_sets_error_when_refresh_fails(self):
        sess = {"refresh_token": "r", "expires_at": time_now_minus()}
        bagholder.save_session(sess)
        with mock.patch.object(bagholder, "refresh_session", return_value=False):
            bagholder.boot_session()
        self.assertFalse(bagholder._state["connected"])
        self.assertTrue(bagholder._state["error"])
        self.assertTrue(bagholder.SESSION_PATH.exists())

    def test_http_json_invalid_body_returns_error_dict(self):
        def fake_urlopen(req, timeout=None, context=None):
            return _FakeHTTPResp(b"not-json{", status=200)

        with mock.patch.object(bagholder, "urlopen", side_effect=fake_urlopen):
            data = bagholder._http_json("GET", "https://example.test/token")
        self.assertEqual(data.get("error"), "invalid_json")
        self.assertIn("_http_status", data)

    def test_http_json_reads_gzip_json(self):
        raw = gzip.compress(b'{"access_token":"tok","expires_in":3600}')

        def fake_urlopen(req, timeout=None, context=None):
            return _FakeHTTPResp(raw, headers={"Content-Encoding": "gzip"})

        with mock.patch.object(bagholder, "urlopen", side_effect=fake_urlopen):
            data = bagholder._http_json("POST", "https://example.test/token", {"grant_type": "refresh_token"})
        self.assertEqual(data.get("access_token"), "tok")
        self.assertNotIn("_http_status", data)



    def test_trade_groups_roundtrip(self):
        groups = [
            {"id": "g_one", "locked": True, "members": ["a|b|1.00000000", "c|d|2.00000000"]},
            {"id": "g_one", "locked": False, "members": ["dup"]},
            {"id": "", "members": ["x"]},
            {"id": "g_empty", "members": []},
            {"id": "g_two", "locked": 1, "members": ["x", "x", "y"]},
        ]
        saved = store.save_trade_groups(groups)
        self.assertEqual([g["id"] for g in saved], ["g_one", "g_two"])
        self.assertEqual(saved[0]["members"], ["a|b|1.00000000", "c|d|2.00000000"])
        self.assertEqual(saved[1]["members"], ["x", "y"])
        self.assertTrue(saved[0]["locked"])
        self.assertTrue(saved[1]["locked"])
        snap = store.snapshot()
        self.assertEqual(snap["tradeGroups"], saved)
        self.assertEqual(store.trade_groups(), saved)

    def test_trade_groups_rejects_non_list(self):
        store.set_meta("trade_groups", "{}")
        self.assertEqual(store.trade_groups(), [])
        self.assertEqual(store.save_trade_groups(None), [])

    def test_trade_notes_roundtrip(self):
        saved = store.save_trade_notes({
            "g_one": {"thesis": "scale in", "tag": "hold", "grade": "A"},
            "g_empty": {"thesis": "", "tag": "", "grade": ""},
            "g_bad": {"thesis": "x", "tag": "y", "grade": "Z"},
            "": {"thesis": "nope"},
        })
        self.assertEqual(saved["g_one"]["grade"], "A")
        self.assertEqual(saved["g_one"]["tag"], "hold")
        self.assertNotIn("g_empty", saved)
        self.assertEqual(saved["g_bad"]["grade"], "")
        self.assertEqual(saved["g_bad"]["thesis"], "x")
        snap = store.snapshot()
        self.assertEqual(snap["notes"], saved)
        self.assertEqual(store.trade_notes(), saved)


    def test_nav_history_migrates_date_pk_to_account_date(self):
        path = store.db_path()
        conn = sqlite3.connect(str(path))
        conn.execute("DROP TABLE nav_history")
        conn.execute(
            """
            CREATE TABLE nav_history (
                date TEXT PRIMARY KEY,
                equity REAL,
                currency TEXT,
                net_deposits REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO nav_history (date, equity, currency, net_deposits) "
            "VALUES (?, ?, ?, ?)",
            ("2024-01-02", 1000.0, "CAD", 100.0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )
        conn.commit()
        conn.close()
        store.ensure()
        snap = store.snapshot()
        self.assertEqual(store.get_meta("schema_version"), str(store.SCHEMA_VERSION))
        self.assertEqual(len(snap["navHistory"]), 1)
        self.assertEqual(snap["navHistory"][0]["date"], "2024-01-02")
        self.assertEqual(snap["navHistory"][0]["equity"], 1000.0)
        self.assertEqual(snap["navHistory"][0]["netDeposits"], 100.0)
        self.assertNotIn("accountId", snap["navHistory"][0])
        self.assertEqual(snap["navByAccount"], {})
        info_conn = sqlite3.connect(str(path))
        info_conn.row_factory = sqlite3.Row
        pk = {r["name"] for r in info_conn.execute("PRAGMA table_info(nav_history)") if r["pk"]}
        info_conn.close()
        self.assertEqual(pk, {"account_id", "date"})

    def test_replace_nav_by_account_and_snapshot(self):
        store.replace_nav(
            [
                {"date": "2024-01-01", "equity": 10, "currency": "CAD", "netDeposits": 1, "accountId": ""},
                {"date": "2024-01-02", "equity": 11, "net_deposits": 2},
                {"date": "2024-01-01", "equity": 5, "currency": "CAD", "accountId": "TFSA"},
                {"date": "2024-01-02", "equity": 6, "account_id": "TFSA", "netDeposits": 3},
                {"date": "2024-01-01", "equity": 7, "accountId": "RRSP"},
            ]
        )
        snap = store.snapshot()
        self.assertEqual([p["date"] for p in snap["navHistory"]], ["2024-01-01", "2024-01-02"])
        self.assertEqual(snap["navHistory"][0]["equity"], 10)
        self.assertEqual(set(snap["navByAccount"]), {"TFSA", "RRSP"})
        self.assertEqual(snap["navByAccount"]["TFSA"][0]["equity"], 5)
        self.assertEqual(snap["navByAccount"]["TFSA"][1]["netDeposits"], 3)
        self.assertNotIn("accountId", snap["navByAccount"]["TFSA"][0])
        store.replace_nav(
            [
                {"date": "2024-06-01", "equity": 20, "accountId": ""},
                {"date": "2024-06-01", "equity": 8, "accountId": "TFSA"},
            ]
        )
        snap = store.snapshot()
        self.assertEqual([p["date"] for p in snap["navHistory"]], ["2024-06-01"])
        self.assertEqual(set(snap["navByAccount"]), {"TFSA"})
        self.assertNotIn("RRSP", snap["navByAccount"])

    def test_upsert_nav_keeps_existing_days(self):
        store.replace_nav(
            [
                {"date": "2024-01-01", "equity": 10, "accountId": ""},
                {"date": "2024-01-01", "equity": 5, "accountId": "TFSA"},
            ]
        )
        store.upsert_nav(
            [
                {"date": "2024-01-02", "equity": 11, "accountId": ""},
                {"date": "2024-01-01", "equity": 6, "accountId": "TFSA"},
            ]
        )
        snap = store.snapshot()
        self.assertEqual([p["date"] for p in snap["navHistory"]], ["2024-01-01", "2024-01-02"])
        self.assertEqual(snap["navHistory"][1]["equity"], 11)
        self.assertEqual(snap["navByAccount"]["TFSA"][0]["equity"], 6)
        self.assertEqual(store.nav_last_dates(), {"": "2024-01-02", "TFSA": "2024-01-01"})

    def test_fetch_nav_history_since_date_skips_older_years(self):
        calls = []

        def fake_graphql(sess, operation, variables, query=None):
            calls.append(dict(variables))
            return {"identity": {"financials": {"historicalDaily": {"edges": [], "pageInfo": {}}}}}

        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql):
            bagholder.fetch_nav_history({"access_token": "t"}, "ident-1", since_date="2026-08-30")
        self.assertTrue(calls)
        for variables in calls:
            self.assertGreaterEqual(variables["startDate"], "2026-08-30")
            self.assertTrue(variables["startDate"].startswith("2026"))

    def test_nav_account_groups_joins_same_nickname(self):
        groups = bagholder.nav_account_groups(
            [
                {"id": "cad-1", "nickname": "TFSA", "currency": "CAD"},
                {"id": "usd-1", "nickname": "TFSA", "currency": "USD"},
                {"id": "rrsp-1", "nickname": "", "unifiedAccountType": "RRSP"},
            ]
        )
        self.assertEqual(groups["TFSA"], ["cad-1", "usd-1"])
        self.assertEqual(groups["RRSP"], ["rrsp-1"])

    def test_fetch_nav_history_identity_wide_omits_account_ids(self):
        calls = []

        def fake_graphql(sess, operation, variables, query=None):
            calls.append((operation, dict(variables), query))
            return {"identity": {"financials": {"historicalDaily": {"edges": [], "pageInfo": {}}}}}

        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql):
            bagholder.fetch_nav_history({"access_token": "t"}, "ident-1")
        self.assertTrue(calls)
        for op, variables, query in calls:
            self.assertEqual(op, "IdentityHistoricalFinancialsQuery")
            self.assertNotIn("accountIds", variables)
            self.assertIs(query, bagholder.Q_IDENTITY_HISTORICAL_FINANCIALS)
            self.assertEqual(variables.get("limit"), 400)
        self.assertNotIn("$accountIds", bagholder.Q_IDENTITY_HISTORICAL_FINANCIALS)
        self.assertNotIn("accounts: $accountIds", bagholder.Q_IDENTITY_HISTORICAL_FINANCIALS)

    def test_fetch_account_nav_history_uses_account_query(self):
        calls = []

        def fake_graphql(sess, operation, variables, query=None):
            calls.append((operation, dict(variables), query))
            return {
                "account": {
                    "financials": {
                        "historicalDaily": {
                            "edges": [
                                {
                                    "node": {
                                        "date": "2024-01-02",
                                        "netLiquidationValueV2": {"amount": "12.5", "currency": "CAD"},
                                        "netDepositsV2": {"amount": "3", "currency": "CAD"},
                                    }
                                }
                            ],
                            "pageInfo": {},
                        }
                    }
                }
            }

        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql):
            pts = bagholder.fetch_account_nav_history({"access_token": "t"}, "acct-1")
        self.assertTrue(calls)
        self.assertEqual(pts[0]["date"], "2024-01-02")
        self.assertEqual(pts[0]["equity"], 12.5)
        self.assertEqual(pts[0]["netDeposits"], 3.0)
        for op, variables, query in calls:
            self.assertEqual(op, "FetchAccountHistoricalFinancials")
            self.assertEqual(variables.get("id"), "acct-1")
            self.assertEqual(variables.get("first"), 400)
            self.assertEqual(variables.get("resolution"), "DAILY")
            self.assertNotIn("accountIds", variables)
            self.assertNotIn("identityId", variables)
            self.assertIs(query, bagholder.Q_FETCH_ACCOUNT_HISTORICAL_FINANCIALS)
        self.assertIn("account(id: $id)", bagholder.Q_FETCH_ACCOUNT_HISTORICAL_FINANCIALS)
        self.assertIn("$resolution: DateResolution!", bagholder.Q_FETCH_ACCOUNT_HISTORICAL_FINANCIALS)
        self.assertIn("FetchAccountHistoricalFinancials", bagholder.QUERIES)

    def test_nav_points_from_payload_accepts_v2_and_identity(self):
        ident_pts, _ = bagholder._nav_points_from_payload(
            {
                "identity": {
                    "financials": {
                        "historicalDaily": {
                            "edges": [
                                {
                                    "node": {
                                        "date": "2024-02-01",
                                        "netLiquidationValue": {"amount": 10, "currency": "CAD"},
                                        "netDeposits": {"amount": 1, "currency": "CAD"},
                                    }
                                }
                            ],
                            "pageInfo": {},
                        }
                    }
                }
            }
        )
        self.assertEqual(ident_pts[0]["equity"], 10.0)
        self.assertEqual(ident_pts[0]["netDeposits"], 1.0)
        acc_pts, _ = bagholder._nav_points_from_payload(
            {
                "account": {
                    "financials": {
                        "historicalDaily": {
                            "edges": [
                                {
                                    "node": {
                                        "date": "2024-02-01",
                                        "netLiquidationValueV2": {"amount": "20", "currency": "CAD"},
                                        "netDepositsV2": {"amount": "4", "currency": "CAD"},
                                    }
                                }
                            ],
                            "pageInfo": {},
                        }
                    }
                }
            }
        )
        self.assertEqual(acc_pts[0]["equity"], 20.0)
        self.assertEqual(acc_pts[0]["netDeposits"], 4.0)

    def test_merge_nav_points_sums_equity_and_deposits(self):
        merged = bagholder.merge_nav_points(
            [
                [{"date": "2024-01-01", "equity": 10, "currency": "CAD", "netDeposits": 1}],
                [
                    {"date": "2024-01-01", "equity": 5, "currency": "CAD", "netDeposits": 2},
                    {"date": "2024-01-02", "equity": 6, "currency": "CAD"},
                ],
            ]
        )
        self.assertEqual(merged[0]["date"], "2024-01-01")
        self.assertEqual(merged[0]["equity"], 15.0)
        self.assertEqual(merged[0]["netDeposits"], 3.0)
        self.assertEqual(merged[1]["date"], "2024-01-02")
        self.assertEqual(merged[1]["equity"], 6.0)
        self.assertNotIn("netDeposits", merged[1])

    def test_fetch_nickname_nav_history_merges_and_records_errors(self):
        def fake_account(sess, account_id, since_date=None):
            if account_id == "rrsp-1":
                raise RuntimeError("nope")
            if account_id == "cad-1":
                return [{"date": "2024-01-01", "equity": 10, "currency": "CAD", "netDeposits": 1}]
            if account_id == "usd-1":
                return [{"date": "2024-01-01", "equity": 5, "currency": "CAD", "netDeposits": 2}]
            return []

        accounts = [
            {"id": "cad-1", "nickname": "TFSA"},
            {"id": "usd-1", "nickname": "TFSA"},
            {"id": "rrsp-1", "nickname": "RRSP"},
        ]
        with mock.patch.object(bagholder, "fetch_account_nav_history", side_effect=fake_account):
            pts, errors = bagholder.fetch_nickname_nav_history({"access_token": "t"}, accounts)
        self.assertEqual([p["accountId"] for p in pts], ["TFSA"])
        self.assertEqual(pts[0]["equity"], 15.0)
        self.assertEqual(pts[0]["netDeposits"], 3.0)
        self.assertTrue(any(e.startswith("RRSP:") for e in errors))
        self.assertIn("nope", errors[0])



class _OrdersBase(unittest.TestCase):
    """A book with a margin account, a TFSA and the QNC listings, for the ticket tests."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BAGHOLDER_HOME"] = self.tmp.name
        store.set_home(self.tmp.name)
        bagholder.set_home(self.tmp.name)
        store.ensure()
        store.replace_accounts([
            {"id": "acct-margin", "nickname": "Trading", "unifiedAccountType": "SELF_DIRECTED_NON_REGISTERED_MARGIN", "currency": "CAD", "status": "open", "type": "non_registered"},
            {"id": "acct-tfsa", "nickname": "TFSA", "unifiedAccountType": "SELF_DIRECTED_TFSA", "currency": "CAD", "status": "open", "type": "tfsa"},
            {"id": "acct-crypto", "nickname": "Crypto", "unifiedAccountType": "SELF_DIRECTED_CRYPTO", "currency": "CAD", "status": "open", "type": "crypto"},
            {"id": "acct-old", "nickname": "Old", "unifiedAccountType": "SELF_DIRECTED_RRSP", "currency": "CAD", "status": "closed", "type": "rrsp"},
            {"id": "acct-managed", "nickname": "Managed", "unifiedAccountType": "MANAGED_TFSA", "currency": "CAD", "status": "open", "type": "tfsa"},
        ])
        store.upsert_securities([
            {"id": "sec-o-1", "symbol": "QNC", "name": "", "primaryExchange": "", "primaryMic": "", "currency": "USD", "underlyingId": "sec-s-us"},
            {"id": "sec-s-us", "symbol": "QNC", "name": "Quantum Emotion Corp", "primaryExchange": "NYSE", "primaryMic": "XNYS", "currency": "USD", "underlyingId": None},
            {"id": "sec-s-ca", "symbol": "QNC.TO", "name": "Quantum Emotion Corp", "primaryExchange": "TSX-V", "primaryMic": "XTSX", "currency": "CAD", "underlyingId": None},
        ])
        store.replace_margin([{"accountId": "acct-margin", "buyingPower": 12680.45, "currency": "CAD"}])

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("BAGHOLDER_HOME", None)

    def _ticket(self, **over):
        body = {"symbol": "QNC", "securityId": "sec-s-us", "accountId": "acct-margin", "side": "BUY", "type": "LIMIT", "tif": "DAY",
                "quantity": 25, "limitPrice": 165.4, "stopPrice": None, "currency": "USD",
                "stopLoss": {"kind": "stop", "price": 157.13}, "takeProfit": {"price": 181.94}}
        body.update(over)
        return body

    def _sent(self):
        """A ticket sent live against a fake Wealthsimple that answers with order id ws-1."""
        with mock.patch.object(bagholder, "graphql", return_value={"soOrdersCreateOrder": {"errors": [], "order": {"orderId": "ws-1"}}}), \
             mock.patch.object(bagholder, "ORDERS_LIVE", True), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}), \
             mock.patch.object(bagholder.threading, "Thread"):
            return bagholder.place_order(self._ticket())["id"]


class OrderTicketTest(_OrdersBase):
    """The order ticket: what the page asks for, what the store keeps, what would be sent."""

    def test_tradable_accounts_are_open_self_directed_securities_accounts(self):
        ids = [a["id"] for a in bagholder.order_accounts()]
        self.assertEqual(ids, ["acct-margin", "acct-tfsa"], "crypto, managed and closed accounts are not offered")
        margin = {a["id"]: a["margin"] for a in bagholder.order_accounts()}
        self.assertTrue(margin["acct-margin"]); self.assertFalse(margin["acct-tfsa"])

    def test_a_symbol_resolves_to_its_share_listing_before_an_option_contract(self):
        self.assertEqual(bagholder.resolve_security("QNC")["id"], "sec-s-us")
        self.assertEqual(bagholder.resolve_security("qnc.to")["id"], "sec-s-ca")
        self.assertEqual(bagholder.resolve_security("", "sec-s-ca")["id"], "sec-s-ca")
        self.assertIsNone(bagholder.resolve_security("NOPE"))
        # an id the book carries before its listing was fetched still names a security
        self.assertEqual(bagholder.resolve_security("NVDA", "sec-nvda")["id"], "sec-nvda")

    def test_the_quote_card_is_read_from_wealthsimples_summary(self):
        node = {"id": "sec-s-us", "buyable": True, "sellable": True, "wsTradeEligible": True, "securityType": "EQUITY", "currency": "USD", "status": "ACTIVE",
                "stock": {"name": "NVIDIA Corp", "symbol": "NVDA", "primaryExchange": "NASDAQ", "primaryMic": "XNAS"},
                "quoteV2": {"__typename": "EquityQuote", "ask": 165.42, "bid": 165.38, "currency": "USD", "price": 165.40, "previousBaseline": 163.42,
                            "marketStatus": "OPEN", "askSize": 300, "bidSize": 100, "mid": 165.40, "quotedAsOf": "2026-09-10T15:30:00Z"}}
        q = bagholder.parse_quote(node)
        self.assertEqual((q["symbol"], q["exchange"], q["currency"]), ("NVDA", "NASDAQ", "USD"))
        self.assertEqual((q["last"], q["bid"], q["ask"], q["bidSize"], q["askSize"], q["mid"]), (165.40, 165.38, 165.42, 100, 300, 165.40))
        self.assertAlmostEqual(q["change"], 1.98, places=6)
        self.assertAlmostEqual(q["changePct"], 1.98 / 163.42, places=9)
        self.assertEqual(q["marketStatus"], "OPEN")
        self.assertIsNone(bagholder.parse_quote({"stock": {}}), "no id, no quote")
        md = bagholder.parse_market_data({"security": {"allowedOrderSubtypes": ["LIMIT", "FRACTIONAL", "MARKET"], "marginRates": {"clientMarginRate": 30}}})
        self.assertEqual(md["orderTypes"], ["MARKET", "LIMIT"], "only the ticket's types, in the ticket's order")
        self.assertAlmostEqual(md["marginRate"], 0.30, "a percentage becomes a fraction")
        bp = bagholder.parse_buying_power({"account": {"financials": {"current": {"tradingBalanceViewV2": {"buyingPower": {"quantity": 12680.45, "currency": "USD"}, "cash": {"quantity": 3420.18, "currency": "USD"}}}}}})
        self.assertEqual((bp["buyingPower"], bp["cash"], bp["currency"]), (12680.45, 3420.18, "USD"))

    def test_ticket_quote_answers_with_everything_the_panel_shows(self):
        def fake_graphql(sess, operation, variables, query=None):
            if operation == "FetchSecuritiesSummary":
                self.assertEqual(variables["ids"], ["sec-s-us"])
                return {"securities": [{"id": "sec-s-us", "buyable": True, "sellable": True, "wsTradeEligible": True, "securityType": "EQUITY", "currency": "USD",
                                        "stock": {"name": "Quantum Emotion Corp", "symbol": "QNC", "primaryExchange": "NYSE"},
                                        "quoteV2": {"__typename": "EquityQuote", "ask": 3.02, "bid": 3.0, "currency": "USD", "price": 3.01, "previousBaseline": 2.9, "marketStatus": "OPEN", "askSize": 5, "bidSize": 7}}]}
            if operation == "FetchSecurityMarketData":
                return {"security": {"id": "sec-s-us", "allowedOrderSubtypes": ["MARKET", "LIMIT", "STOP_LIMIT"], "marginRates": {"clientMarginRate": 0.5}}}
            if operation == "FetchTradingBalanceBuyingPower":
                self.assertEqual((variables["accountCanonicalId"], variables["currency"], variables["securityId"]), ("acct-margin", "USD", "sec-s-us"))
                return {"account": {"financials": {"current": {"tradingBalanceViewV2": {"buyingPower": {"quantity": 9000.0, "currency": "USD"}, "cash": {"quantity": 100.0, "currency": "USD"}}}}}}
            raise AssertionError(operation)
        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}):
            r = bagholder.ticket_quote("QNC", "", "acct-margin")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["quote"]["symbol"], "QNC")
        self.assertEqual(r["orderTypes"], ["MARKET", "LIMIT", "STOP_LIMIT"])
        self.assertEqual(r["marginRate"], 0.5)
        self.assertEqual(r["marginAvailable"], 12680.45, "the margin account's available margin, from the stored buying power")
        self.assertEqual((r["buyingPower"], r["cash"]), (9000.0, 100.0))
        self.assertEqual([a["id"] for a in r["accounts"]], ["acct-margin", "acct-tfsa"])
        self.assertTrue(r["live"], "orders are live by default")
        with mock.patch.object(bagholder, "_ticket_session", return_value=None):
            self.assertEqual(bagholder.ticket_quote("QNC", "", "acct-margin")["error"], "Not connected.")
        self.assertIn("No listing stored", bagholder.ticket_quote("NOPE", "", "acct-margin")["error"])

    def test_the_request_is_the_one_wealthsimples_web_app_sends(self):
        row, req, err = bagholder.order_request(self._ticket())
        self.assertEqual(err, "")
        self.assertTrue(req["externalId"].startswith("order-"))
        self.assertEqual({k: v for k, v in req.items() if k != "externalId"},
                         {"canonicalAccountId": "acct-margin", "executionType": "LIMIT", "orderType": "BUY_QUANTITY", "quantity": 25.0, "securityId": "sec-s-us", "timeInForce": "DAY", "limitPrice": 165.4})
        self.assertEqual(row["stopLoss"], {"kind": "stop", "price": 157.13, "trail": None, "trailUnit": "pct"})
        self.assertEqual(row["takeProfit"], {"price": 181.94})
        self.assertEqual((row["symbol"], row["currency"], row["account"]), ("QNC", "USD", "Trading"))
        _, req, _ = bagholder.order_request(self._ticket(type="MARKET", tif="UNTIL_CANCEL"))
        self.assertNotIn("limitPrice", req); self.assertNotIn("stopPrice", req); self.assertEqual(req["timeInForce"], "UNTIL_CANCEL")
        _, req, _ = bagholder.order_request(self._ticket(type="STOP_LIMIT", stopPrice=170.0))
        self.assertEqual((req["executionType"], req["stopPrice"], req["limitPrice"]), ("STOP_LIMIT", 170.0, 165.4))
        row, req, _ = bagholder.order_request(self._ticket(side="SELL", type="STOP", stopPrice=150.0))
        self.assertEqual((req["executionType"], req["orderType"], req["stopPrice"]), ("STOP", "SELL_QUANTITY", 150.0))
        self.assertIsNone(row["stopLoss"], "a sell has nothing to protect"); self.assertIsNone(row["takeProfit"])
        row, _, _ = bagholder.order_request(self._ticket(stopLoss={"kind": "trail", "trail": 5, "trailUnit": "pct"}))
        self.assertEqual(row["stopLoss"], {"kind": "trail", "price": None, "trail": 5.0, "trailUnit": "pct"})

    def test_a_bad_ticket_is_refused_with_the_reason(self):
        bad = lambda **o: bagholder.order_request(self._ticket(**o))[2]
        self.assertIn("Quantity", bad(quantity=0))
        self.assertIn("limit price", bad(limitPrice=None))
        self.assertIn("stop price", bad(type="STOP", stopPrice=None))
        self.assertIn("account", bad(accountId="acct-crypto"))
        self.assertIn("No listing", bad(symbol="NOPE", securityId=""))
        self.assertIn("Side", bad(side="HOLD"))
        self.assertIn("Order type", bad(type="TRAILING"))
        self.assertIn("Time in force", bad(tif="WEEK"))
        self.assertIn("stop loss price", bad(stopLoss={"kind": "stop", "price": 0}))
        self.assertIn("take profit", bad(takeProfit={"price": None}))

    def test_orders_are_live_unless_the_dry_setting_is_on(self):
        self.assertTrue(bagholder.ORDERS_LIVE, "imported without BAGHOLDER_DRY_ORDERS: live")

    def test_under_the_dry_setting_a_submit_is_recorded_and_nothing_is_sent(self):
        with mock.patch.object(bagholder, "graphql", side_effect=AssertionError("must not be called")), mock.patch.object(bagholder, "ORDERS_LIVE", False):
            r = bagholder.place_order(self._ticket())
            self.assertFalse(bagholder.status_payload()["ordersLive"])
        self.assertTrue(r["ok"]); self.assertEqual(r["status"], "dry")
        rows = store.list_orders()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["id"], rows[0]["status"], rows[0]["side"], rows[0]["type"], rows[0]["quantity"]), (r["id"], "dry", "BUY", "LIMIT", 25.0))
        self.assertEqual(rows[0]["request"]["executionType"], "LIMIT")
        self.assertEqual(rows[0]["stopLoss"]["price"], 157.13)
        self.assertEqual(store.get_order(r["id"])["takeProfit"], {"price": 181.94})

    def test_by_default_the_order_goes_to_wealthsimple_and_the_answer_is_kept(self):
        sent = []
        def fake_graphql(sess, operation, variables, query=None):
            sent.append((operation, variables))
            return {"soOrdersCreateOrder": {"errors": [], "order": {"orderId": "ws-123", "createdAt": "2026-09-10T15:31:00Z"}}}
        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql), mock.patch.object(bagholder, "ORDERS_LIVE", True), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}):
            r = bagholder.place_order(self._ticket())
        self.assertTrue(r["ok"]); self.assertEqual((r["status"], r["wsOrderId"]), ("sent", "ws-123"))
        self.assertEqual(sent[0][0], "SoOrdersOrderCreate")
        self.assertEqual(sent[0][1]["input"]["externalId"], r["id"])
        row = store.get_order(r["id"])
        self.assertEqual((row["status"], row["wsOrderId"]), ("sent", "ws-123"))
        # a rejection keeps its reason on the row and comes back as the error
        def rejecting(sess, operation, variables, query=None):
            return {"soOrdersCreateOrder": {"errors": [{"code": "ORDER.insufficient_funds", "message": "Insufficient funds"}], "order": None}}
        with mock.patch.object(bagholder, "graphql", side_effect=rejecting), mock.patch.object(bagholder, "ORDERS_LIVE", True), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}):
            r2 = bagholder.place_order(self._ticket())
        self.assertFalse(r2["ok"]); self.assertIn("Insufficient funds", r2["error"])
        self.assertEqual((store.get_order(r2["id"])["status"], store.get_order(r2["id"])["error"]), ("rejected", "Insufficient funds"))
        # a session Wealthsimple refuses never sends and says so
        with mock.patch.object(bagholder, "graphql", side_effect=PermissionError()), mock.patch.object(bagholder, "ORDERS_LIVE", True), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}):
            r3 = bagholder.place_order(self._ticket())
        self.assertIn("refused the session", r3["error"])
        self.assertEqual(store.get_order(r3["id"])["status"], "failed")
        self.assertEqual(len(store.list_orders()), 3, "every attempt is a row")

    def test_the_orders_table_survives_clear_synced_data(self):
        with mock.patch.object(bagholder, "ORDERS_LIVE", False):
            r = bagholder.place_order(self._ticket())
        store.clear_synced_data(keep_journal=False, keep_market=False)
        self.assertEqual(len(store.list_orders()), 1, "what was submitted is a record of the user's own actions, never cleared with the synced rows")
        self.assertEqual(store.list_orders()[0]["id"], r["id"])


class OrdersReadBackTest(_OrdersBase):
    """Orders read back from Wealthsimple: their state, the pending feed, and cancel."""

    def test_wealthsimple_statuses_group_as_the_page_shows_them(self):
        for ws in ("NEW", "PENDING_SUBMISSION", "SUBMITTED", "PLACED", "PARTIALLY_FILLED", "CONTINGENT"):
            self.assertEqual(bagholder.app_status(ws), "pending", ws)
        self.assertEqual(bagholder.app_status("CANCEL_PENDING"), "cancelling")
        self.assertEqual(bagholder.app_status("FILLED"), "filled"); self.assertEqual(bagholder.app_status("POSTED"), "filled")
        self.assertEqual(bagholder.app_status("CANCELLED"), "cancelled"); self.assertEqual(bagholder.app_status("DELETED"), "cancelled")
        self.assertEqual(bagholder.app_status("EXPIRED"), "expired"); self.assertEqual(bagholder.app_status("REJECTED"), "rejected")
        self.assertEqual(bagholder.app_status(""), "")

    def test_a_sent_order_is_read_back_by_its_external_id_on_the_TR_branch(self):
        oid = self._sent()
        asked = []
        def fake_graphql(sess, operation, variables, query=None):
            asked.append((operation, variables))
            if operation == "FetchSoOrdersExtendedOrder":
                return {"soOrdersExtendedOrder": {"status": "FILLED", "filledQuantity": 25, "averageFilledPrice": 165.38, "submittedAtUtc": "2026-09-10T13:30:00Z", "expiredAtUtc": None, "rejectionCause": None, "timeInForce": "DAY", "submittedQuantity": 25}}
            if operation == "OrderServiceExtendedOrderFeed":
                return {"identity": {"id": "ident-1", "orderServiceExtendedOrderFeed": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
            raise AssertionError(operation)
        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t", "identity_canonical_id": "ident-1"}):
            r = bagholder.refresh_orders()
        self.assertEqual((r["read"], r["added"], r["failed"]), (1, 0, 0))
        self.assertEqual(asked[0], ("FetchSoOrdersExtendedOrder", {"branchId": "TR", "externalId": oid}))
        self.assertEqual(asked[1][1]["statuses"], list(bagholder.WS_PENDING))
        row = store.get_order(oid)
        self.assertEqual((row["status"], row["wsStatus"], row["filledQty"], row["avgFill"], row["submittedAt"]), ("filled", "FILLED", 25.0, 165.38, "2026-09-10T13:30:00Z"))
        # a filled order is not asked about again
        asked.clear()
        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t", "identity_canonical_id": "ident-1"}):
            bagholder.refresh_orders()
        self.assertEqual([a[0] for a in asked], ["OrderServiceExtendedOrderFeed"])

    def test_an_order_placed_in_wealthsimples_app_becomes_a_row_from_the_feed(self):
        node = {"id": "order-ws-placed", "orderId": "ws-9", "canonicalAccountId": "acct-tfsa", "createdAtUtc": "2026-09-10T01:00:00Z", "status": "SUBMITTED", "side": "BUY", "executionType": "LIMIT",
                "submittedQuantity": 3, "limitPrice": 1.76, "stopPrice": None, "averageFillPrice": None, "securityCurrency": "USD", "securityId": "sec-s-us", "symbol": "QNC", "security": {"id": "sec-s-us", "stock": {"symbol": "QNC", "name": "Quantum Emotion Corp"}}}
        def fake_graphql(sess, operation, variables, query=None):
            if operation == "OrderServiceExtendedOrderFeed":
                return {"identity": {"id": "ident-1", "orderServiceExtendedOrderFeed": {"edges": [{"cursor": "c1", "node": node}], "pageInfo": {"hasNextPage": False, "endCursor": "c1"}}}}
            if operation == "FetchSoOrdersExtendedOrder":
                return {"soOrdersExtendedOrder": {"status": "SUBMITTED", "timeInForce": "UNTIL_CANCEL", "submittedQuantity": 3, "limitPrice": 1.76, "securityCurrency": "USD"}}
            raise AssertionError(operation)
        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t", "identity_canonical_id": "ident-1"}):
            r = bagholder.refresh_orders()
        self.assertEqual((r["read"], r["added"]), (0, 1))
        row = store.get_order("order-ws-placed")
        self.assertEqual((row["source"], row["status"], row["symbol"], row["account"], row["side"], row["type"], row["quantity"], row["limitPrice"], row["wsOrderId"]), ("wealthsimple", "pending", "QNC", "TFSA", "BUY", "LIMIT", 3.0, 1.76, "ws-9"))
        self.assertIsNone(row["stopLoss"])
        # the next pass reads it like any live order and learns its time in force; nothing is inserted twice
        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t", "identity_canonical_id": "ident-1"}):
            r = bagholder.refresh_orders()
        self.assertEqual((r["read"], r["added"]), (1, 0))
        self.assertEqual(store.get_order("order-ws-placed")["tif"], "UNTIL_CANCEL")
        self.assertEqual(len(store.list_orders()), 1)

    def test_a_failed_read_is_counted_and_the_others_still_happen(self):
        oid = self._sent()
        def fake_graphql(sess, operation, variables, query=None):
            if operation == "FetchSoOrdersExtendedOrder":
                raise RuntimeError("FetchSoOrdersExtendedOrder: boom")
            return {"identity": {"id": "ident-1", "orderServiceExtendedOrderFeed": {"edges": [], "pageInfo": {"hasNextPage": False}}}}
        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t", "identity_canonical_id": "ident-1"}):
            r = bagholder.refresh_orders()
        self.assertEqual((r["ok"], r["failed"]), (False, 1))
        self.assertEqual(store.get_order(oid)["status"], "sent", "an unanswered read changes nothing")

    def test_cancel_needs_the_switch_and_a_live_order(self):
        oid = self._sent()
        with mock.patch.object(bagholder, "ORDERS_LIVE", False):
            self.assertIn("Orders are off", bagholder.cancel_order(oid)["error"])
        self.assertEqual(bagholder.cancel_order("nope")["error"], "No such order.")
        store.update_order(oid, {"status": "filled"})
        with mock.patch.object(bagholder, "ORDERS_LIVE", True):
            self.assertEqual(bagholder.cancel_order(oid)["error"], "That order is not open.")

    def test_cancel_goes_to_wealthsimple_by_external_id_and_the_row_says_cancelling(self):
        oid = self._sent()
        sent = []
        def fake_graphql(sess, operation, variables, query=None):
            sent.append((operation, variables))
            return {"orderServiceCancelOrder": {"externalId": oid, "errors": []}}
        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql), mock.patch.object(bagholder, "ORDERS_LIVE", True), \
             mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}), mock.patch.object(bagholder.threading, "Thread"):
            r = bagholder.cancel_order(oid)
        self.assertTrue(r["ok"]); self.assertEqual(r["status"], "cancelling")
        self.assertEqual(sent, [("SoOrdersOrderCancel", {"cancelOrderRequest": {"externalId": oid}})])
        self.assertEqual((store.get_order(oid)["status"], store.get_order(oid)["wsStatus"]), ("cancelling", "CANCEL_PENDING"))
        # a refusal leaves the row as it was
        store.update_order(oid, {"status": "pending", "wsStatus": "SUBMITTED"})
        with mock.patch.object(bagholder, "graphql", return_value={"orderServiceCancelOrder": {"externalId": oid, "errors": [{"code": "x", "message": "Too late to cancel"}]}}), \
             mock.patch.object(bagholder, "ORDERS_LIVE", True), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}):
            r = bagholder.cancel_order(oid)
        self.assertIn("Too late to cancel", r["error"])
        self.assertEqual(store.get_order(oid)["status"], "pending")

    def test_the_orders_tab_opening_kicks_a_read_unless_one_is_fresh(self):
        ran = []
        class Sync:
            def __init__(self, target=None, args=(), **kw): self.target, self.args = target, args
            def start(self): self.target(*self.args)
        with mock.patch.object(bagholder.threading, "Thread", Sync), mock.patch.object(bagholder, "refresh_orders", side_effect=lambda only_id="": ran.append(only_id)) as rf:
            with bagholder._lock:
                bagholder._state["connected"] = False
            self.assertFalse(bagholder.kick_orders_refresh(), "nothing is read while not connected")
            with bagholder._lock:
                bagholder._state["connected"] = True
            bagholder._orders_refreshed_at = ""
            self.assertTrue(bagholder.orders_payload(kick=True)["ok"])
            self.assertEqual(ran, [""], "the list's first request reads everything")
            bagholder._orders_refreshed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.assertFalse(bagholder.kick_orders_refresh(), "a read younger than the loop's tick is fresh enough")
            bagholder._orders_refreshed_at = "2026-01-01T00:00:00Z"
            self.assertTrue(bagholder.kick_orders_refresh())
        with bagholder._lock:
            bagholder._state["connected"] = False
        bagholder._orders_refreshed_at = ""

    def test_one_orders_read_after_a_send_does_not_count_as_a_check(self):
        oid = self._sent()
        bagholder._orders_refreshed_at = ""
        with mock.patch.object(bagholder, "graphql", return_value={"soOrdersExtendedOrder": {"status": "SUBMITTED"}}), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}):
            bagholder.refresh_orders(only_id=oid)
        self.assertEqual(bagholder._orders_refreshed_at, "")
        self.assertEqual(store.get_order(oid)["status"], "pending")


class _EngineBase(_OrdersBase):
    """A book with a filled-able entry and a fake Wealthsimple that takes, cancels and reads orders."""

    def setUp(self):
        super().setUp()
        store.replace_balances([{"accountId": "acct-margin", "securityId": "sec-s-us", "quantity": 25}])
        store.set_meta("balances_read_at", "")
        bagholder._stop_allowed_cache.clear()
        bagholder._bracket_said.clear()
        self.sent = []
        self.rejections = []

    def _graphql(self, sess, operation, variables, query=None):
        self.sent.append((operation, variables))
        if operation == "SoOrdersOrderCreate":
            if self.rejections:
                return {"soOrdersCreateOrder": {"errors": [{"code": "x", "message": self.rejections.pop(0)}], "order": None}}
            return {"soOrdersCreateOrder": {"errors": [], "order": {"orderId": "ws-" + str(len(self.sent)), "createdAt": "2026-09-10T13:30:00Z"}}}
        if operation == "SoOrdersOrderCancel":
            return {"orderServiceCancelOrder": {"externalId": variables["cancelOrderRequest"]["externalId"], "errors": []}}
        if operation == "FetchSecurityMarketData":
            return {"security": {"id": variables["id"], "allowedOrderSubtypes": ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"], "marginRates": {"clientMarginRate": 0.3}}}
        if operation == "FetchSoOrdersExtendedOrder":
            row = store.get_order(variables["externalId"]) or {}
            ws = {"sent": "SUBMITTED", "pending": "SUBMITTED", "cancelling": "CANCEL_PENDING", "filled": "FILLED", "cancelled": "CANCELLED", "expired": "EXPIRED", "rejected": "REJECTED"}.get(row.get("status"), "SUBMITTED")
            return {"soOrdersExtendedOrder": {"status": ws, "filledQuantity": row.get("filledQty"), "averageFilledPrice": row.get("avgFill"), "submittedQuantity": row.get("quantity")}}
        raise AssertionError(operation)

    def _live(self):
        return [mock.patch.object(bagholder, "graphql", side_effect=self._graphql), mock.patch.object(bagholder, "ORDERS_LIVE", True),
                mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}), mock.patch.object(bagholder.threading, "Thread")]

    def _entry(self, **over):
        with self._live()[0], self._live()[1], self._live()[2], self._live()[3]:
            r = bagholder.place_order(self._ticket(**over))
        self.assertTrue(r["ok"], r)
        return r["id"], store.get_bracket(r["bracketId"])

    def _tick(self, quote=None):
        with self._live()[0], self._live()[1], self._live()[2], self._live()[3]:
            return bagholder.bracket_tick({"sec-s-us": quote} if quote else {})

    def _q(self, last, bid=None, status="OPEN"):
        return {"last": last, "bid": bid if bid is not None else last, "ask": last + 0.02, "marketStatus": status}

class BracketEngineTest(_EngineBase):
    """The stop loss and take profit after the fill: arming, watching, firing, ending."""

    def test_a_ticket_with_brackets_makes_a_waiting_bracket(self):
        oid, b = self._entry()
        self.assertEqual((b["orderId"], b["status"], b["slKind"], b["slPrice"], b["tpPrice"], b["quantity"], b["tif"]), (oid, "waiting", "stop", 157.13, 181.94, 25.0, "DAY"))
        self.assertIsNone(store.bracket_for_order("nope"))
        self._tick()
        self.assertEqual(store.get_bracket(b["id"])["status"], "waiting", "an unfilled entry leaves the bracket waiting")

    def test_the_fill_arms_the_bracket_and_places_the_stop_as_wealthsimples_own_order(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25, "avgFill": 165.38})
        self.sent.clear()
        self._tick()
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["slMode"], b["slNative"]), ("armed", "native", True))
        self.assertTrue(b["slOrderId"].startswith("order-"))
        create = [v for op, v in self.sent if op == "SoOrdersOrderCreate"]
        self.assertEqual(len(create), 1)
        inp = create[0]["input"]
        self.assertEqual({k: v for k, v in inp.items() if k != "externalId"},
                         {"canonicalAccountId": "acct-margin", "executionType": "STOP", "orderType": "SELL_QUANTITY", "quantity": 25.0, "securityId": "sec-s-us", "timeInForce": "DAY", "stopPrice": 157.13})
        stop = store.get_order(b["slOrderId"])
        self.assertEqual((stop["role"], stop["parentId"], stop["side"], stop["type"], stop["status"]), ("stop", oid, "SELL", "STOP", "sent"))
        # armed and resting: a quote below the target changes nothing
        self.sent.clear()
        self._tick(self._q(170.0))
        self.assertEqual([op for op, _ in self.sent], [])

    def test_a_partial_fill_at_the_end_arms_for_what_filled(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "cancelled", "filledQty": 10})
        self._tick()
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["quantity"]), ("armed", 10.0))
        self.assertEqual(store.get_order(b["slOrderId"])["quantity"], 10.0)

    def test_an_entry_that_never_filled_ends_the_bracket(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "cancelled"})
        self._tick()
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["outcome"]), ("cancelled", "entry cancelled"))

    def test_the_target_cancels_the_stop_then_places_the_limit_sell(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()
        b = store.get_bracket(b["id"])
        self.sent.clear()
        self._tick(self._q(182.0, bid=181.95))
        b = store.get_bracket(b["id"])
        self.assertEqual(b["status"], "firing")
        self.assertEqual([op for op, _ in self.sent], ["SoOrdersOrderCancel"], "the stop's cancel goes first, alone")
        self.assertEqual(store.get_order(b["slOrderId"])["status"], "cancelling")
        self.sent.clear()
        self._tick(self._q(182.0, bid=181.95))
        self.assertEqual([op for op, _ in self.sent], ["FetchSoOrdersExtendedOrder"], "the stop is read back every check; nothing is written until Wealthsimple confirms the cancel")
        store.update_order(b["slOrderId"], {"status": "cancelled", "wsStatus": "CANCELLED"})
        self._tick(self._q(182.0, bid=181.95))
        b = store.get_bracket(b["id"])
        self.assertEqual(b["status"], "target_placed")
        create = [v["input"] for op, v in self.sent if op == "SoOrdersOrderCreate"]
        self.assertEqual((create[0]["executionType"], create[0]["orderType"], create[0]["limitPrice"], create[0]["quantity"]), ("LIMIT", "SELL_QUANTITY", 181.94, 25.0))
        tp = store.get_order(b["tpOrderId"])
        self.assertEqual((tp["role"], tp["parentId"]), ("target", oid))
        store.update_order(b["tpOrderId"], {"status": "filled", "filledQty": 25, "avgFill": 181.94})
        self._tick()
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["outcome"]), ("done", "target"))

    def test_the_bid_not_the_last_decides_the_target(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()
        self.sent.clear()
        self._tick(self._q(182.0, bid=181.50))
        self.assertEqual(store.get_bracket(b["id"])["status"], "armed")
        self._tick(self._q(181.0, bid=181.94))
        self.assertEqual(store.get_bracket(b["id"])["status"], "firing")

    def test_nothing_fires_while_the_market_is_closed(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()
        self.sent.clear()
        self._tick(self._q(190.0, status="CLOSED"))
        self.assertEqual(self.sent, [])
        self.assertEqual(store.get_bracket(b["id"])["status"], "armed")

    def test_the_stop_filling_ends_the_bracket(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()
        b = store.get_bracket(b["id"])
        store.update_order(b["slOrderId"], {"status": "filled", "filledQty": 25, "avgFill": 157.0})
        self._tick()
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["outcome"]), ("done", "stopped"))

    def test_a_stop_cancelled_by_hand_leaves_the_target_watched(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()
        b = store.get_bracket(b["id"])
        store.update_order(b["slOrderId"], {"status": "cancelled"})
        self._tick()
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["slKind"], b["slOrderId"]), ("armed", "", ""))
        self.assertIn("stop cancelled at Wealthsimple", b["error"])
        self.sent.clear()
        self._tick(self._q(182.0))
        self.assertEqual(store.get_bracket(b["id"])["status"], "target_placed", "no stop to cancel: the limit sell goes at once")

    def test_a_watched_stop_fires_as_a_market_sell_when_wealthsimple_takes_no_stop_order(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        with mock.patch.object(bagholder, "_stop_allowed", return_value=False):
            self._tick()
            b = store.get_bracket(b["id"])
            self.assertEqual((b["status"], b["slMode"], b["slOrderId"]), ("armed", "watched", ""))
            self.sent.clear()
            self._tick(self._q(158.0, bid=157.90))
            self.assertEqual(self.sent, [])
            self._tick(self._q(157.2, bid=157.10))
        b = store.get_bracket(b["id"])
        self.assertEqual(b["status"], "firing")
        create = [v["input"] for op, v in self.sent if op == "SoOrdersOrderCreate"]
        self.assertEqual((create[0]["executionType"], create[0]["orderType"]), ("MARKET", "SELL_QUANTITY"))
        self.assertNotIn("stopPrice", create[0])
        store.update_order(b["slOrderId"], {"status": "filled", "filledQty": 25})
        self._tick()
        self.assertEqual(store.get_bracket(b["id"])["outcome"], "stopped")

    def test_a_trailing_stop_follows_the_high_by_cancel_and_replace_no_more_than_once_a_minute(self):
        oid, b = self._entry(stopLoss={"kind": "trail", "trail": 5, "trailUnit": "pct"})
        store.update_order(oid, {"status": "filled", "filledQty": 25, "avgFill": 165.4})
        self._tick()
        b = store.get_bracket(b["id"])
        first_stop = b["slOrderId"]
        self.assertEqual(b["slKind"], "trail")
        self.sent.clear()
        self._tick(self._q(180.0))
        b = store.get_bracket(b["id"])
        self.assertEqual(b["highWater"], 180.0)
        self.assertEqual(b["slPrice"], 171.0, "the high less five percent")
        self.assertEqual([op for op, _ in self.sent], ["SoOrdersOrderCancel"], "the old stop is cancelled; the new one waits for the confirmation")
        self.assertEqual(b["slOrderId"], "")
        store.update_order(first_stop, {"status": "cancelled"})
        self.sent.clear()
        self._tick(self._q(180.0))
        b = store.get_bracket(b["id"])
        create = [v["input"] for op, v in self.sent if op == "SoOrdersOrderCreate"]
        self.assertEqual((create[0]["executionType"], create[0]["stopPrice"]), ("STOP", 171.0))
        self.assertNotEqual(b["slOrderId"], first_stop)
        # a rise below half a percent does not move it again; a lower high never lowers it
        self.sent.clear()
        self._tick(self._q(180.5))
        self.assertEqual(self.sent, [])
        self.assertEqual(store.get_bracket(b["id"])["slPrice"], 171.0)
        self._tick(self._q(171.5))
        self.assertEqual(store.get_bracket(b["id"])["slPrice"], 171.0, "a lower high never lowers the stop")
        # a rise past the step moves it at once
        self._tick(self._q(182.0))
        self.assertEqual(store.get_bracket(b["id"])["slPrice"], 172.9)

    def test_a_position_sold_elsewhere_ends_the_bracket_and_cancels_its_orders(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()
        b = store.get_bracket(b["id"])
        store.replace_balances([{"accountId": "acct-margin", "securityId": "sec-other", "quantity": 1}])
        store.set_meta("balances_read_at", "2020-01-01T00:00:00Z")
        self._tick()
        self.assertEqual(store.get_bracket(b["id"])["status"], "armed", "a balances read older than the arming proves nothing")
        store.set_meta("balances_read_at", "2099-01-01T00:00:00Z")
        self._tick()
        self.assertEqual(store.get_bracket(b["id"])["status"], "armed", "a read that never showed the position held proves nothing: Wealthsimple's balances lag a fill")
        # the position shows up in a read, then disappears: still nothing within ten minutes of arming
        store.replace_balances([{"accountId": "acct-margin", "securityId": "sec-s-us", "quantity": 25}])
        self._tick()
        self.assertTrue(store.get_bracket(b["id"])["seenHeld"])
        store.replace_balances([{"accountId": "acct-margin", "securityId": "sec-other", "quantity": 1}])
        self._tick()
        self.assertEqual(store.get_bracket(b["id"])["status"], "armed", "too soon after arming")
        store.update_bracket(b["id"], {"armedAt": "2020-01-01T00:00:00Z"})
        self.sent.clear()
        self._tick()
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["outcome"]), ("cancelled", "position closed elsewhere"))
        self.assertEqual([op for op, _ in self.sent], ["SoOrdersOrderCancel"])

    def test_a_rejected_exit_is_tried_again_spaced_out_then_the_bracket_fails_loudly(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self.rejections = ["Market closed"] * 5
        self._tick()
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["attempts"]), ("armed", 1))
        self.assertIn("Market closed", b["error"])
        self.sent.clear()
        self._tick()
        self.assertEqual([op for op, _ in self.sent if op == "SoOrdersOrderCreate"], [], "no second try within the minute")
        # each later try comes only after its wait: a minute, five, fifteen, an hour
        for n, wait in enumerate((60, 300, 900, 3600), start=2):
            with mock.patch.object(store, "_now_iso", return_value="2020-01-01T00:00:00Z"):
                store.update_bracket(b["id"], {"error": "Market closed"})   # the last failure, long enough ago
            self._tick()
            b = store.get_bracket(b["id"])
            self.assertEqual(b["attempts"], n, "attempt %d after %d s" % (n, wait))
        self.assertEqual(b["status"], "failed")
        self.sent.clear()
        with mock.patch.object(store, "_now_iso", return_value="2020-01-01T00:00:00Z"):
            store.update_bracket(b["id"], {"error": "Market closed"})
        self._tick()
        self.assertEqual([op for op, _ in self.sent if op == "SoOrdersOrderCreate"], [], "a failed bracket is left alone")

    def test_with_orders_off_nothing_is_placed_and_the_line_is_printed_once(self):
        with mock.patch.object(bagholder, "ORDERS_LIVE", False):
            r = bagholder.place_order(self._ticket())
        oid, bid = r["id"], r["bracketId"]
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        err = io.StringIO()
        with mock.patch.object(bagholder, "graphql", side_effect=self._graphql), mock.patch.object(bagholder, "ORDERS_LIVE", False), \
             mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}), mock.patch.object(bagholder.sys, "stderr", err):
            bagholder.bracket_tick({}); bagholder.bracket_tick({})
        b = store.get_bracket(bid)
        self.assertEqual((b["status"], b["slOrderId"]), ("armed", ""))
        self.assertEqual([op for op, _ in self.sent if op == "SoOrdersOrderCreate"], [])
        self.assertEqual(err.getvalue().count("orders are off, not placed"), 1)

    def test_cancel_bracket_cancels_its_resting_orders_and_stops_watching(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()
        b = store.get_bracket(b["id"])
        self.sent.clear()
        with self._live()[0], self._live()[1], self._live()[2], self._live()[3]:
            r = bagholder.cancel_bracket(b["id"])
        self.assertTrue(r["ok"])
        self.assertEqual([op for op, _ in self.sent], ["SoOrdersOrderCancel"])
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["outcome"]), ("cancelled", "cancelled by the user"))
        self.assertEqual(store.get_order(oid)["status"], "filled", "the entry is not touched")
        self.assertIn("not live", bagholder.cancel_bracket(b["id"])["error"])
        self.assertEqual(bagholder.cancel_bracket("nope")["error"], "No such bracket.")
        self.assertEqual([x["id"] for x in bagholder.orders_payload()["brackets"]], [b["id"]])


class OrdersPanelTest(_EngineBase):
    """Edit on an open order, Adjust and Remove on a bracket's legs, the header's count."""

    def test_open_orders_are_counted_for_the_header_badge(self):
        oid, b = self._entry()
        self.assertEqual(bagholder.open_orders_count(), 1)
        self.assertEqual(bagholder.status_payload()["openOrders"], 1)
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()   # the stop is placed: an exit row, not counted
        self.assertEqual(bagholder.open_orders_count(), 0)

    def test_edit_sends_wealthsimples_modify_with_the_new_price_and_quantity(self):
        oid, b = self._entry()
        sent = []
        def fake(sess, operation, variables, query=None):
            sent.append((operation, variables))
            return {"soOrdersModifyOrder": {"errors": []}}
        with mock.patch.object(bagholder, "graphql", side_effect=fake), mock.patch.object(bagholder, "ORDERS_LIVE", True), \
             mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}), mock.patch.object(bagholder.threading, "Thread"):
            r = bagholder.modify_order(oid, 30, 164.0)
        self.assertTrue(r["ok"], r)
        self.assertEqual(sent, [("SoOrdersOrderModify", {"input": {"externalId": oid, "newLimitPrice": 164.0, "newQuantity": 30.0}})])
        row = store.get_order(oid)
        self.assertEqual((row["quantity"], row["limitPrice"]), (30.0, 164.0))
        self.assertEqual(store.get_bracket(b["id"])["quantity"], 30.0, "a waiting bracket follows the entry's quantity")
        # only what changed is sent; nothing changed sends nothing
        sent.clear()
        with mock.patch.object(bagholder, "graphql", side_effect=fake), mock.patch.object(bagholder, "ORDERS_LIVE", True), \
             mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}), mock.patch.object(bagholder.threading, "Thread"):
            self.assertTrue(bagholder.modify_order(oid, 30, 165.0)["ok"])
            self.assertEqual(sent[-1][1]["input"], {"externalId": oid, "newLimitPrice": 165.0})
            self.assertTrue(bagholder.modify_order(oid, 30, 165.0).get("unchanged"))
        # refusals and limits
        self.assertIn("more than zero", bagholder.modify_order(oid, 0, 165.0)["error"])
        self.assertEqual(bagholder.modify_order("nope", 1, 1)["error"], "No such order.")
        with mock.patch.object(bagholder, "graphql", return_value={"soOrdersModifyOrder": {"errors": [{"code": "x", "message": "Too late"}]}}), mock.patch.object(bagholder, "ORDERS_LIVE", True), \
             mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t"}):
            self.assertIn("Too late", bagholder.modify_order(oid, 31, 165.0)["error"])
        self.assertEqual(store.get_order(oid)["quantity"], 30.0, "a refused change changes nothing")
        store.update_order(oid, {"status": "filled"})
        self.assertIn("not open", bagholder.modify_order(oid, 31, 165.0)["error"])

    def test_adjusting_a_resting_stop_cancels_it_and_the_engine_places_the_new_level(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()
        b = store.get_bracket(b["id"])
        first = b["slOrderId"]
        self.sent.clear()
        with self._live()[0], self._live()[1], self._live()[2], self._live()[3]:
            r = bagholder.adjust_bracket(b["id"], "sl", price=160.0)
        self.assertTrue(r["ok"], r)
        self.assertEqual([op for op, _ in self.sent], ["SoOrdersOrderCancel"])
        b = store.get_bracket(b["id"])
        self.assertEqual((b["slPrice"], b["slOrderId"], b["status"]), (160.0, "", "armed"))
        store.update_order(first, {"status": "cancelled"})
        self.sent.clear()
        self._tick()
        create = [v["input"] for op, v in self.sent if op == "SoOrdersOrderCreate"]
        self.assertEqual((create[0]["executionType"], create[0]["stopPrice"]), ("STOP", 160.0))

    def test_adjusting_the_target_and_a_trailing_stop(self):
        oid, b = self._entry(stopLoss={"kind": "trail", "trail": 5, "trailUnit": "pct"})
        store.update_order(oid, {"status": "filled", "filledQty": 25, "avgFill": 165.4})
        self._tick()
        b = store.get_bracket(b["id"])
        with self._live()[0], self._live()[1], self._live()[2], self._live()[3]:
            self.assertTrue(bagholder.adjust_bracket(b["id"], "tp", price=190.0)["ok"])
            self.assertTrue(bagholder.adjust_bracket(b["id"], "sl", trail=10)["ok"])
        b = store.get_bracket(b["id"])
        self.assertEqual(b["tpPrice"], 190.0)
        self.assertEqual((b["slTrail"], b["slPrice"]), (10.0, 148.86), "ten percent under the high of 165.40")
        with self._live()[0], self._live()[1], self._live()[2], self._live()[3]:
            self.assertIn("required", bagholder.adjust_bracket(b["id"], "tp", price=0)["error"])
            self.assertIn("Which leg", bagholder.adjust_bracket(b["id"], "x", price=1)["error"])
            self.assertEqual(bagholder.adjust_bracket("nope", "tp", price=1)["error"], "No such bracket.")

    def test_a_placed_target_moved_is_cancelled_and_watched_again(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()
        b = store.get_bracket(b["id"])
        store.update_bracket(b["id"], {"slKind": "", "slOrderId": ""})   # no stop: the target goes straight out
        self._tick(self._q(182.0, bid=181.95))
        b = store.get_bracket(b["id"])
        self.assertEqual(b["status"], "target_placed")
        tp = b["tpOrderId"]
        self.sent.clear()
        with self._live()[0], self._live()[1], self._live()[2], self._live()[3]:
            self.assertTrue(bagholder.adjust_bracket(b["id"], "tp", price=185.0)["ok"])
        self.assertEqual([op for op, _ in self.sent], ["SoOrdersOrderCancel"])
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["tpPrice"], b["tpOrderId"]), ("armed", 185.0, ""))
        self.assertEqual(store.get_order(tp)["status"], "cancelling")

    def test_removing_a_leg_and_then_the_other_ends_the_bracket(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()
        b = store.get_bracket(b["id"])
        self.sent.clear()
        with self._live()[0], self._live()[1], self._live()[2], self._live()[3]:
            self.assertTrue(bagholder.adjust_bracket(b["id"], "sl", remove=True)["ok"])
        self.assertEqual([op for op, _ in self.sent], ["SoOrdersOrderCancel"], "the resting stop is cancelled")
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["slKind"], b["slOrderId"]), ("armed", "", ""))
        with self._live()[0], self._live()[1], self._live()[2], self._live()[3]:
            self.assertTrue(bagholder.adjust_bracket(b["id"], "tp", remove=True)["ok"])
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["outcome"], b["tpPrice"]), ("cancelled", "both legs removed", None))


class FeedMatchingTest(_OrdersBase):
    """An order Bagholder sent is never duplicated from Wealthsimple's pending list."""

    def test_the_feed_matches_bagholders_order_by_either_id(self):
        oid = self._sent()   # stored with Wealthsimple's order id ws-1
        node = {"id": "order-some-other-id", "orderId": "ws-1", "canonicalAccountId": "acct-margin", "createdAtUtc": "2026-09-10T01:00:00Z", "status": "SUBMITTED", "side": "BUY", "executionType": "LIMIT",
                "submittedQuantity": 25, "limitPrice": 165.4, "securityCurrency": "USD", "securityId": "sec-s-us", "symbol": "QNC", "security": {"id": "sec-s-us", "stock": {"symbol": "QNC", "name": "Quantum Emotion Corp"}}}
        def fake_graphql(sess, operation, variables, query=None):
            if operation == "OrderServiceExtendedOrderFeed":
                return {"identity": {"id": "ident-1", "orderServiceExtendedOrderFeed": {"edges": [{"cursor": "c1", "node": node}, {"cursor": "c2", "node": dict(node, id=oid, orderId="ws-1")}], "pageInfo": {"hasNextPage": False}}}}
            if operation == "FetchSoOrdersExtendedOrder":
                return {"soOrdersExtendedOrder": {"status": "SUBMITTED"}}
            raise AssertionError(operation)
        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t", "identity_canonical_id": "ident-1"}):
            r = bagholder.refresh_orders()
        self.assertEqual(r["added"], 0, "the same order under Wealthsimple's id, or under its own external id, is not a new row")
        self.assertEqual(len(store.list_orders()), 1)

    def test_an_option_order_from_the_feed_is_named_by_its_contract(self):
        store.apply_wealthsimple_mapped([bagholder.map_activity(_ws_item(canonicalId="ws-opt-1", type="OPTIONS_BUY", subType="BUYTOOPEN", assetSymbol="QNC 20NOV26 3.00 CALL", assetQuantity=5, amount=-150, occurredAt="2026-08-05T16:12:17.268Z", securityId="sec-o-1"))])
        node = {"id": "order-opt", "orderId": "ws-7", "canonicalAccountId": "acct-tfsa", "createdAtUtc": "2026-08-05T16:16:16Z", "status": "SUBMITTED", "side": "SELL", "executionType": "LIMIT",
                "submittedQuantity": 40, "limitPrice": 0.25, "securityCurrency": "USD", "securityId": "sec-o-1", "symbol": "QNC", "security": {"id": "sec-o-1", "stock": {"symbol": "QNC", "name": "Quantum Emotion Corp"}}}
        def fake_graphql(sess, operation, variables, query=None):
            if operation == "OrderServiceExtendedOrderFeed":
                return {"identity": {"id": "ident-1", "orderServiceExtendedOrderFeed": {"edges": [{"cursor": "c1", "node": node}], "pageInfo": {"hasNextPage": False}}}}
            if operation == "FetchSoOrdersExtendedOrder":
                return {"soOrdersExtendedOrder": {"status": "SUBMITTED", "timeInForce": "UNTIL_CANCEL"}}
            raise AssertionError(operation)
        with mock.patch.object(bagholder, "graphql", side_effect=fake_graphql), mock.patch.object(bagholder, "_ticket_session", return_value={"access_token": "t", "identity_canonical_id": "ident-1"}):
            bagholder.refresh_orders()
        row = store.get_order("order-opt")
        self.assertEqual(row["symbol"], "QNC 20NOV26 3.00 CALL", "the book's name for the contract, not the underlying the feed gives")
        self.assertEqual((row["side"], row["quantity"], row["limitPrice"], row["account"]), ("SELL", 40.0, 0.25, "TFSA"))


class OrderTickTest(_OrdersBase):
    """A price Wealthsimple accepts: two decimals from a dollar, four below; a quote can carry more."""

    def test_prices_are_rounded_to_the_tick_before_they_are_sent(self):
        self.assertEqual(bagholder.order_tick(1.736), 1.74)
        self.assertEqual(bagholder.order_tick(0.2537), 0.2537)
        self.assertEqual(bagholder.order_tick(0.25371), 0.2537)
        self.assertIsNone(bagholder.order_tick(None))
        row, req, err = bagholder.order_request(self._ticket(limitPrice=1.736, stopLoss={"kind": "stop", "price": 1.6512}, takeProfit={"price": 1.9139}))
        self.assertEqual(err, "")
        self.assertEqual(req["limitPrice"], 1.74)
        self.assertEqual((row["stopLoss"]["price"], row["takeProfit"]["price"]), (1.65, 1.91))
        _, req, _ = bagholder.order_request(self._ticket(type="STOP_LIMIT", limitPrice=0.98765, stopPrice=1.005))
        self.assertEqual((req["limitPrice"], req["stopPrice"]), (0.9877, 1.0))


class StopExpiryTest(_EngineBase):
    def test_a_day_stop_that_expires_is_placed_again(self):
        oid, b = self._entry()
        store.update_order(oid, {"status": "filled", "filledQty": 25})
        self._tick()
        b = store.get_bracket(b["id"])
        first = b["slOrderId"]
        store.update_order(first, {"status": "expired", "wsStatus": "EXPIRED"})
        self.sent.clear()
        self._tick()
        b = store.get_bracket(b["id"])
        self.assertEqual((b["status"], b["slKind"], b["slPrice"]), ("armed", "stop", 157.13), "the leg stays")
        create = [v["input"] for op, v in self.sent if op == "SoOrdersOrderCreate"]
        self.assertEqual((create[0]["executionType"], create[0]["stopPrice"]), ("STOP", 157.13), "a new stop at the same level")
        self.assertNotEqual(b["slOrderId"], first)
        # a stop cancelled by hand is different: the leg is dropped
        store.update_order(b["slOrderId"], {"status": "cancelled"})
        self._tick()
        self.assertEqual(store.get_bracket(b["id"])["slKind"], "")
