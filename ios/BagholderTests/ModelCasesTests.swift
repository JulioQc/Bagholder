import XCTest
@testable import Bagholder

/// The shared model cases in ../../fixtures/cases, run through the Swift model.
/// The same files run through the Python model (test_fixtures.py); a rule
/// changed in one place fails here. fixtures/README.md describes the format.
final class ModelCasesTests: XCTestCase {
    static let casesDir: URL = {
        var u = URL(fileURLWithPath: #filePath)
        for _ in 0..<3 { u.deleteLastPathComponent() }   // BagholderTests -> ios -> repo root
        return u.appendingPathComponent("fixtures/cases")
    }()

    func activity(_ d: [String: Any]) -> WSActivity {
        func s(_ k: String) -> String { (d[k] as? String) ?? "" }
        func n(_ k: String) -> Double { (d[k] as? Double) ?? Double((d[k] as? Int) ?? 0) }
        return WSActivity(id: s("id"), canonicalId: s("id"), occurredAt: s("occurredAt"), transactionDate: s("transactionDate"),
                          accountId: s("accountId"), fifoId: "", accountType: s("accountType"), activityType: s("activityType"),
                          activitySubType: s("activitySubType"), description: "", direction: "", symbol: s("symbol"), name: s("name"),
                          currency: s("currency"), quantity: n("quantity"), unitPrice: n("unitPrice"), commission: n("commission"),
                          netCashAmount: n("netCashAmount"), category: s("category"), rawType: s("rawType"), aftType: "",
                          counterSymbol: "")
    }

    func testEveryCaseMatches() throws {
        let files = try FileManager.default.contentsOfDirectory(at: Self.casesDir, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
        XCTAssertFalse(files.isEmpty, "no cases found at \(Self.casesDir.path)")
        for file in files {
            let doc = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
            let snapshot = doc["snapshot"] as! [String: Any]
            let expect = doc["expect"] as! [String: Any]
            let acts = (snapshot["activities"] as! [[String: Any]]).map(activity)
            let matched = WSPull.matchFifo(acts)
            let trades = matched.closed.sorted { ($0.entryDate, $0.exitDate, $0.symbol) < ($1.entryDate, $1.exitDate, $1.symbol) }
            let want = expect["trades"] as! [[String: Any]]
            let name = file.lastPathComponent
            XCTAssertEqual(trades.count, want.count, "\(name): trade count")
            for (t, w) in zip(trades, want) {
                XCTAssertEqual(t.symbol, w["symbol"] as? String, "\(name): symbol")
                XCTAssertEqual(t.displaySide, w["side"] as? String, "\(name): side")
                XCTAssertEqual(t.entryDate, w["entryDate"] as? String, "\(name): entryDate")
                XCTAssertEqual(t.exitDate, w["exitDate"] as? String, "\(name): exitDate")
                XCTAssertEqual(t.quantity, w["qty"] as? Double ?? 0, accuracy: 1e-6, "\(name): qty")
                XCTAssertEqual(t.entryPrice, w["entry"] as? Double ?? 0, accuracy: 1e-6, "\(name): entry")
                XCTAssertEqual(t.exitPrice, w["exit"] as? Double ?? 0, accuracy: 1e-6, "\(name): exit")
                XCTAssertEqual(t.pnl, w["pnl"] as? Double ?? 0, accuracy: 1e-6, "\(name): pnl")
                XCTAssertEqual(t.holdDays, w["holdDays"] as? Int ?? -1, "\(name): holdDays")
            }
            let kpi = expect["kpi"] as! [String: Any]
            let m = WSPull.computeMetrics(matched.closed)
            XCTAssertEqual(m.tradeCount, kpi["count"] as? Int ?? -1, "\(name): count")
            XCTAssertEqual(m.winCount, kpi["wins"] as? Int ?? -1, "\(name): wins")
            XCTAssertEqual(m.lossCount, kpi["losses"] as? Int ?? -1, "\(name): losses")
            if let wr = kpi["winRate"] as? Double { XCTAssertEqual(m.winRate, wr, accuracy: 1e-6, "\(name): winRate") }
            // Python keeps one position per symbol and account; Swift keeps the lots. Compare what is open by symbol.
            let openWant = Set((expect["positions"] as! [[String: Any]]).compactMap { $0["symbol"] as? String })
            XCTAssertEqual(Set(matched.open.map { $0.symbol }), openWant, "\(name): open symbols")
        }
    }
}
