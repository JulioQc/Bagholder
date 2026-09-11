"""News: two per-symbol wires parsed into rows, kept per listing, tagged in the model."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

import bagholder
import model
import news
import store


class ParseTest(unittest.TestCase):
    def test_tmx_items_carry_an_exact_time_and_a_page_link(self):
        data = {"data": {"news": [{"headline": "Shopify Delivers Big: 30%+ Growth Across&#xA0;GMV", "datetime": "2026-08-05T07:00:00-04:00", "source": "GlobeNewswire via QuoteMedia", "newsid": 4883675477075330},
                                  {"headline": "no id", "datetime": "2026-08-05T07:00:00-04:00"},
                                  {"headline": "bad time", "datetime": "yesterday", "newsid": 5}]}}
        rows = news.parse_tmx_news(data, "SHOP")
        self.assertEqual(rows, [{"id": "tmx:4883675477075330", "headline": "Shopify Delivers Big: 30%+ Growth Across GMV", "source": "GlobeNewswire",
                                 "url": "https://money.tmx.com/en/quote/SHOP/news/4883675477075330", "publishedAt": "2026-08-05T11:00:00Z"}])

    def test_nasdaq_items_take_their_time_from_the_age_given(self):
        now = datetime(2026, 9, 11, 15, 30, tzinfo=timezone.utc)
        data = {"data": {"rows": [{"id": 28351741, "title": "Forget AMD. Here&#39;s Who Nvidia Really Needs to Be Worried About.", "publisher": "The Motley Fool", "created": "Sep 11, 2026", "ago": "17 minutes ago", "url": "/articles/forget-amd", "primarysymbol": "avgo", "related_symbols": ["avgo|stocks", "nvda|stocks"]},
                                  {"id": 2, "title": "Two hours", "publisher": "Zacks", "created": "Sep 11, 2026", "ago": "2 hours ago", "url": "https://www.nasdaq.com/articles/two", "related_symbols": ["NVDA|stocks"]},
                                  {"id": 3, "title": "Old", "publisher": "Barchart", "created": "Sep 3, 2026", "ago": "", "url": "/articles/old", "primarysymbol": "nvda"},
                                  {"id": 4, "publisher": "no title", "related_symbols": ["nvda|stocks"]},
                                  {"id": 5, "title": "Market wrap that never names it", "publisher": "Barchart", "created": "Sep 11, 2026", "ago": "3 minutes ago", "url": "/articles/wrap", "related_symbols": ["spy|etf", "aapl|stocks"]}]}}
        rows = news.parse_nasdaq_news(data, now, "NVDA")
        self.assertEqual([(r["id"], r["headline"], r["source"], r["url"], r["publishedAt"]) for r in rows],
                         [("nasdaq:28351741", "Forget AMD. Here's Who Nvidia Really Needs to Be Worried About.", "The Motley Fool", "https://www.nasdaq.com/articles/forget-amd", "2026-09-11T15:13:00Z"),
                          ("nasdaq:2", "Two hours", "Zacks", "https://www.nasdaq.com/articles/two", "2026-09-11T13:30:00Z"),
                          ("nasdaq:3", "Old", "Barchart", "https://www.nasdaq.com/articles/old", "2026-09-03T00:00:00Z")],
                         "an item Nasdaq does not tag with the symbol is left out")

    def test_the_wire_follows_the_venue(self):
        self.assertEqual(news.source_for("SHOP", "TSX", "CAD"), "tmx")
        self.assertEqual(news.source_for("NVDA", "NASDAQ", "USD"), "nasdaq")
        self.assertEqual(news.source_for("AAPL", "", "USD"), "nasdaq")
        self.assertEqual(news.source_for("QBTC", "NEO", "CAD"), "tmx")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BAGHOLDER_HOME"] = self.tmp.name
        store.set_home(self.tmp.name)
        bagholder.set_home(self.tmp.name)
        store.ensure()
        model.invalidate()

    def tearDown(self):
        self.tmp.cleanup()

    def test_refresh_reads_only_stale_listings_and_replaces_their_rows(self):
        now = datetime(2026, 9, 11, 15, 30, tzinfo=timezone.utc)
        answers = {"SHOP": [{"id": "tmx:1", "headline": "One", "source": "GlobeNewswire", "url": "u1", "publishedAt": "2026-09-11T14:00:00Z"}],
                   "NVDA": [{"id": "nasdaq:9", "headline": "Nine", "source": "Zacks", "url": "u9", "publishedAt": "2026-09-11T15:00:00Z"}]}
        calls = []
        def fake(symbol, exchange, currency, ssl_context=None, now=None):
            calls.append(symbol)
            return ("tmx" if exchange == "TSX" else "nasdaq"), answers.get(symbol)
        listings = [("SHOP", "TSX", "CAD"), ("NVDA", "NASDAQ", "USD"), ("BROKEN", "TSX", "CAD")]
        with mock.patch.object(news, "fetch_symbol", side_effect=fake):
            self.assertEqual(news.refresh(listings, now=now), 2, "a wire that fails leaves nothing behind and is asked again next time")
            self.assertEqual(calls, ["SHOP", "NVDA", "BROKEN"])
            calls.clear()
            self.assertEqual(news.refresh(listings, now=now), 0)
            self.assertEqual(calls, ["BROKEN"], "fresh listings are not asked again within fifteen minutes")
            answers["SHOP"] = [{"id": "tmx:2", "headline": "Two", "source": "CNW", "url": "u2", "publishedAt": "2026-09-11T16:00:00Z"}]
            later = datetime(2026, 9, 11, 16, 0, tzinfo=timezone.utc)
            news.refresh(listings, now=later)
        rows = store.snapshot()["news"]
        self.assertEqual([(r["id"], r["symbol"], r["wire"]) for r in rows], [("tmx:2", "SHOP", "CNW"), ("nasdaq:9", "NVDA", "Zacks")], "newest first; a listing's rows are replaced by its wire's latest")
        store.forget_news("SHOP", "TSX")
        self.assertEqual([r["id"] for r in store.snapshot()["news"]], ["nasdaq:9"])
        self.assertEqual(news.stale([("SHOP", "TSX", "CAD")], now=later), [("SHOP", "TSX", "CAD")], "forgotten means stale")

    def test_trim_keeps_the_newest(self):
        store.replace_news("A", "TSX", "tmx", [{"id": "tmx:%d" % i, "headline": str(i), "source": "", "url": "", "publishedAt": "2026-09-%02dT00:00:00Z" % i} for i in range(1, 6)])
        store.trim_news(2)
        self.assertEqual([r["id"] for r in store.snapshot()["news"]], ["tmx:5", "tmx:4"])


class ModelTest(unittest.TestCase):
    def test_rows_are_tagged_with_what_the_book_holds_or_watches(self):
        base = {"news": [{"id": "tmx:1", "symbol": "SHOP", "exchange": "TSX", "wire": "GlobeNewswire", "headline": "One", "url": "u1", "publishedAt": "2026-09-11T14:00:00Z"},
                         {"id": "tmx:1", "symbol": "HHIS", "exchange": "TSX", "wire": "GlobeNewswire", "headline": "One", "url": "u1", "publishedAt": "2026-09-11T14:00:00Z"},
                         {"id": "nasdaq:9", "symbol": "NVDA", "exchange": "NASDAQ", "wire": "Zacks", "headline": "Nine", "url": "u9", "publishedAt": "2026-09-11T15:00:00Z"}]}
        positions = [{"id": "p1", "symbol": "HHIS", "exchange": "TSX", "percentChange": 0.6}]
        watch = [{"symbol": "SHOP", "exchange": "TSX", "percentChange": 3.28}, {"symbol": "NVDA", "exchange": "NASDAQ", "percentChange": None}]
        rows = model.news_rows(base, positions, watch)
        self.assertEqual([(r["id"], [(t["symbol"], t["held"], t["watched"], t["percentChange"], t["positionId"]) for t in r["tags"]]) for r in rows],
                         [("nasdaq:9", [("NVDA", False, True, None, None)]), ("tmx:1", [("SHOP", False, True, 3.28, None), ("HHIS", True, False, 0.6, "p1")])],
                         "newest first; an item two listings share is one row with both tags")

    def test_the_books_form_and_the_bare_ticker_are_one_listing(self):
        base = {"news": [{"id": "tmx:7", "symbol": "QNC.TO", "exchange": "TSX-V", "wire": "TMX Newsfile", "headline": "Seven", "url": "u7", "publishedAt": "2026-09-08T13:00:00Z"},
                         {"id": "tmx:7", "symbol": "QNC", "exchange": "TSX-V", "wire": "TMX Newsfile", "headline": "Seven", "url": "u7", "publishedAt": "2026-09-08T13:00:00Z"}]}
        positions = [{"id": "p2", "symbol": "QNC.TO", "exchange": "TSX-V", "percentChange": -1.67}]
        watch = [{"symbol": "QNC", "exchange": "TSX-V", "percentChange": -1.67}]
        rows = model.news_rows(base, positions, watch)
        self.assertEqual([(t["symbol"], t["held"], t["watched"], t["percentChange"], t["positionId"]) for t in rows[0]["tags"]], [("QNC", True, True, -1.67, "p2")], "one tag, held and watched, the bare ticker")


if __name__ == "__main__":
    unittest.main()
