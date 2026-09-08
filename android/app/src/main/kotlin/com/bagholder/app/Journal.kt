// The app's state: the session, the last pull, and the model built from it.
// Screens read these; the pull runs off the main thread and writes them back.
package com.bagholder.app

import android.content.Context
import android.webkit.CookieManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.bagholder.model.KPI
import com.bagholder.model.Lot
import com.bagholder.model.Market
import com.bagholder.model.Model
import com.bagholder.model.Security
import com.bagholder.model.Trade
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/** The model's output for the screens, unfiltered. */
class ModelView(
    val trades: List<Trade>,
    val lots: List<Lot>,
    val kpi: KPI,
    val biggestWinner: Pair<String, Double>?,
    val biggestLoser: Pair<String, Double>?,
    val activityCount: Int,
    val syncedAt: String,
)

object Journal {
    sealed class Phase {
        object Idle : Phase()
        data class Pulling(val step: String) : Phase()
        object Ready : Phase()
        data class Failed(val message: String) : Phase()
    }

    var phase by mutableStateOf<Phase>(Phase.Idle)
        private set
    var connected by mutableStateOf(false)
        private set
    var view by mutableStateOf<ModelView?>(null)
        private set

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var started = false
    private var pulling = false

    fun start(context: Context) {
        if (started) return
        started = true
        Store.init(context.applicationContext)
        connected = Store.loadSession() != null
        scope.launch {
            val stored = Store.loadPull()
            if (stored != null) {
                val v = rebuild(stored, Store.loadFx())
                withContext(Dispatchers.Main) {
                    view = v
                    phase = Phase.Ready
                }
            }
            if (connected) pull()
        }
    }

    fun connect(cookie: String, wssdi: String?) {
        Store.saveSession(cookie, wssdi)
        connected = true
        pull()
    }

    fun disconnect() {
        Store.clearSession()
        Store.clearPull()
        CookieManager.getInstance().removeAllCookies(null)
        CookieManager.getInstance().flush()
        connected = false
        view = null
        phase = Phase.Idle
    }

    fun pull() {
        val session = Store.loadSession() ?: return
        if (pulling) return
        pulling = true
        phase = Phase.Pulling("Connecting…")
        scope.launch {
            try {
                val stored = Store.loadPull()
                val res = WSPull.run(session.first, session.second, stored?.activities ?: emptyList(), stored?.listings ?: emptyList()) { step ->
                    scope.launch(Dispatchers.Main) { phase = Phase.Pulling(step) }
                }
                withContext(Dispatchers.Main) { phase = Phase.Pulling("Fetching exchange rates…") }
                val fx = WSPull.ensureFxRates(res.activities, Store.loadFx())
                Store.saveFx(fx)
                val pull = StoredPull(res.activities, res.listings, nowIso())
                Store.savePull(pull)
                val v = rebuild(pull, fx)
                withContext(Dispatchers.Main) {
                    view = v
                    phase = Phase.Ready
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) { phase = Phase.Failed(e.message ?: e.toString()) }
            } finally {
                pulling = false
            }
        }
    }

    private fun nowIso(): String {
        val f = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
        f.timeZone = TimeZone.getTimeZone("UTC")
        return f.format(Date())
    }

    private fun rebuild(pull: StoredPull, fx: Map<String, Double>): ModelView {
        val securities = pull.listings.map {
            Security(id = it.id, symbol = it.symbol, name = it.name, underlyingId = it.underlyingId, primaryExchange = it.primaryExchange, primaryMic = it.primaryMic, currency = it.currency)
        }
        val base = Model.buildBase(pull.activities.map { it.toAct() }, securities, Market(fx = fx), Model.todayLocal())
        val bySymbol = LinkedHashMap<String, Double>()
        for (t in base.trades) bySymbol[t.underlying] = (bySymbol[t.underlying] ?: 0.0) + t.pnlCad
        val winner = bySymbol.entries.filter { it.value > 0 }.maxByOrNull { it.value }?.let { Pair(it.key, it.value) }
        val loser = bySymbol.entries.filter { it.value < 0 }.minByOrNull { it.value }?.let { Pair(it.key, it.value) }
        return ModelView(base.trades, base.openLots, Model.kpi(base.trades), winner, loser, pull.activities.size, pull.syncedAt)
    }
}
