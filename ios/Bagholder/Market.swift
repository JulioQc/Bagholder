// Market data on the phone: what the desktop's market.py fetches server-side,
// fetched here from the same sources and kept in the app's files. Every
// request records its outcome, and that is what a chart's empty state says.
import Foundation

enum MarketData {
    static var dir: URL { AppFiles.dir }

    // MARK: caches

    private static func readJSON(_ name: String) -> [String: Any] {
        guard let data = try? Data(contentsOf: dir.appendingPathComponent(name)), let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return obj
    }

    private static func writeJSON(_ name: String, _ obj: [String: Any]) {
        if let data = try? JSONSerialization.data(withJSONObject: obj) { try? data.write(to: dir.appendingPathComponent(name), options: .atomic) }
    }

    /// The S&P/TSX Composite and TSX 60 closes, by benchmark key.
    static func indexCloses() -> [String: [String: Double]] {
        var out: [String: [String: Double]] = [:]
        for (k, v) in readJSON("indexes.json") {
            var m: [String: Double] = [:]
            for (d, c) in (v as? [String: Any]) ?? [:] { if let n = (c as? NSNumber)?.doubleValue { m[d] = n } }
            out[k] = m
        }
        return out
    }

    /// The declared distribution records, by symbol.
    static func distributions() -> [String: [BHDistribution]] {
        var out: [String: [BHDistribution]] = [:]
        for (sym, rows) in readJSON("distributions.json") {
            out[sym] = ((rows as? [[String: Any]]) ?? []).map {
                BHDistribution(exDate: ($0["exDate"] as? String) ?? "", payDate: ($0["payDate"] as? String) ?? "", amount: (($0["amount"] as? NSNumber)?.doubleValue) ?? 0, currency: ($0["currency"] as? String) ?? "")
            }
        }
        return out
    }

    // MARK: the trade chart

    /// The bars for a trade's span: the sources are asked next; until then the
    /// chart says so rather than drawing anything.
    static func bars(for trade: BHTrade) async -> (bars: [BHBar], reason: String) {
        return ([], "No bars for this span: the sources have not been asked on this device.")
    }
}
