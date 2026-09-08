// The screens: Home, Closed trades, Open lots, and the Wealthsimple login.
// Every figure comes from the model (android/model); a screen is a layout of
// those figures, not a new definition of them.
package com.bagholder.app

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.bagholder.model.Lot
import com.bagholder.model.Trade
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Locale
import kotlin.math.abs

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Journal.start(this)
        setContent {
            BagholderTheme { App() }
        }
    }
}

// MARK: theme and formatting

object Tone {
    val profit = Color(0xFF34C759)
    val loss = Color(0xFFFF3B30)
}

@Composable
fun BagholderTheme(content: @Composable () -> Unit) {
    val scheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()
    MaterialTheme(colorScheme = scheme) {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background, content = content)
    }
}

object Fmt {
    const val DASH = "—"
    const val MINUS = "−"

    fun cad(n: Double?, digits: Int = 2): String {
        if (n == null || n.isNaN()) return DASH
        val body = "$" + String.format(Locale.US, "%,." + digits + "f", abs(n))
        return if (n < 0) MINUS + body else body
    }

    fun pct(r: Double?, digits: Int = 1): String {
        if (r == null || !r.isFinite()) return DASH
        val body = String.format(Locale.US, "%." + digits + "f", abs(r) * 100) + "%"
        return if (r < 0) MINUS + body else body
    }

    fun qty(n: Double): String {
        val a = abs(n)
        return if (a == Math.floor(a)) String.format(Locale.US, "%,.0f", a) else String.format(Locale.US, "%,.8f", a).trimEnd('0').trimEnd('.')
    }

    fun date(iso: String): String {
        if (iso.length < 10) return iso
        return try {
            val d = SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(iso.take(10))!!
            SimpleDateFormat("MMM d, yyyy", Locale.US).format(d)
        } catch (e: Exception) {
            iso
        }
    }

    fun hold(days: Int): String = if (days == 1) "1 day" else "$days days"

    fun profitFactor(pf: Double?, infinite: Boolean): String {
        if (infinite) return "∞"
        if (pf == null) return DASH
        return String.format(Locale.US, "%.2f", pf)
    }

    fun signed(n: Double, ink: Color): Color = when {
        n < -0.0001 -> Tone.loss
        n > 0.0001 -> Tone.profit
        else -> ink
    }
}

// MARK: the app

@Composable
fun App() {
    var tab by remember { mutableIntStateOf(0) }
    var showConnect by remember { mutableStateOf(false) }
    var selected by remember { mutableStateOf<Trade?>(null) }

    if (showConnect) {
        ConnectScreen(onSession = { cookie, wssdi ->
            showConnect = false
            Journal.connect(cookie, wssdi)
        }, onCancel = { showConnect = false })
        return
    }
    val trade = selected
    if (trade != null) {
        BackHandler { selected = null }
        TradeDetailScreen(trade, onBack = { selected = null })
        return
    }
    Scaffold(
        bottomBar = {
            NavigationBar {
                NavigationBarItem(selected = tab == 0, onClick = { tab = 0 }, icon = { Icon(Icons.Default.Home, null) }, label = { Text("Home") })
                NavigationBarItem(selected = tab == 1, onClick = { tab = 1 }, icon = { Icon(Icons.Default.List, null) }, label = { Text("Closed") })
                NavigationBarItem(selected = tab == 2, onClick = { tab = 2 }, icon = { Icon(Icons.Default.Star, null) }, label = { Text("Open") })
            }
        },
    ) { pad ->
        Box(Modifier.padding(pad)) {
            when (tab) {
                0 -> HomeScreen(onConnect = { showConnect = true })
                1 -> ClosedTradesScreen(onOpen = { selected = it })
                else -> OpenLotsScreen()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TitleBar(title: String) {
    val phase = Journal.phase
    TopAppBar(
        title = { Text(title) },
        actions = {
            if (Journal.connected) {
                if (phase is Journal.Phase.Pulling) {
                    CircularProgressIndicator(modifier = Modifier.padding(end = 16.dp).width(20.dp).height(20.dp), strokeWidth = 2.dp)
                } else {
                    IconButton(onClick = { Journal.pull() }) { Icon(Icons.Default.Refresh, contentDescription = "Sync") }
                }
            }
        },
    )
}

@Composable
private fun SyncLine() {
    val phase = Journal.phase
    val text = when (phase) {
        is Journal.Phase.Pulling -> phase.step
        is Journal.Phase.Failed -> phase.message
        else -> Journal.view?.syncedAt?.takeIf { it.isNotEmpty() }?.let { "Synced " + Fmt.date(it) } ?: ""
    }
    if (text.isNotEmpty()) {
        Text(
            text,
            style = MaterialTheme.typography.bodyMedium,
            color = if (phase is Journal.Phase.Failed) Tone.loss else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
        )
    }
}

// MARK: Home

@Composable
fun HomeScreen(onConnect: () -> Unit) {
    val view = Journal.view
    Column(Modifier.fillMaxSize()) {
        TitleBar("Bagholder")
        SyncLine()
        if (view == null && !Journal.connected) {
            Column(Modifier.fillMaxSize().padding(40.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                Text("Connect Wealthsimple", style = MaterialTheme.typography.headlineSmall)
                Spacer(Modifier.height(16.dp))
                Button(onClick = onConnect) { Text("Connect") }
            }
            return
        }
        val k = view?.kpi
        val ink = MaterialTheme.colorScheme.onBackground
        Column(Modifier.padding(horizontal = 16.dp)) {
            Text(
                Fmt.cad(k?.realized),
                fontSize = 38.sp,
                fontWeight = FontWeight.Bold,
                color = if (k != null) Fmt.signed(k.realized, ink) else ink,
            )
            Text("Realized P&L", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Spacer(Modifier.height(12.dp))
        val cards = listOf(
            Triple("Biggest winner", view?.biggestWinner?.let { Fmt.cad(it.second) } ?: Fmt.DASH, view?.biggestWinner?.first ?: Fmt.DASH),
            Triple("Biggest loser", view?.biggestLoser?.let { Fmt.cad(it.second) } ?: Fmt.DASH, view?.biggestLoser?.first ?: Fmt.DASH),
            Triple("Profit factor", k?.let { Fmt.profitFactor(it.profitFactor, it.profitFactorInfinite) } ?: Fmt.DASH, k?.let { Fmt.cad(it.grossWin) + " W, " + Fmt.cad(it.grossLoss) + " L" } ?: Fmt.DASH),
            Triple("Expectancy", k?.let { Fmt.cad(it.expectancy) } ?: Fmt.DASH, k?.let { Fmt.cad(it.avgWin) + " · " + Fmt.cad(it.avgLoss) } ?: Fmt.DASH),
            Triple("Win rate", k?.let { Fmt.pct(it.winRate) } ?: Fmt.DASH, k?.let { "${it.wins} W, ${it.losses} L, ${it.breakeven} BE" } ?: Fmt.DASH),
            Triple("Avg hold", k?.avgHold?.let { Fmt.hold(Math.round(it).toInt()) } ?: Fmt.DASH, k?.let { "${it.count} trades" } ?: Fmt.DASH),
        )
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            contentPadding = PaddingValues(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(cards) { (title, value, subtitle) ->
                val color = when (title) {
                    "Biggest winner" -> Tone.profit
                    "Biggest loser" -> Tone.loss
                    else -> ink
                }
                MetricCard(title, value, subtitle, color)
            }
            item { Spacer(Modifier.height(8.dp)) }
            item { Spacer(Modifier.height(8.dp)) }
        }
        if (Journal.connected) {
            TextButton(onClick = { Journal.disconnect() }, modifier = Modifier.padding(horizontal = 8.dp)) { Text("Disconnect") }
        } else {
            TextButton(onClick = onConnect, modifier = Modifier.padding(horizontal = 8.dp)) { Text("Connect") }
        }
    }
}

@Composable
private fun MetricCard(title: String, value: String, subtitle: String, valueColor: Color) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.padding(14.dp)) {
            Text(title, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(6.dp))
            Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold, color = valueColor, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

// MARK: Closed trades

@Composable
fun ClosedTradesScreen(onOpen: (Trade) -> Unit) {
    val trades = Journal.view?.trades ?: emptyList()
    val ink = MaterialTheme.colorScheme.onBackground
    Column(Modifier.fillMaxSize()) {
        TitleBar("Closed trades")
        SyncLine()
        if (trades.isEmpty()) {
            Empty("No closed trades")
            return
        }
        LazyColumn {
            items(trades, key = { it.id }) { t ->
                Row(
                    Modifier.fillMaxWidth().clickable { onOpen(t) }.padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(t.symbol, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(t.side + " · " + Fmt.date(t.exitDate), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text(Fmt.cad(t.pnl), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = Fmt.signed(t.pnl, ink), fontFamily = FontFamily.Monospace)
                }
                HorizontalDivider(modifier = Modifier.padding(horizontal = 16.dp))
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TradeDetailScreen(t: Trade, onBack: () -> Unit) {
    val ink = MaterialTheme.colorScheme.onBackground
    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("Executions (${t.fills.size})") },
            navigationIcon = { TextButton(onClick = onBack) { Text("Back") } },
        )
        LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
            item {
                Column(Modifier.padding(16.dp)) {
                    Text(t.symbol, style = MaterialTheme.typography.titleMedium)
                    val line = listOf(t.name.takeIf { it != t.symbol } ?: "", t.exchange).filter { it.isNotEmpty() }.joinToString(" · ")
                    if (line.isNotEmpty()) Text(line, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            val facts = listOf(
                "In" to t.entryDate, "Out" to t.exitDate, "Entry" to Fmt.cad(t.entry), "Exit" to Fmt.cad(t.exit),
                "P&L $" to Fmt.cad(t.pnl), "P&L %" to Fmt.pct(t.pnlPct), "Hold" to Fmt.hold(t.holdDays), "Currency" to t.currency,
            )
            items(facts) { (label, value) ->
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
                    Text(label, Modifier.weight(1f))
                    Text(value, fontFamily = FontFamily.Monospace, color = if (label.startsWith("P&L")) Fmt.signed(t.pnl, ink) else ink)
                }
            }
            item { HorizontalDivider(Modifier.padding(16.dp)) }
            items(t.fills.sortedByDescending { it.whenAt }) { f ->
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(Fmt.date(f.date) + (if (f.time.isNotEmpty()) " " + f.time else ""))
                        Text(f.sub + " · " + Fmt.qty(f.qty) + " · " + Fmt.cad(f.price), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text(Fmt.cad(f.amount), fontWeight = FontWeight.SemiBold, fontFamily = FontFamily.Monospace, color = Fmt.signed(f.amount, ink))
                }
            }
        }
    }
}

// MARK: Open lots

@Composable
fun OpenLotsScreen() {
    val lots = (Journal.view?.lots ?: emptyList<Lot>()).sortedWith(compareByDescending<Lot> { it.date }.thenBy { it.symbol })
    Column(Modifier.fillMaxSize()) {
        TitleBar("Open lots")
        SyncLine()
        if (lots.isEmpty()) {
            Empty("No open lots")
            return
        }
        LazyColumn {
            items(lots) { l ->
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(l.symbol, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(l.direction + " · " + Fmt.qty(l.qty) + " · " + Fmt.cad(l.price), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text(Fmt.date(l.date), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                HorizontalDivider(modifier = Modifier.padding(horizontal = 16.dp))
            }
        }
    }
}

@Composable
private fun Empty(text: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(text, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

// MARK: Connect (the Wealthsimple login in a web view; the session cookie is captured from it)

private val COOKIE_URLS = listOf("https://my.wealthsimple.com", "https://wealthsimple.com", "https://api.production.wealthsimple.com")

private fun sessionFromCookies(): Pair<String, String?>? {
    val cm = CookieManager.getInstance()
    var oauth: String? = null
    var wssdi: String? = null
    for (url in COOKIE_URLS) {
        val raw = cm.getCookie(url) ?: continue
        for (part in raw.split(";")) {
            val eq = part.indexOf('=')
            if (eq < 0) continue
            val name = part.substring(0, eq).trim()
            val value = part.substring(eq + 1).trim()
            if (name == "wssdi" && value.isNotEmpty()) wssdi = value
            if (name == WSPull.OAUTH_COOKIE && WSPull.jsonWithAccessToken(value) != null) {
                oauth = value
            } else if (oauth == null && WSPull.jsonWithAccessToken(value) != null) {
                oauth = value
            }
        }
    }
    val o = oauth ?: return null
    return Pair(o, wssdi)
}

@SuppressLint("SetJavaScriptEnabled")
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConnectScreen(onSession: (String, String?) -> Unit, onCancel: () -> Unit) {
    var done by remember { mutableStateOf(false) }
    BackHandler { onCancel() }
    LaunchedEffect(Unit) {
        while (!done) {
            val found = sessionFromCookies()
            if (found != null) {
                done = true
                CookieManager.getInstance().flush()
                onSession(found.first, found.second)
                break
            }
            delay(1000)
        }
    }
    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("Connect") },
            navigationIcon = { TextButton(onClick = onCancel) { Text("Cancel") } },
        )
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { context ->
                WebView(context).apply {
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    CookieManager.getInstance().setAcceptCookie(true)
                    CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
                    webViewClient = object : WebViewClient() {}
                    loadUrl(WSPull.LOGIN_URL)
                }
            },
        )
    }
}
