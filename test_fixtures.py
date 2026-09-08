"""The shared model cases in fixtures/cases, run through the Python model: the
same files a Swift or Kotlin implementation runs through its own model, so the
three cannot disagree without a failing test. Regenerate with
fixtures/make_fixtures.py after an intended model change and review the diff."""
import glob
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures"))
import model  # noqa: E402
import make_fixtures  # noqa: E402


class FixtureTest(unittest.TestCase):
    def test_every_case_matches(self):
        paths = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "cases", "*.json")))
        self.assertTrue(paths, "no cases found")
        for path in paths:
            with open(path) as f:
                doc = json.load(f)
            base = model.build_base(doc["snapshot"], doc["market"], {}, today=doc["today"])
            view = model.build_view(base, doc["filters"])
            got = make_fixtures.rounded({
                "kpi": make_fixtures.pick(view["kpi"], make_fixtures.KPI_KEYS),
                "trades": [dict(make_fixtures.pick(t, make_fixtures.TRADE_KEYS), fills=[x["sub"] for x in sorted(t["fills"], key=lambda x: x["when"])])
                           for t in sorted(view["trades"], key=lambda t: (t["entryDate"], t["exitDate"], t["symbol"]))],
                "positions": [make_fixtures.pick(p, make_fixtures.POSITION_KEYS) for p in sorted(view["positions"], key=lambda p: p["symbol"])],
            })
            if "cashflowHoldings" in doc["expect"]:
                got["cashflowHoldings"] = make_fixtures.rounded([make_fixtures.pick(h, make_fixtures.HOLDING_KEYS) for h in sorted(view["cashflow"]["holdings"], key=lambda h: h["symbol"])])
            self.assertEqual(got, doc["expect"], os.path.basename(path))

    def test_cases_are_current(self):
        """The files on disk are what the generator writes now: a model change means regenerating them on purpose."""
        for name, case in make_fixtures.CASES.items():
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "cases", name + ".json")) as f:
                self.assertEqual(json.load(f)["expect"], make_fixtures.expect(case), name)


if __name__ == "__main__":
    unittest.main()
