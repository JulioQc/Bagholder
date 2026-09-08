// What the app keeps on the device: the Wealthsimple session, the last pull
// (activities, listings, NAV history), the journal, the filter set, the FX
// rates and the index closes already fetched. All in the app's private
// storage; nothing leaves the device.
package com.bagholder.app

import android.content.Context
import android.content.SharedPreferences
import com.bagholder.model.Filters
import com.bagholder.model.JournalEntry
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class StoredPull(
    val activities: List<WSActivity>, val listings: List<WSSecurityListing>, val syncedAt: String,
    val nav: List<WSNavPoint> = emptyList(), val navByAccount: Map<String, List<WSNavPoint>> = emptyMap(),
)

object Store {
    private lateinit var prefs: SharedPreferences
    lateinit var dir: File
        private set

    fun init(context: Context) {
        prefs = context.getSharedPreferences("bagholder", Context.MODE_PRIVATE)
        dir = File(context.filesDir, "bagholder").apply { mkdirs() }
    }

    // MARK: the session

    fun loadSession(): Pair<String, String?>? {
        val cookie = prefs.getString("oauth_cookie", null) ?: return null
        if (WSPull.jsonWithAccessToken(cookie) == null) return null
        return Pair(cookie, prefs.getString("wssdi", null))
    }

    fun saveSession(cookie: String, wssdi: String?) {
        if (WSPull.jsonWithAccessToken(cookie) == null) return
        prefs.edit().putString("oauth_cookie", cookie).putString("wssdi", wssdi).apply()
    }

    fun clearSession() {
        prefs.edit().remove("oauth_cookie").remove("wssdi").remove("lastSync").apply()
    }

    var lastSync: Long?
        get() = if (prefs.contains("lastSync")) prefs.getLong("lastSync", 0) else null
        set(v) { if (v == null) prefs.edit().remove("lastSync").apply() else prefs.edit().putLong("lastSync", v).apply() }

    // MARK: JSON files

    fun readJSON(name: String): JSONObject {
        val f = File(dir, name)
        if (!f.exists()) return JSONObject()
        return try { JSONObject(f.readText()) } catch (e: Exception) { JSONObject() }
    }

    fun writeJSON(name: String, obj: JSONObject) {
        val tmp = File(dir, "$name.tmp")
        tmp.writeText(obj.toString())
        tmp.renameTo(File(dir, name))
    }

    // MARK: the last pull

    private val pullFile get() = File(dir, "last-pull.json")

    private fun navList(a: JSONArray?): List<WSNavPoint> = if (a == null) emptyList() else (0 until a.length()).map { WSNavPoint.fromJson(a.getJSONObject(it)) }

    fun loadPull(): StoredPull? {
        if (!pullFile.exists()) return null
        return try {
            val doc = JSONObject(pullFile.readText())
            val acts = doc.optJSONArray("activities") ?: JSONArray()
            val lists = doc.optJSONArray("listings") ?: JSONArray()
            val navBy = HashMap<String, List<WSNavPoint>>()
            doc.optJSONObject("navByAccount")?.let { o -> for (k in o.keys()) navBy[k] = navList(o.optJSONArray(k)) }
            StoredPull(
                (0 until acts.length()).map { WSActivity.fromJson(acts.getJSONObject(it)) },
                (0 until lists.length()).map { WSSecurityListing.fromJson(lists.getJSONObject(it)) },
                doc.optString("syncedAt"), navList(doc.optJSONArray("nav")), navBy,
            )
        } catch (e: Exception) {
            null
        }
    }

    fun savePull(pull: StoredPull) {
        val navBy = JSONObject()
        for ((k, v) in pull.navByAccount) navBy.put(k, JSONArray(v.map { it.toJson() }))
        val doc = JSONObject()
            .put("activities", JSONArray(pull.activities.map { it.toJson() }))
            .put("listings", JSONArray(pull.listings.map { it.toJson() }))
            .put("nav", JSONArray(pull.nav.map { it.toJson() }))
            .put("navByAccount", navBy)
            .put("syncedAt", pull.syncedAt)
        writeJSON("last-pull.json", doc)
    }

    fun clearPull() {
        pullFile.delete()
    }

    // MARK: rates and index closes

    private fun closes(name: String, key: String? = null): Map<String, Double> {
        val o = if (key == null) readJSON(name) else readJSON(name).optJSONObject(key) ?: JSONObject()
        val out = HashMap<String, Double>()
        for (k in o.keys()) {
            val v = o.optDouble(k, Double.NaN)
            if (v > 0) out[k] = v
        }
        return out
    }

    fun loadFx(): Map<String, Double> = closes("fx.json")
    fun saveFx(map: Map<String, Double>) = writeJSON("fx.json", JSONObject(map))
    fun loadSp500(): Map<String, Double> = closes("sp500.json")
    fun saveSp500(map: Map<String, Double>) = writeJSON("sp500.json", JSONObject(map))

    fun loadIndexes(): Map<String, Map<String, Double>> {
        val o = readJSON("indexes.json")
        return o.keys().asSequence().associateWith { closes("indexes.json", it) }
    }

    // MARK: the journal

    fun loadJournal(): Map<String, JournalEntry> {
        val o = readJSON("journal.json")
        val out = HashMap<String, JournalEntry>()
        for (k in o.keys()) {
            val e = o.optJSONObject(k) ?: continue
            val tags = e.optJSONArray("tags") ?: JSONArray()
            out[k] = JournalEntry(e.optString("grade"), e.optString("thesis"), (0 until tags.length()).map { tags.getString(it) })
        }
        return out
    }

    fun saveJournal(journal: Map<String, JournalEntry>) {
        val o = JSONObject()
        for ((k, e) in journal) {
            if (e.grade.isEmpty() && e.thesis.isEmpty() && e.tags.isEmpty()) continue
            o.put(k, JSONObject().put("grade", e.grade).put("thesis", e.thesis).put("tags", JSONArray(e.tags)))
        }
        writeJSON("journal.json", o)
    }

    // MARK: the filter set

    fun loadFilters(): Filters {
        val raw = prefs.getString("filters", null) ?: return Filters()
        return try { Filters.clean(loose(JSONObject(raw)) as Map<String, Any?>) } catch (e: Exception) { Filters() }
    }

    fun saveFilters(f: Filters) {
        val ranges = JSONObject()
        for ((k, r) in f.ranges) ranges.put(k, JSONObject().put("op", r.op).put("v", r.v ?: JSONObject.NULL))
        val lists = JSONObject()
        for ((k, v) in f.lists) lists.put(k, JSONArray(v))
        val o = JSONObject().put("lists", lists).put("ranges", ranges).put("preset", f.preset).put("years", JSONArray(f.years))
            .put("from", f.from).put("to", f.to).put("search", f.search).put("benchmark", f.benchmark)
        prefs.edit().putString("filters", o.toString()).apply()
    }

    fun loose(v: Any?): Any? = when (v) {
        is JSONObject -> v.keys().asSequence().associateWith { loose(v.get(it)) }
        is JSONArray -> (0 until v.length()).map { loose(v.get(it)) }
        JSONObject.NULL -> null
        else -> v
    }

    var allocationBy: String
        get() = prefs.getString("allocationBy", "market") ?: "market"
        set(v) = prefs.edit().putString("allocationBy", v).apply()
}
