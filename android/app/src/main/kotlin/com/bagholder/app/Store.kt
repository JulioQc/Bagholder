// What the app keeps on the device: the Wealthsimple session, the last pull
// (activities and listings), and the FX rates already fetched. All in the
// app's private storage; nothing leaves the device.
package com.bagholder.app

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class StoredPull(val activities: List<WSActivity>, val listings: List<WSSecurityListing>, val syncedAt: String)

object Store {
    private lateinit var prefs: SharedPreferences
    private lateinit var dir: File

    fun init(context: Context) {
        prefs = context.getSharedPreferences("bagholder", Context.MODE_PRIVATE)
        dir = File(context.filesDir, "bagholder").apply { mkdirs() }
    }

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
        prefs.edit().remove("oauth_cookie").remove("wssdi").apply()
    }

    private val pullFile get() = File(dir, "last-pull.json")

    fun loadPull(): StoredPull? {
        if (!pullFile.exists()) return null
        return try {
            val doc = JSONObject(pullFile.readText())
            val acts = doc.optJSONArray("activities") ?: JSONArray()
            val lists = doc.optJSONArray("listings") ?: JSONArray()
            StoredPull(
                (0 until acts.length()).map { WSActivity.fromJson(acts.getJSONObject(it)) },
                (0 until lists.length()).map { WSSecurityListing.fromJson(lists.getJSONObject(it)) },
                doc.optString("syncedAt"),
            )
        } catch (e: Exception) {
            null
        }
    }

    fun savePull(pull: StoredPull) {
        val doc = JSONObject()
            .put("activities", JSONArray(pull.activities.map { it.toJson() }))
            .put("listings", JSONArray(pull.listings.map { it.toJson() }))
            .put("syncedAt", pull.syncedAt)
        val tmp = File(dir, "last-pull.json.tmp")
        tmp.writeText(doc.toString())
        tmp.renameTo(pullFile)
    }

    fun clearPull() {
        pullFile.delete()
    }

    fun loadFx(): Map<String, Double> {
        val raw = prefs.getString("fx", null) ?: return emptyMap()
        return try {
            val o = JSONObject(raw)
            val out = HashMap<String, Double>()
            for (k in o.keys()) {
                val v = o.optDouble(k, Double.NaN)
                if (v > 0) out[k] = v
            }
            out
        } catch (e: Exception) {
            emptyMap()
        }
    }

    fun saveFx(map: Map<String, Double>) {
        prefs.edit().putString("fx", JSONObject(map).toString()).apply()
    }
}
