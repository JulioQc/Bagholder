package com.bagholder.model

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The shared model cases in ../../fixtures/cases, run through the Kotlin model.
 * The same files run through the Python (test_fixtures.py) and Swift
 * (ModelCasesTests) models; a rule changed in one place fails here.
 * fixtures/README.md describes the format: `expect` holds the trades, KPIs,
 * positions and, when the case has a dividend row, the Cashflow holdings and
 * tiles, floats rounded to six places. */
class ModelCasesTest {
    private val casesDir = File("../../fixtures/cases")

    private fun str(d: JSONObject, k: String) = d.optString(k, "")
    private fun num(d: JSONObject, k: String) = if (d.has(k) && !d.isNull(k)) d.optDouble(k, 0.0) else 0.0
    private fun numOrNull(d: JSONObject, k: String): Double? = if (d.has(k) && !d.isNull(k)) d.optDouble(k) else null

    private fun activity(d: JSONObject): Act {
        val a = Act()
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

    private fun security(d: JSONObject) = Security(
        id = str(d, "id"), symbol = str(d, "symbol"), name = str(d, "name"), underlyingId = str(d, "underlyingId"),
        primaryExchange = str(d, "primaryExchange"), primaryMic = str(d, "primaryMic"), currency = str(d, "currency"),
    )

    private fun market(d: JSONObject): Market {
        val fx = HashMap<String, Double>()
        d.optJSONObject("fx")?.let { o -> for (k in o.keys()) fx[k] = o.getDouble(k) }
        val dists = HashMap<String, List<Distribution>>()
        d.optJSONObject("distributions")?.let { o ->
            for (sym in o.keys()) {
                val rows = o.getJSONArray(sym)
                dists[sym] = (0 until rows.length()).map { i ->
                    val r = rows.getJSONObject(i)
                    Distribution(str(r, "exDate"), str(r, "payDate"), num(r, "amount"), str(r, "currency"))
                }
            }
        }
        val quotes = HashMap<String, Quote>()
        d.optJSONObject("quotes")?.let { o ->
            for (sym in o.keys()) {
                val q = o.getJSONObject(sym)
                quotes[sym] = Quote(numOrNull(q, "price"), numOrNull(q, "priceChange"), numOrNull(q, "percentChange"), str(q, "fetchedAt"), str(q, "exDividendDate"))
            }
        }
        return Market(fx, dists, quotes)
    }

    // What the Kotlin model produces, in the fixture's shape.

    private fun opt(v: Double?): Any = v ?: JSONObject.NULL

    private fun expect(base: Base, hasDividends: Boolean): Map<String, Any> {
        val trades = base.trades.sortedWith(compareBy({ it.entryDate }, { it.exitDate }, { it.symbol }))
        val k = Model.kpi(base.trades)
        val out = LinkedHashMap<String, Any>()
        out["kpi"] = mapOf(
            "count" to k.count, "wins" to k.wins, "losses" to k.losses, "winRate" to opt(k.winRate), "realized" to k.realized,
            "expectancy" to opt(k.expectancy), "profitFactor" to opt(k.profitFactor), "avgHold" to opt(k.avgHold),
            "avgWin" to k.avgWin, "avgLoss" to k.avgLoss,
        )
        out["trades"] = trades.map { t ->
            mapOf(
                "symbol" to t.symbol, "kind" to t.kind, "currency" to t.currency, "side" to t.side, "qty" to t.qty, "mult" to t.mult,
                "entry" to t.entry, "exit" to t.exit, "entryDate" to t.entryDate, "exitDate" to t.exitDate, "holdDays" to t.holdDays,
                "pnl" to t.pnl, "pnlCad" to t.pnlCad, "pnlPct" to opt(t.pnlPct), "status" to t.status, "fees" to t.fees,
                "fills" to t.fills.sortedBy { it.whenAt }.map { it.sub },
            )
        }
        out["positions"] = base.positions.sortedBy { it.symbol }.map { p ->
            mapOf("symbol" to p.symbol, "kind" to p.kind, "currency" to p.currency, "qty" to p.qty, "avg" to p.avg, "cost" to p.cost)
        }
        if (hasDividends) {
            val cf = Model.cashflowView(base)
            out["cashflowHoldings"] = cf.holdings.sortedBy { it.symbol }.map { h ->
                mapOf(
                    "symbol" to h.symbol, "qty" to h.qty, "per" to opt(h.per), "freq" to (h.freq ?: JSONObject.NULL),
                    "freqVerified" to h.freqVerified, "annual" to opt(h.annual), "yoc" to opt(h.yoc), "ytd" to h.ytd, "ttm" to h.ttm, "all" to h.all,
                    "nextExDate" to h.nextExDate, "nextPayDate" to h.nextPayDate, "exPast" to h.exPast, "payPast" to h.payPast,
                )
            }
            out["cashflowTiles"] = cf.tiles.map { t ->
                val d = LinkedHashMap<String, Any>()
                d["label"] = t.label
                t.total?.let { d["total"] = it }
                t.perMonth?.let { d["perMonth"] = it }
                t.count?.let { d["count"] = it }
                if (t.label == "Yield on cost") {
                    d["yield"] = opt(t.yield)
                    d["earned"] = t.earned ?: 0.0
                    d["book"] = t.book ?: 0.0
                }
                d
            }
        }
        return out
    }

    // Comparing.

    private fun diff(got: Any?, want: Any?, path: String, out: MutableList<String>) {
        when (got) {
            is Map<*, *> -> {
                if (want !is JSONObject) { out.add("$path: expected $want, got object"); return }
                val keys = (got.keys.map { it.toString() } + want.keys().asSequence().toList()).toSet().sorted()
                for (key in keys) {
                    if (!got.containsKey(key)) { out.add("$path.$key: missing on the Kotlin side"); continue }
                    if (!want.has(key)) { out.add("$path.$key: not in the case"); continue }
                    diff(got[key], want.get(key), "$path.$key", out)
                }
            }
            is List<*> -> {
                if (want !is JSONArray) { out.add("$path: expected $want, got list"); return }
                if (got.size != want.length()) out.add("$path: ${want.length()} expected, got ${got.size}")
                for (i in 0 until minOf(got.size, want.length())) diff(got[i], want.get(i), "$path[$i]", out)
            }
            JSONObject.NULL, null -> if (want != JSONObject.NULL) out.add("$path: expected $want, got null")
            is String -> if (got != want) out.add("$path: expected $want, got \"$got\"")
            is Boolean -> if (got != want) out.add("$path: expected $want, got $got")
            is Number -> {
                if (want !is Number) { out.add("$path: expected $want, got $got"); return }
                if (abs(got.toDouble() - want.toDouble()) > 2e-6) out.add("$path: expected $want, got $got")
            }
            else -> out.add("$path: cannot compare $got with $want")
        }
    }

    @Test
    fun everyCaseMatches() {
        val files = (casesDir.listFiles() ?: emptyArray()).filter { it.extension == "json" }.sortedBy { it.name }
        assertTrue(files.isNotEmpty(), "no cases found at ${casesDir.absolutePath}")
        for (file in files) {
            val doc = JSONObject(file.readText())
            val snapshot = doc.getJSONObject("snapshot")
            val rows = snapshot.getJSONArray("activities")
            val acts = (0 until rows.length()).map { activity(rows.getJSONObject(it)) }
            val secRows = snapshot.optJSONArray("securities") ?: JSONArray()
            val secs = (0 until secRows.length()).map { security(secRows.getJSONObject(it)) }
            val base = Model.buildBase(acts, secs, market(doc.getJSONObject("market")), doc.getString("today"))
            val hasDividends = (0 until rows.length()).any { rows.getJSONObject(it).optString("category") == "dividend" }
            val problems = mutableListOf<String>()
            diff(expect(base, hasDividends), doc.getJSONObject("expect"), file.name, problems)
            assertTrue(problems.isEmpty(), problems.joinToString("\n"))
        }
    }

    @Test
    fun dateArithmetic() {
        assertEquals(31, Model.daysBetween("2026-01-10", "2026-02-10"))
        assertEquals(0, Model.daysBetween("2026-02-10", "2026-01-10"))
        assertEquals("2026-02-28", Model.shiftDate("2026-03-01", -1))
        assertEquals("2024-02-29", Model.shiftDate("2024-02-28", 1))
        assertEquals("2025-08-29", Model.optionExpiry("LUNR 29AUG25 11.50 CALL"))
        assertEquals("2026-01-02", Model.optionExpiry("BBAI 02JAN26 5.50 PUT"))
        assertEquals("", Model.optionExpiry("AAPL"))
    }
}
