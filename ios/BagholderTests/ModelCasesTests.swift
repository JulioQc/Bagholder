import XCTest
@testable import Bagholder

/// The shared model cases in ../../fixtures/cases, run through the Swift model.
/// The same files run through the Python model (test_fixtures.py); a rule
/// changed in one place fails here. fixtures/README.md describes the format:
/// `expect` holds the trades, KPIs, positions and, when the case has a
/// dividend row, the Cashflow holdings and tiles, floats rounded to six places.
final class ModelCasesTests: XCTestCase {
    static let casesDir: URL = {
        var u = URL(fileURLWithPath: #filePath)
        for _ in 0..<3 { u.deleteLastPathComponent() }   // BagholderTests -> ios -> repo root
        return u.appendingPathComponent("fixtures/cases")
    }()

    // MARK: reading a case

    func str(_ d: [String: Any], _ k: String) -> String { (d[k] as? String) ?? "" }
    func num(_ d: [String: Any], _ k: String) -> Double { (d[k] as? NSNumber)?.doubleValue ?? 0 }

    func activity(_ d: [String: Any]) -> BHAct {
        let a = BHAct()
        a.id = str(d, "id"); a.occurredAt = str(d, "occurredAt"); a.transactionDate = str(d, "transactionDate")
        a.accountId = str(d, "accountId"); a.fifoId = str(d, "fifoId"); a.accountType = str(d, "accountType")
        a.activityType = str(d, "activityType"); a.activitySubType = str(d, "activitySubType")
        a.description = str(d, "description"); a.direction = str(d, "direction"); a.symbol = str(d, "symbol")
        a.name = str(d, "name"); a.currency = str(d, "currency")
        a.quantity = num(d, "quantity"); a.unitPrice = num(d, "unitPrice"); a.commission = num(d, "commission")
        a.netCashAmount = num(d, "netCashAmount")
        a.category = str(d, "category"); a.rawType = str(d, "rawType"); a.aftType = str(d, "aftType")
        a.securityId = str(d, "securityId")
        return a
    }

    func security(_ d: [String: Any]) -> BHSecurity {
        BHSecurity(id: str(d, "id"), symbol: str(d, "symbol"), name: str(d, "name"), underlyingId: str(d, "underlyingId"),
                   primaryExchange: str(d, "primaryExchange"), primaryMic: str(d, "primaryMic"), currency: str(d, "currency"))
    }

    func market(_ d: [String: Any]) -> BHMarket {
        var m = BHMarket()
        for (k, v) in (d["fx"] as? [String: Any]) ?? [:] { m.fx[k] = (v as? NSNumber)?.doubleValue }
        for (sym, rows) in (d["distributions"] as? [String: Any]) ?? [:] {
            m.distributions[sym] = ((rows as? [[String: Any]]) ?? []).map {
                BHDistribution(exDate: str($0, "exDate"), payDate: str($0, "payDate"), amount: num($0, "amount"), currency: str($0, "currency"))
            }
        }
        for (sym, q) in (d["quotes"] as? [String: Any]) ?? [:] {
            let qd = (q as? [String: Any]) ?? [:]
            m.quotes[sym] = BHQuote(price: (qd["price"] as? NSNumber)?.doubleValue, priceChange: (qd["priceChange"] as? NSNumber)?.doubleValue,
                                    percentChange: (qd["percentChange"] as? NSNumber)?.doubleValue, fetchedAt: str(qd, "fetchedAt"),
                                    exDividendDate: str(qd, "exDividendDate"))
        }
        return m
    }

    // MARK: what the Swift model produces, in the fixture's shape

    func opt(_ v: Double?) -> Any { v.map { $0 as Any } ?? NSNull() }

    func expect(_ base: BHBase, hasDividends: Bool) -> [String: Any] {
        let trades = base.trades.sorted { ($0.entryDate, $0.exitDate, $0.symbol) < ($1.entryDate, $1.exitDate, $1.symbol) }
        let k = BHModel.kpi(base.trades)
        var out: [String: Any] = [
            "kpi": [
                "count": k.count, "wins": k.wins, "losses": k.losses, "winRate": opt(k.winRate), "realized": k.realized,
                "expectancy": opt(k.expectancy), "profitFactor": opt(k.profitFactor), "avgHold": opt(k.avgHold),
                "avgWin": k.avgWin, "avgLoss": k.avgLoss,
            ] as [String: Any],
            "trades": trades.map { t -> [String: Any] in
                [
                    "symbol": t.symbol, "kind": t.kind, "currency": t.currency, "side": t.side, "qty": t.qty, "mult": t.mult,
                    "entry": t.entry, "exit": t.exit, "entryDate": t.entryDate, "exitDate": t.exitDate, "holdDays": t.holdDays,
                    "pnl": t.pnl, "pnlCad": t.pnlCad, "pnlPct": opt(t.pnlPct), "status": t.status, "fees": t.fees,
                    "fills": t.fills.sorted { $0.when < $1.when }.map { $0.sub },
                ]
            },
            "positions": base.positions.sorted { $0.symbol < $1.symbol }.map { p -> [String: Any] in
                ["symbol": p.symbol, "kind": p.kind, "currency": p.currency, "qty": p.qty, "avg": p.avg, "cost": p.cost]
            },
        ]
        if hasDividends {
            let cf = BHModel.cashflowView(base)
            out["cashflowHoldings"] = cf.holdings.sorted { $0.symbol < $1.symbol }.map { h -> [String: Any] in
                [
                    "symbol": h.symbol, "qty": h.qty, "per": opt(h.per), "freq": h.freq.map { $0 as Any } ?? NSNull(),
                    "freqVerified": h.freqVerified, "annual": opt(h.annual), "yoc": opt(h.yoc), "ytd": h.ytd, "ttm": h.ttm, "all": h.all,
                    "nextExDate": h.nextExDate, "nextPayDate": h.nextPayDate, "exPast": h.exPast, "payPast": h.payPast,
                ]
            }
            out["cashflowTiles"] = cf.tiles.map { t -> [String: Any] in
                var d: [String: Any] = ["label": t.label]
                if let v = t.total { d["total"] = v }
                if let v = t.perMonth { d["perMonth"] = v }
                if let v = t.count { d["count"] = v }
                if t.label == "Yield on cost" {
                    d["yield"] = opt(t.yield)
                    d["earned"] = t.earned ?? 0
                    d["book"] = t.book ?? 0
                }
                return d
            }
        }
        return out
    }

    // MARK: comparing

    func diff(_ got: Any, _ want: Any, _ path: String, _ out: inout [String]) {
        if let g = got as? [String: Any] {
            guard let w = want as? [String: Any] else { out.append("\(path): expected \(want), got object"); return }
            for key in Set(g.keys).union(w.keys).sorted() {
                guard let gv = g[key] else { out.append("\(path).\(key): missing on the Swift side"); continue }
                guard let wv = w[key] else { out.append("\(path).\(key): not in the case"); continue }
                diff(gv, wv, "\(path).\(key)", &out)
            }
            return
        }
        if let g = got as? [Any] {
            guard let w = want as? [Any] else { out.append("\(path): expected \(want), got list"); return }
            if g.count != w.count { out.append("\(path): \(w.count) expected, got \(g.count)") }
            for (i, (gv, wv)) in zip(g, w).enumerated() { diff(gv, wv, "\(path)[\(i)]", &out) }
            return
        }
        if got is NSNull {
            if !(want is NSNull) { out.append("\(path): expected \(want), got null") }
            return
        }
        if let g = got as? String {
            if g != (want as? String) { out.append("\(path): expected \(want), got \"\(g)\"") }
            return
        }
        if let g = got as? Bool, type(of: got) == Bool.self {
            if g != ((want as? NSNumber)?.boolValue) { out.append("\(path): expected \(want), got \(g)") }
            return
        }
        if let g = (got as? NSNumber)?.doubleValue {
            guard !(want is NSNull), let w = (want as? NSNumber)?.doubleValue else { out.append("\(path): expected \(want), got \(g)"); return }
            if abs(g - w) > 2e-6 { out.append("\(path): expected \(w), got \(g)") }
            return
        }
        out.append("\(path): cannot compare \(got) with \(want)")
    }

    func testEveryCaseMatches() throws {
        let files = try FileManager.default.contentsOfDirectory(at: Self.casesDir, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
        XCTAssertFalse(files.isEmpty, "no cases found at \(Self.casesDir.path)")
        for file in files {
            let doc = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
            let snapshot = doc["snapshot"] as! [String: Any]
            let rows = snapshot["activities"] as! [[String: Any]]
            let acts = rows.map(activity)
            let secs = ((snapshot["securities"] as? [[String: Any]]) ?? []).map(security)
            let base = BHModel.buildBase(activities: acts, securities: secs, market: market(doc["market"] as! [String: Any]), today: doc["today"] as! String)
            let got = expect(base, hasDividends: rows.contains { ($0["category"] as? String) == "dividend" })
            var problems: [String] = []
            diff(got, doc["expect"] as! [String: Any], file.lastPathComponent, &problems)
            XCTAssertTrue(problems.isEmpty, problems.joined(separator: "\n"))
        }
    }

    func testDateArithmetic() {
        XCTAssertEqual(BHModel.daysBetween("2026-01-10", "2026-02-10"), 31)
        XCTAssertEqual(BHModel.daysBetween("2026-02-10", "2026-01-10"), 0)
        XCTAssertEqual(BHModel.shiftDate("2026-03-01", -1), "2026-02-28")
        XCTAssertEqual(BHModel.shiftDate("2024-02-28", 1), "2024-02-29")
        XCTAssertEqual(BHModel.shiftDate("2025-12-31", 1), "2026-01-01")
        XCTAssertEqual(BHModel.optionExpiry("LUNR 29AUG25 11.50 CALL"), "2025-08-29")
        XCTAssertEqual(BHModel.optionExpiry("BBAI 02JAN26 5.50 PUT"), "2026-01-02")
        XCTAssertEqual(BHModel.optionExpiry("AAPL"), "")
    }
}
