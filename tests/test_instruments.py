"""Indices, futures, rates and currency pairs the watchlist can follow, and the bare-ticker convention."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import bagholder
import exposure
import instruments
import market
import model
import store


class SearchTest(unittest.TestCase):
    def test_aliases_find_what_people_type(self):
        self.assertEqual([r["symbol"] for r in instruments.search("WTI")][:1], ["CL"])
        self.assertEqual([r["symbol"] for r in instruments.search("crude")][:2], ["CL", "BZ"])
        self.assertEqual([r["symbol"] for r in instruments.search("NDX")][:1], ["NDX"])
        self.assertEqual([r["symbol"] for r in instruments.search("nasdaq 100")][:1], ["NDX"])
        self.assertEqual([r["symbol"] for r in instruments.search("VIX")][:1], ["VIX"])
        self.assertEqual([r["symbol"] for r in instruments.search("volatility")][:1], ["VIX"])
        self.assertEqual([r["symbol"] for r in instruments.search("gold")][:1], ["GC"])
        self.assertEqual(instruments.search("ZZZZ"), [])
        self.assertEqual(instruments.search("V"), [], "a single letter is not a search for every V")
        self.assertEqual([r["symbol"] for r in instruments.search("VI")][:1], ["VIX"])
        row = instruments.search("VIX")[0]
        self.assertEqual((row["name"], row["exchange"], row["currency"], row["kind"]), ("CBOE Volatility Index", "Index", "USD", "Index"))

    def test_an_alias_hit_ranks_as_the_exact_match_it_is(self):
        rows = bagholder.rank_search("WTI", instruments.search("WTI") + [{"symbol": "WTI", "name": "W&T Offshore", "exchange": "NYSE", "currency": "USD"}, {"symbol": "WTIB", "name": "USCF", "exchange": "NYSE", "currency": "USD"}])
        self.assertEqual([(r["symbol"], r["exchange"]) for r in rows][:3], [("CL", "NYMEX"), ("WTI", "NYSE"), ("WTIB", "NYSE")])

    def test_find_by_symbol_and_venue(self):
        self.assertEqual(instruments.find("cl", "nymex")["yahoo"], "CL=F")
        self.assertIsNone(instruments.find("CL", "TSX"), "a listing with the same letters is not the future")
        self.assertIsNone(instruments.find("SHOP", "TSX"))


class QuoteTest(unittest.TestCase):
    def test_yahoo_meta_becomes_a_quote(self):
        text = '{"chart": {"result": [{"meta": {"regularMarketPrice": 99.4, "chartPreviousClose": 93.03, "currency": "USD", "shortName": "Crude Oil Oct 26", "exchangeName": "NYM"}}]}}'
        q = market.parse_yahoo_quote(text)
        self.assertEqual((q["price"], round(q["priceChange"], 2), round(q["percentChange"], 2), q["prevClose"], q["currency"], q["name"]), (99.4, 6.37, 6.85, 93.03, "USD", "Crude Oil Oct 26"))
        self.assertIsNone(market.parse_yahoo_quote('{"chart": {"result": []}}'))

    def test_an_instrument_is_quoted_from_yahoo_under_its_own_key(self):
        needing = market.quote_symbols_needing_refresh([{"symbol": "VIX", "exchange": "Index", "currency": "USD", "kind": "Instrument", "yahoo": "^VIX", "quoteKey": "VIX@INDEX"}])
        self.assertEqual(needing, [("VIX@INDEX", "yahoo_quote", "^VIX")])


class ConventionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BAGHOLDER_HOME"] = self.tmp.name
        store.set_home(self.tmp.name)
        bagholder.set_home(self.tmp.name)
        store.ensure()
        model.invalidate()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_watched_listing_is_kept_as_its_bare_ticker(self):
        with mock.patch.object(market, "refresh_quotes", return_value=0), mock.patch.object(exposure, "share_exposure", return_value={}) as se:
            r = bagholder.watch_add({"symbol": "QNC.TO", "exchange": "TSX-V", "name": "Quantum eMotion Corp", "currency": "CAD"})
            import time
            for _ in range(100):   # the background read finishes inside the mocks, not in the next test
                if se.called:
                    break
                time.sleep(0.05)
        self.assertEqual([(w["symbol"], w["exchange"]) for w in r["watchlist"]], [("QNC", "TSX-V")], "Wealthsimple's .TO is not the app's convention")
        r = bagholder.watch_remove({"symbol": "QNC.TO", "exchange": "TSX-V"})
        self.assertEqual(r["watchlist"], [], "removing by either form works")

    def test_an_instrument_takes_the_directory_name_and_a_kind(self):
        with mock.patch.object(market, "refresh_quotes", return_value=0) as rq, mock.patch.object(exposure, "share_exposure") as se:
            r = bagholder.watch_add({"symbol": "CL", "exchange": "NYMEX", "name": "", "currency": ""})
            import time
            for _ in range(50):
                if rq.called:
                    break
                time.sleep(0.05)
        self.assertEqual((r["watchlist"][0]["name"], r["watchlist"][0]["currency"]), ("Crude Oil (WTI)", "USD"))
        self.assertFalse(se.called, "a future has no sector record to read")
        base = model.base_model()
        self.assertEqual(model.watch_symbols(base), [{"symbol": "CL", "exchange": "NYMEX", "currency": "USD", "kind": "Instrument", "quoteKey": "CL@NYMEX", "yahoo": "CL=F"}])
        rows = model.watch_rows(dict(base, quotes={"CL@NYMEX": {"price": 99.4, "priceChange": 6.37, "percentChange": 6.85}}), [])
        self.assertEqual((rows[0]["sector"], rows[0]["kind"], rows[0]["last"]), ("Commodities", "Commodity", 99.4), "an instrument groups under its kind on the heatmap")
        self.assertEqual(bagholder.news_listings(), [], "no news wire for a future")


if __name__ == "__main__":
    unittest.main()
