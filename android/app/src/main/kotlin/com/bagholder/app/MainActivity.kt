// The pages: Dashboard, Trades, Positions, Cashflow, the trade and position
// detail, the filter sheet, the menu and the Wealthsimple login. Every figure
// comes from the model's View; a screen is a layout of those figures, not a
// new definition of them.
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
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.material3.Icon
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.bagholder.model.CashflowView
import com.bagholder.model.Filters
import com.bagholder.model.Holding
import com.bagholder.model.JournalEntry
import com.bagholder.model.Model
import com.bagholder.model.Options
import com.bagholder.model.Position
import com.bagholder.model.SymbolRow
import com.bagholder.model.Trade
import com.bagholder.model.View
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlin.math.abs
import kotlin.math.roundToInt

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Book.start(this)
        setContent {
            val t = if (isSystemInDarkTheme()) BHTheme.nocturne else BHTheme.light
            CompositionLocalProvider(LocalTheme provides t) {
                Surface(modifier = Modifier.fillMaxSize(), color = t.bg) { App() }
            }
        }
    }

    override fun onResume() { super.onResume(); Book.handleAppear() }
    override fun onStop() { super.onStop(); Book.handleBackground() }
}

class Chrome(val onFilters: () -> Unit, val onMenu: () -> Unit, val onConnect: () -> Unit)

// MARK: - root

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App() {
    val t = LocalTheme.current
    var tab by remember { mutableIntStateOf(0) }
    var showFilters by remember { mutableStateOf(false) }
    var showMenu by remember { mutableStateOf(false) }
    var showConnect by remember { mutableStateOf(false) }
    var trade by remember { mutableStateOf<String?>(null) }
    var position by remember { mutableStateOf<String?>(null) }
    val chrome = remember { Chrome({ showFilters = true }, { showMenu = true }, { showConnect = true }) }

    if (showConnect) {
        ConnectScreen(onSession = { c, w -> showConnect = false; Book.connect(c, w) }, onCancel = { showConnect = false })
        return
    }
    Column(Modifier.fillMaxSize()) {
        Box(Modifier.weight(1f)) {
            // a detail sits over its tab with the tab bar still below it, as on the phone
            val t0 = trade; val p0 = position
            when {
                t0 != null -> { BackHandler { trade = null }; TradeDetailScreen(t0, onBack = { trade = null }) }
                p0 != null -> { BackHandler { position = null }; HoldingDetailScreen(p0, onBack = { position = null }) }
                tab == 0 -> DashboardScreen(chrome, onTrade = { trade = it }, onTrades = { tab = 1 })
                tab == 1 -> TradesScreen(chrome, onTrade = { trade = it })
                tab == 2 -> PortfolioScreen(chrome, onHolding = { position = it })
                else -> CashflowScreen(chrome)
            }
        }
        TabBar(tab) { trade = null; position = null; tab = it }
    }
    if (showFilters) {
        ModalBottomSheet(onDismissRequest = { showFilters = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = t.bg) {
            FiltersSheet(onDone = { showFilters = false })
        }
    }
    if (showMenu) {
        ModalBottomSheet(onDismissRequest = { showMenu = false }, containerColor = t.bg) {
            MenuSheet(onConnect = { showMenu = false; showConnect = true }, onDone = { showMenu = false })
        }
    }
}

/** The iOS symbols the header and tab bar use (bag, filter, menu, gauge, list, briefcase, dollar circle), drawn as 24-pt outline vectors. */
object TabIcons {
    val bag: ImageVector by lazy { outline("bag") {
        moveTo(5f, 9f); lineTo(19f, 9f); lineTo(18f, 20f); lineTo(6f, 20f); close()
        moveTo(8.5f, 9f); lineTo(8.5f, 7.5f); arcTo(3.5f, 3.5f, 0f, false, true, 15.5f, 7.5f); lineTo(15.5f, 9f)
    } }
    val filter: ImageVector by lazy { outline("funnel") {
        moveTo(4f, 5f); lineTo(20f, 5f); lineTo(14f, 12.5f); lineTo(14f, 19f); lineTo(10f, 21f); lineTo(10f, 12.5f); close()
    } }
    val menu: ImageVector by lazy { outline("menu") {
        moveTo(4f, 7f); lineTo(20f, 7f); moveTo(4f, 12f); lineTo(20f, 12f); moveTo(4f, 17f); lineTo(20f, 17f)
    } }
    val back: ImageVector by lazy { outline("back") { moveTo(14.5f, 6f); lineTo(8.5f, 12f); lineTo(14.5f, 18f) } }
    private fun outline(name: String, draw: androidx.compose.ui.graphics.vector.PathBuilder.() -> Unit): ImageVector =
        ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).apply {
            path(fill = null, stroke = SolidColor(Color.Black), strokeLineWidth = 1.6f, strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round) { draw() }
        }.build()

    val gauge: ImageVector by lazy { outline("gauge") {
        moveTo(4.5f, 16.5f); arcTo(8.5f, 8.5f, 0f, true, true, 19.5f, 16.5f)   // the dial, open at the bottom
        moveTo(12f, 16.5f); lineTo(15.8f, 10.2f)                                  // the needle
        moveTo(6.2f, 11.5f); lineTo(6.2f, 11.5f); moveTo(17.8f, 11.5f); lineTo(17.8f, 11.5f); moveTo(12f, 7.2f); lineTo(12f, 7.2f)   // dots
    } }
    val list: ImageVector by lazy { outline("list") {
        moveTo(5f, 5f); lineTo(19f, 5f); lineTo(19f, 19f); lineTo(5f, 19f); close()
        moveTo(8f, 9.5f); lineTo(8f, 9.5f); moveTo(11f, 9.5f); lineTo(16f, 9.5f)
        moveTo(8f, 12f); lineTo(8f, 12f); moveTo(11f, 12f); lineTo(16f, 12f)
        moveTo(8f, 14.5f); lineTo(8f, 14.5f); moveTo(11f, 14.5f); lineTo(16f, 14.5f)
    } }
    val briefcase: ImageVector by lazy { outline("briefcase") {
        moveTo(3.5f, 8f); lineTo(20.5f, 8f); lineTo(20.5f, 19f); lineTo(3.5f, 19f); close()
        moveTo(9f, 8f); lineTo(9f, 5.5f); lineTo(15f, 5.5f); lineTo(15f, 8f)
        moveTo(3.5f, 12.5f); lineTo(20.5f, 12.5f)
    } }
    val dollar: ImageVector by lazy { outline("dollar") {
        moveTo(12f, 3f); arcTo(9f, 9f, 0f, true, true, 12f, 21f); arcTo(9f, 9f, 0f, true, true, 12f, 3f)
        moveTo(12f, 6.8f); lineTo(12f, 17.2f)
        moveTo(14.6f, 9.6f); curveTo(14.6f, 8.5f, 13.4f, 8.1f, 12f, 8.1f); curveTo(10.5f, 8.1f, 9.4f, 8.7f, 9.4f, 9.9f); curveTo(9.4f, 11.1f, 10.8f, 11.5f, 12f, 11.8f); curveTo(13.3f, 12.1f, 14.6f, 12.6f, 14.6f, 13.9f); curveTo(14.6f, 15.1f, 13.4f, 15.9f, 12f, 15.9f); curveTo(10.5f, 15.9f, 9.4f, 15.3f, 9.4f, 14.2f)
    } }
}

@Composable
private fun TabBar(tab: Int, onTab: (Int) -> Unit) {
    val t = LocalTheme.current
    val items = listOf("Dashboard" to TabIcons.gauge, "Trades" to TabIcons.list, "Portfolio" to TabIcons.briefcase, "Cashflow" to TabIcons.dollar)
    Column(Modifier.fillMaxWidth().background(t.surface)) {
        HorizontalDivider(color = t.hair)
        Row(Modifier.fillMaxWidth()) {
            for ((i, item) in items.withIndex()) {
                val color = if (tab == i) t.ink else t.ink55
                Column(Modifier.weight(1f).clickable { onTab(i) }.padding(bottom = 6.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Box(Modifier.fillMaxWidth().height(2.dp).background(if (tab == i) t.accent else Color.Transparent))
                    Icon(item.second, contentDescription = null, tint = color, modifier = Modifier.size(22.dp))
                    Text(item.first, fontSize = 11.sp, fontWeight = if (tab == i) FontWeight.SemiBold else FontWeight.Normal, color = color)
                }
            }
        }
    }
}

// MARK: - shared pieces

@Composable
fun Header(chrome: Chrome) {
    val t = LocalTheme.current
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(30.dp).clip(RoundedCornerShape(8.dp)).background(t.accent900), contentAlignment = Alignment.Center) {
            Icon(TabIcons.bag, contentDescription = null, tint = t.accent300, modifier = Modifier.size(16.dp))
        }
        Spacer(Modifier.width(10.dp))
        Text("Bagholder", fontSize = 19.sp, fontWeight = FontWeight.Bold, color = t.ink)
        Spacer(Modifier.width(6.dp))
        Text(Book.appVersion, fontSize = 11.sp, color = t.ink55)
        Spacer(Modifier.width(8.dp))
        Text(Book.headerStatus, fontSize = 13.sp, color = if (Book.statusIsError) t.neg else t.ink60, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f), textAlign = TextAlign.End)
        Spacer(Modifier.width(8.dp))
        Box(Modifier.size(38.dp).clip(RoundedCornerShape(9.dp)).background(t.surface).clickable { chrome.onFilters() }, contentAlignment = Alignment.Center) {
            Icon(TabIcons.filter, contentDescription = null, tint = t.ink75, modifier = Modifier.size(18.dp))
            if (Book.filters.isActive) Box(Modifier.align(Alignment.TopEnd).padding(5.dp).size(8.dp).clip(RoundedCornerShape(4.dp)).background(t.accent))
        }
        Spacer(Modifier.width(8.dp))
        Box(Modifier.size(38.dp).clip(RoundedCornerShape(9.dp)).background(t.surface).clickable { chrome.onMenu() }, contentAlignment = Alignment.Center) {
            Icon(TabIcons.menu, contentDescription = null, tint = t.ink75, modifier = Modifier.size(18.dp))
        }
    }
}

class Chip(val key: String, val field: String, val value: String)

fun filterChips(f: Filters): List<Chip> {
    val out = mutableListOf<Chip>()
    if (f.from.isNotEmpty() || f.to.isNotEmpty()) out.add(Chip("date", "Date", (f.from.ifEmpty { "…" }) + " → " + (f.to.ifEmpty { "…" })))
    else if (f.years.isNotEmpty()) out.add(Chip("date", "Date", f.years.joinToString(", ")))
    else if (f.preset != "all") out.add(Chip("date", "Date", f.preset.uppercase()))
    val names = mapOf("account" to "Account", "symbol" to "Symbol", "grade" to "Grade", "tag" to "Tag", "kind" to "Kind", "exchange" to "Exchange", "side" to "Side", "result" to "Result")
    for (k in Filters.LIST_KEYS) {
        val vals = f.lists[k] ?: emptyList()
        if (vals.isNotEmpty()) out.add(Chip("list:$k", (names[k] ?: k) + if (vals.size == 1) " is" else " in", vals.joinToString(", ")))
    }
    val rnames = mapOf("price" to "Price", "hold" to "Hold", "pnl" to "P&L", "qty" to "Qty")
    for (k in Filters.RANGE_KEYS) {
        val r = f.ranges[k] ?: continue
        val v = r.v ?: continue
        out.add(Chip("range:$k", rnames[k] ?: k, r.op + " " + Fmt.qty(v)))
    }
    if (f.search.isNotEmpty()) out.add(Chip("search", "Search", f.search))
    return out
}

fun removingChip(key: String, f: Filters): Filters {
    val g = Book.copyFilters(f)
    when {
        key == "date" -> { g.from = ""; g.to = ""; g.years = emptyList(); g.preset = "all" }
        key.startsWith("list:") -> g.lists[key.drop(5)] = emptyList()
        key.startsWith("range:") -> g.ranges[key.drop(6)]?.v = null
        key == "search" -> g.search = ""
    }
    return g
}

@Composable
fun FilterChips() {
    val t = LocalTheme.current
    val chips = filterChips(Book.filters)
    if (chips.isEmpty()) return
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        for (c in chips) {
            Row(Modifier.clip(RoundedCornerShape(8.dp)).background(t.surface).padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(c.field, fontSize = 14.sp, color = t.ink60, modifier = Modifier.padding(start = 10.dp, end = 6.dp))
                Text(c.value, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = t.chipFg,
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(t.chipBg).padding(horizontal = 8.dp, vertical = 5.dp))
                Text("×", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = t.ink55, modifier = Modifier.clickable { Book.applyFilters(removingChip(c.key, Book.filters)) }.padding(horizontal = 10.dp))
            }
        }
    }
}

@Composable
fun Card(title: String? = null, subtitle: String? = null, trailing: (@Composable () -> Unit)? = null, content: @Composable () -> Unit) {
    val t = LocalTheme.current
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(t.surface).border(1.dp, t.hair, RoundedCornerShape(12.dp)).padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (title != null || trailing != null) {
            // one header height whatever sits at the right, so cards in a row match
            Row(Modifier.fillMaxWidth().heightIn(min = 24.dp), verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    if (title != null) Text(title, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
                    if (subtitle != null) Text(subtitle, fontSize = 13.sp, color = t.ink55)
                }
                trailing?.invoke()
            }
        }
        content()
    }
}

@Composable
fun Tile(label: String, value: String, subtitle: String, color: Color? = null, modifier: Modifier = Modifier) {
    val t = LocalTheme.current
    Column(modifier.clip(RoundedCornerShape(12.dp)).background(t.surface).border(1.dp, t.hair, RoundedCornerShape(12.dp)).padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(label.uppercase(), fontSize = 11.sp, fontWeight = FontWeight.Medium, letterSpacing = 1.sp, color = t.ink55)
        Text(value, fontSize = 24.sp, fontWeight = FontWeight.Medium, color = color ?: t.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(subtitle, fontSize = 12.sp, color = t.ink60, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
fun GradeBadge(grade: String) {
    val t = LocalTheme.current
    val fg = when (grade) { "A", "B" -> t.pos; "F" -> t.neg; "C" -> t.ink75; else -> t.ink55 }
    Box(Modifier.size(30.dp).clip(RoundedCornerShape(7.dp)).background(fg.copy(alpha = 0.14f)), contentAlignment = Alignment.Center) {
        Text(grade.ifEmpty { Fmt.DASH }, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = fg)
    }
}

@Composable
fun TagChip(text: String) {
    val t = LocalTheme.current
    Text(text, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = t.chipFg, modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(t.chipBg).padding(horizontal = 8.dp, vertical = 5.dp))
}

@Composable
fun Muted(text: String) {
    Text(text, fontSize = 14.sp, color = LocalTheme.current.ink55)
}

/** The page with nothing to show (SPEC.md §4). */
@Composable
fun EmptyPage(chrome: Chrome) {
    val t = LocalTheme.current
    Column(Modifier.fillMaxSize().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        if (Book.phase == Book.Phase.Pulling) {
            Text("Pulling your history", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
            Spacer(Modifier.height(8.dp))
            Text("The first sync can take a minute.", fontSize = 15.sp, color = t.ink60)
        } else {
            Text("No activity yet", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
            Spacer(Modifier.height(8.dp))
            if (Book.connected) {
                Text("Nothing has come back from Wealthsimple yet.", fontSize = 15.sp, color = t.ink60)
                Spacer(Modifier.height(14.dp))
                Button(onClick = { Book.syncNow() }, colors = ButtonDefaults.buttonColors(containerColor = t.accent)) { Text("Sync now") }
            } else {
                Text("Connect Wealthsimple to pull your trades.", fontSize = 15.sp, color = t.ink60)
                Spacer(Modifier.height(14.dp))
                Button(onClick = chrome.onConnect, colors = ButtonDefaults.buttonColors(containerColor = t.accent)) { Text("Connect Wealthsimple") }
            }
            (Book.phase as? Book.Phase.Failed)?.let {
                Spacer(Modifier.height(14.dp))
                Text(it.message, fontSize = 14.sp, color = t.neg, textAlign = TextAlign.Center)
            }
        }
    }
}

// MARK: - Dashboard

@Composable
fun DashboardScreen(chrome: Chrome, onTrade: (String) -> Unit, onTrades: () -> Unit) {
    val t = LocalTheme.current
    val v = Book.view
    var equityPick by remember { mutableStateOf<Int?>(null) }
    var pnlPick by remember { mutableStateOf<Int?>(null) }
    Column(Modifier.fillMaxSize()) {
        Header(chrome)
        FilterChips()
        if (v == null) { EmptyPage(chrome); return }
        LazyColumn(contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { Tiles(v) }
            item {
                // the current equity at the card's top right; the pressed day's while the chart is pressed
                Card("Equity", trailing = {
                    val point = equityPick?.let { i -> v.equity.series.getOrNull(i) } ?: v.equity.series.lastOrNull()
                    if (point != null) Text(Fmt.money(point.v), fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
                }) {
                    if (v.equity.series.size > 1) EquityCurveChart(v.equity.series, equityPick, { equityPick = it }) else Muted("No equity history for this span.")
                }
            }
            // Annual returns, P&L and Grade vs P&L: one swiping row of equal cards
            item {
                PagedRow(3) { i ->
                    when (i) {
                        0 -> AnnualizedCard(v)
                        1 -> PnlCard(v, pnlPick, { pnlPick = it }, onTrades)
                        else -> Card("Grade vs P&L") { Box(Modifier.height(CARD_BODY_HEIGHT.dp)) { GradeBarsChart(v.grades, CARD_BODY_HEIGHT - 20) } }
                    }
                }
            }
            item { BySymbolCard(v, onTrades) }
            item { QueueCard(v, onTrade) }
        }
    }
}

@Composable
private fun Tiles(v: View) {
    val t = LocalTheme.current
    val k = v.kpi
    val dd = v.equity.drawdown
    val ann = v.equity.annualized
    val tiles: List<@Composable (Modifier) -> Unit> = listOf(
        { m -> Tile("Realized P&L", Fmt.money(k.realized), "${k.count} trade" + (if (k.count == 1) "" else "s"), t.signed(k.realized), m) },
        { m -> Tile("Win rate", Fmt.pct(k.winRate, signed = false), "${k.wins} W · ${k.losses} L" + if (k.breakeven > 0) " · ${k.breakeven} BE" else "", modifier = m) },
        { m -> Tile("Profit factor", Fmt.profitFactor(k), "W " + Fmt.wholeMoney(k.grossWin) + " · L " + Fmt.wholeMoney(k.grossLoss), modifier = m) },
        { m -> Tile("Expectancy", Fmt.money(k.expectancy), "avg W " + Fmt.wholeMoney(k.avgWin) + " · L " + Fmt.wholeMoney(abs(k.avgLoss)), modifier = m) },
        { m -> Tile("Max drawdown", dd.pct?.let { Fmt.pct(it) } ?: Fmt.DASH, dd.abs?.let { Fmt.compactMoney(it) + " · " + Fmt.monthAxis(dd.at) } ?: Fmt.DASH,
            dd.pct?.let { if (it < 0) t.neg else t.ink }, m) },
        { m -> Tile("Avg annualized", Fmt.pct(ann.rate), if (ann.count > 0) "over ${ann.count} year" + (if (ann.count == 1) "" else "s") else Fmt.DASH, ann.rate?.let { t.signed(it) }, m) },
    )
    TilePager(tiles)
}

/**
 * A row of full-width pages swiped sideways, with the indicator below: 4 dp dots at 24 %
 * ink, the current page a 14 × 4 accent pill that slides on swipe.
 */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
fun PagedRow(count: Int, page: @Composable (Int) -> Unit) {
    val t = LocalTheme.current
    val state = rememberPagerState(pageCount = { count })
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        HorizontalPager(state, pageSpacing = 12.dp, verticalAlignment = Alignment.Top) { i -> page(i) }
        if (count > 1) Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            for (i in 0 until count) {
                val active = i == state.currentPage
                val width by animateDpAsState(if (active) 14.dp else 4.dp, tween(200), label = "dot")
                val color by animateColorAsState(if (active) t.accent else t.ink.copy(alpha = 0.24f), tween(200), label = "dotColor")
                Box(Modifier.width(width).height(4.dp).clip(RoundedCornerShape(2.dp)).background(color))
            }
        }
    }
}

/** Two tiles per page, swiped sideways: the phone's version of the tile row. */
@Composable
fun TilePager(tiles: List<@Composable (Modifier) -> Unit>) {
    val pages = tiles.chunked(2)
    PagedRow(pages.size) { i ->
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            for (tile in pages[i]) tile(Modifier.weight(1f))
            if (pages[i].size == 1) Spacer(Modifier.weight(1f))
        }
    }
}

/** The swiping row's cards share one body height. */
const val CARD_BODY_HEIGHT = 150

@Composable
private fun AnnualizedCard(v: View) {
    val t = LocalTheme.current
    val scale = v.years.flatMap { listOf(abs(it.r), abs(it.spR ?: 0.0)) }.maxOrNull() ?: 1.0
    var pick by remember { mutableStateOf(false) }
    Card("Annual returns", trailing = {
        Box {
            Text("Vs " + v.benchmarkLabel + " ▾", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = t.ink75,
                modifier = Modifier.clip(RoundedCornerShape(7.dp)).background(t.well).clickable { pick = !pick }.padding(horizontal = 10.dp, vertical = 4.dp))
        }
    }) {
        if (pick) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for (key in listOf("SP500", "TSX", "TSX60")) {
                    Text(Model.BENCHMARK_LABELS[key] ?: key, fontSize = 13.sp, color = if (key == v.benchmarkKey) t.chipFg else t.ink75,
                        modifier = Modifier.clip(RoundedCornerShape(7.dp)).background(if (key == v.benchmarkKey) t.chipBg else t.well).clickable { Book.setBenchmark(key); pick = false }.padding(horizontal = 10.dp, vertical = 6.dp))
                }
            }
        }
        // the years scroll inside the card's fixed body
        if (v.years.isEmpty()) Box(Modifier.height(CARD_BODY_HEIGHT.dp)) { Muted("No equity history for this span.") }
        else {
            Column(Modifier.height(CARD_BODY_HEIGHT.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                for (y in v.years.reversed()) {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Row(Modifier.fillMaxWidth()) {
                            Text(y.year, fontSize = 16.sp, fontWeight = FontWeight.Medium, color = t.ink)
                            Spacer(Modifier.weight(1f))
                            Text(Fmt.pct(y.r), fontSize = 15.sp, fontWeight = FontWeight.Medium, color = t.signed(y.r))
                            Text(" / ", fontSize = 15.sp, color = t.ink55)
                            Text(Fmt.pct(y.spR), fontSize = 15.sp, fontWeight = FontWeight.Medium, color = y.spR?.let { t.signed(it) } ?: t.ink55)
                        }
                        YearPairBars(y.r, y.spR, scale)
                    }
                }
            }
        }
    }
}

/** The P&L in scope at the card's top right; the pressed month's while the chart is pressed. */
@Composable
private fun PnlCard(v: View, pick: Int?, onPickChange: (Int?) -> Unit, onTrades: () -> Unit) {
    val t = LocalTheme.current
    val value = pick?.let { v.monthly.getOrNull(it)?.value } ?: v.monthly.sumOf { it.value }
    Card("P&L", trailing = { Text(Fmt.money(value), fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = t.signed(value)) }) {
        if (v.monthly.isEmpty()) Box(Modifier.height(CARD_BODY_HEIGHT.dp)) { Muted("No closed trades in this span.") }
        else PnlBarsChart(v.monthly, pick, onPickChange, CARD_BODY_HEIGHT - 20) { m ->
            val f = Book.copyFilters(Book.filters)
            f.preset = "all"; f.years = emptyList()
            f.from = m.key + "-01"
            f.to = Model.shiftDate(Model.shiftDate(m.key + "-01", 31).take(7) + "-01", -1)
            Book.applyFilters(f)
            onTrades()
        }
    }
}

fun symbolLine(r: SymbolRow): String = "${r.n} trade" + (if (r.n == 1) "" else "s") + " · " + Fmt.pct(r.winRate, signed = false) + " win · " + Fmt.hold(r.avgHold.roundToInt()) + " avg"

@Composable
private fun BySymbolCard(v: View, onTrades: () -> Unit) {
    val t = LocalTheme.current
    val sorts = listOf("pnl" to "P&L", "n" to "Trades", "winRate" to "Win rate", "avgHold" to "Avg hold")
    var sortKey by remember { mutableStateOf("pnl") }
    var desc by remember { mutableStateOf(true) }
    var open by remember { mutableStateOf(false) }
    fun value(r: SymbolRow): Double = when (sortKey) { "n" -> r.n.toDouble(); "winRate" -> r.winRate; "avgHold" -> r.avgHold; else -> r.pnl }
    val rows = v.bySymbol.sortedWith(compareBy<SymbolRow> { if (desc) -value(it) else value(it) }.thenBy { it.symbol })
    val label = (sorts.first { it.first == sortKey }.second) + if (desc) " ▼" else " ▲"
    Card("By symbol", trailing = {
        Box {
            Text(label, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = t.ink60, modifier = Modifier.clickable { open = true }.padding(4.dp))
            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                for ((key, name) in sorts) {
                    DropdownMenuItem(text = { Text(name + if (key == sortKey) (if (desc) "  ▼" else "  ▲") else "") }, onClick = {
                        if (sortKey == key) desc = !desc else { sortKey = key; desc = true }
                        open = false
                    })
                }
            }
        }
    }) {
        if (rows.isEmpty()) Muted("No closed trades in this span.")
        Column {
            for ((i, r) in rows.take(12).withIndex()) {
                Row(Modifier.fillMaxWidth().clickable {
                    val f = Book.copyFilters(Book.filters)
                    f.lists["symbol"] = listOf(r.symbol)
                    Book.applyFilters(f)
                    onTrades()
                }.padding(top = if (i == 0) 0.dp else 12.dp, bottom = if (i == minOf(rows.size, 12) - 1) 0.dp else 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(r.symbol, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
                        Text(symbolLine(r), fontSize = 13.sp, color = t.ink60)
                    }
                    Text(Fmt.wholeMoney(r.pnl), fontSize = 17.sp, fontWeight = FontWeight.Medium, color = t.signed(r.pnl))
                }
                if (i < minOf(rows.size, 12) - 1) HorizontalDivider(color = t.hair)
            }
        }
    }
}

@Composable
private fun QueueCard(v: View, onTrade: (String) -> Unit) {
    val t = LocalTheme.current
    Card("Review queue") {
        if (v.queue.isEmpty()) Muted("Every closed trade has a grade and a thesis.")
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            for (q in v.queue.take(8)) {
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(t.well).border(1.dp, t.hair, RoundedCornerShape(10.dp)).clickable { onTrade(q.id) }.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(q.symbol, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
                        Text(q.date + " · " + q.missing.replaceFirstChar { it.uppercase() }, fontSize = 13.sp, color = t.ink60)
                    }
                    Text(Fmt.money(q.pnl), fontSize = 17.sp, fontWeight = FontWeight.Medium, color = t.signed(q.pnl))
                }
            }
        }
    }
}

// MARK: - Trades

enum class TradeSort(val label: String) { CLOSE("Close date"), OPEN("Open date"), PNL("P&L"), PNL_PCT("P&L %"), HOLD("Hold"), SYMBOL("Symbol") }

@Composable
fun TradesScreen(chrome: Chrome, onTrade: (String) -> Unit) {
    val t = LocalTheme.current
    val v = Book.view
    var sort by remember { mutableStateOf(TradeSort.CLOSE) }
    var ascending by remember { mutableStateOf(false) }
    var pickSort by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize()) {
        Header(chrome)
        FilterChips()
        if (v == null) { EmptyPage(chrome); return }
        val trades = sortTrades(v.trades, sort, ascending)
        LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
            item {
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("${trades.size} closed · sorted by ${sort.label.lowercase()}", fontSize = 14.sp, color = t.ink60, modifier = Modifier.weight(1f))
                    Text((if (ascending) "↑ " else "↓ ") + "Sort", fontSize = 14.sp, fontWeight = FontWeight.Medium, color = t.ink75,
                        modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(t.surface).border(1.dp, t.hair, RoundedCornerShape(8.dp)).clickable { pickSort = !pickSort }.padding(horizontal = 12.dp, vertical = 8.dp))
                }
                if (pickSort) {
                    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        for (s in TradeSort.values()) {
                            Text(s.label, fontSize = 13.sp, color = if (s == sort) t.chipFg else t.ink75,
                                modifier = Modifier.clip(RoundedCornerShape(7.dp)).background(if (s == sort) t.chipBg else t.well).clickable { if (sort == s) ascending = !ascending else { sort = s; ascending = false }; pickSort = false }.padding(horizontal = 10.dp, vertical = 6.dp))
                        }
                    }
                }
            }
            items(trades, key = { it.id }) { tr ->
                TradeCard(tr, onClick = { onTrade(tr.id) })
                HorizontalDivider(color = t.hair, modifier = Modifier.padding(horizontal = 16.dp))
            }
            if (trades.isEmpty()) item { Box(Modifier.fillMaxWidth().padding(top = 40.dp), contentAlignment = Alignment.Center) { Muted(if (v.tradeTotal == 0) "No closed trades yet." else "No closed trades match these filters.") } }
        }
    }
}

fun sortTrades(trades: List<Trade>, sort: TradeSort, ascending: Boolean): List<Trade> {
    val s = when (sort) {
        TradeSort.CLOSE -> trades.sortedWith(compareBy({ it.exitDate }, { it.id }))
        TradeSort.OPEN -> trades.sortedWith(compareBy({ it.entryDate }, { it.id }))
        TradeSort.PNL -> trades.sortedBy { it.pnlCad }
        TradeSort.PNL_PCT -> trades.sortedBy { it.pnlPct ?: -1e18 }
        TradeSort.HOLD -> trades.sortedBy { it.holdDays }
        TradeSort.SYMBOL -> trades.sortedWith(compareBy({ it.symbol }, { it.exitDate }))
    }
    return if (ascending) s else s.reversed()
}

@Composable
fun TradeCard(tr: Trade, onClick: () -> Unit) {
    val t = LocalTheme.current
    val color = t.signed(tr.pnl)
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
        Row(Modifier.fillMaxWidth()) {
            Text(tr.symbol, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = t.ink, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            Text(Fmt.money(tr.pnl), fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = color)
        }
        Row(Modifier.fillMaxWidth()) {
            Text(tr.entryDate + " → " + tr.exitDate, fontSize = 14.sp, color = t.ink60, modifier = Modifier.weight(1f))
            Text(Fmt.pct(tr.pnlPct), fontSize = 14.sp, color = color)
        }
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(Fmt.hold(tr.holdDays) + " · " + Fmt.price(tr.entry) + " → " + Fmt.price(tr.exit) + " · " + tr.currency, fontSize = 14.sp, color = t.ink60, modifier = Modifier.weight(1f))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                for (tag in tr.tags.take(2)) TagChip(tag)
                GradeBadge(tr.grade)
            }
        }
    }
}

@Composable
fun DetailBar(title: String, onBack: () -> Unit) {
    val t = LocalTheme.current
    Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        Box(Modifier.size(38.dp).clip(RoundedCornerShape(19.dp)).background(t.surface).clickable(onClick = onBack).align(Alignment.CenterStart), contentAlignment = Alignment.Center) {
            Icon(TabIcons.back, contentDescription = null, tint = t.ink, modifier = Modifier.size(18.dp))
        }
        Text(title, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = t.ink, modifier = Modifier.align(Alignment.Center))
    }
}

@Composable
fun Facts(rows: List<Pair<String, String>>, colorOf: ((String) -> Color)? = null) {
    val t = LocalTheme.current
    Column {
        for ((i, r) in rows.withIndex()) {
            Row(Modifier.fillMaxWidth().padding(vertical = 7.dp)) {
                Text(r.first, fontSize = 14.sp, color = t.ink60, modifier = Modifier.weight(1f))
                Text(r.second, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = colorOf?.invoke(r.first) ?: t.ink, textAlign = TextAlign.End)
            }
            if (i < rows.size - 1) HorizontalDivider(color = t.hair)
        }
    }
}

@Composable
fun NoteField(value: String, placeholder: String, onChange: (String) -> Unit, single: Boolean = false, capitalize: Boolean = false) {
    val t = LocalTheme.current
    Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(t.well).padding(10.dp)) {
        if (value.isEmpty()) Text(placeholder, fontSize = 15.sp, color = t.ink55)
        BasicTextField(value, onChange, textStyle = TextStyle(color = t.ink, fontSize = 15.sp), cursorBrush = SolidColor(t.accent), singleLine = single,
            keyboardOptions = KeyboardOptions(capitalization = if (capitalize) KeyboardCapitalization.Sentences else KeyboardCapitalization.None))
    }
}

@Composable
fun TradeDetailScreen(tradeId: String, onBack: () -> Unit) {
    val t = LocalTheme.current
    val tr = Book.trade(tradeId)
    if (tr == null) { Column(Modifier.fillMaxSize()) { DetailBar("Trade", onBack); Muted("This trade is no longer in the book.") }; return }
    var chart by remember { mutableStateOf<Triple<List<Bar>, String, String>?>(null) }
    var timeframe by remember { mutableStateOf<String?>(null) }
    var grade by remember { mutableStateOf(tr.grade) }
    var thesis by remember { mutableStateOf(tr.thesis) }
    var tags by remember { mutableStateOf(tr.tags.joinToString(", ")) }
    fun save() { Book.saveJournal(tradeId, JournalEntry(grade, thesis, tags.split(",").map { it.trim() }.filter { it.isNotEmpty() })) }
    LaunchedEffect(tradeId, timeframe) { chart = withContext(Dispatchers.IO) { MarketData.bars(tr, timeframe) } }
    Column(Modifier.fillMaxSize()) {
        DetailBar("Trade", onBack)
        LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            item {
                Text(tr.symbol, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = t.ink)
                val parts = mutableListOf<String>()
                if (tr.name.isNotEmpty() && tr.name != tr.symbol) parts.add(tr.name)
                val ticker = Model.listingTicker(tr.underlying)
                if (tr.exchange.isNotEmpty()) parts.add(tr.exchange.uppercase() + ": " + ticker) else if (tr.underlying != tr.symbol) parts.add(ticker)
                Text(parts.joinToString(" · "), fontSize = 14.sp, color = t.ink60)
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(Fmt.money(tr.pnl), fontSize = 28.sp, fontWeight = FontWeight.SemiBold, color = t.signed(tr.pnl))
                    Text(Fmt.pct(tr.pnlPct), fontSize = 17.sp, fontWeight = FontWeight.Medium, color = t.signed(tr.pnl), modifier = Modifier.padding(bottom = 4.dp))
                    Text(tr.currency, fontSize = 13.sp, color = t.ink55, modifier = Modifier.padding(bottom = 6.dp))
                }
            }
            item {
                Card {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        for (tf in listOf("1d", "1w", "1M")) {
                            val on = (chart?.third ?: timeframe) == tf
                            Text(tf.uppercase(), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = if (on) t.chipFg else t.ink55,
                                modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(if (on) t.chipBg else t.well).clickable { timeframe = tf }.padding(horizontal = 9.dp, vertical = 5.dp))
                        }
                    }
                    val c = chart
                    if (c != null && c.first.isNotEmpty()) CandleChart(c.first, tr.fills, atClose = tr.kind == "Options")
                    else Box(Modifier.fillMaxWidth().height(120.dp), contentAlignment = Alignment.Center) { Muted(c?.second ?: "Fetching bars…") }
                }
            }
            item {
                Card {
                    Facts(listOf(
                        "Open" to tr.entryDate, "Close" to tr.exitDate, "Entry" to Fmt.price(tr.entry), "Exit" to Fmt.price(tr.exit),
                        "Qty" to (Fmt.qty(tr.qty) + if (tr.mult > 1) " × ${tr.mult.toInt()}" else ""), "Hold" to Fmt.hold(tr.holdDays), "Account" to tr.account,
                        "P&L (CAD)" to Fmt.money(tr.pnlCad),
                    ))
                }
            }
            item {
                Card("Executions") {
                    Column {
                        for ((i, f) in tr.fills.withIndex()) {
                            Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(f.date + if (f.time.isEmpty()) "" else " " + f.time, fontSize = 14.sp, color = t.ink)
                                    Text(f.sub + " · " + Fmt.qty(abs(f.qty)) + " · " + f.currency + " " + Fmt.price(f.price), fontSize = 13.sp, color = t.ink60)
                                }
                                Text(Fmt.money(f.amount), fontSize = 15.sp, fontWeight = FontWeight.Medium, color = t.signed(f.amount))
                            }
                            if (i < tr.fills.size - 1) HorizontalDivider(color = t.hair)
                        }
                    }
                }
            }
            item {
                Card("Journal") {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        for (g in Model.GRADES) {
                            Box(Modifier.size(44.dp, 36.dp).clip(RoundedCornerShape(8.dp)).background(if (grade == g) t.chipBg else t.well).clickable { grade = if (grade == g) "" else g; save() }, contentAlignment = Alignment.Center) {
                                Text(g, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = if (grade == g) t.chipFg else t.ink75)
                            }
                        }
                    }
                    NoteField(thesis, "Thesis", { thesis = it; save() }, capitalize = true)
                    NoteField(tags, "Tags, comma separated", { tags = it; save() }, single = true)
                }
            }
        }
    }
}

// MARK: - Portfolio

/** A holding opens the page a trade opens, with the position standing in for the trade:
 *  no close date, the current price as the exit, the days so far as the hold. */
fun holdingAsTrade(p: Position): Trade = Trade().apply {
    id = p.id; status = "open"; symbol = p.symbol; underlying = p.underlying; name = p.name; exchange = p.exchange; kind = p.kind; currency = p.currency
    account = p.account; accountId = p.accountId; securityId = p.securityId
    side = if (p.short) "COVER" else "SELL"; openDirection = if (p.short) "SHORT" else "LONG"
    qty = p.qty; mult = p.mult; entry = p.avg; exit = p.last
    entryDate = p.opened; exitDate = Model.todayLocal(); holdDays = p.held
    pnl = p.unreal; pnlPct = p.unrealPct; fills = p.fills
    grade = p.grade; thesis = p.thesis; tags = p.tags
}

@Composable
private fun PortfolioTiles(pf: com.bagholder.model.Portfolio) {
    val t = LocalTheme.current
    val n = pf.positionCount
    val positions = "$n position" + if (n == 1) "" else "s"
    val unavailable = pf.availableMarginUnavailable
    val tiles = listOf<@Composable (Modifier) -> Unit>(
        { m -> Tile("Market value", Fmt.wholeMoney(pf.marketValue), "across $n open position" + (if (n == 1) "" else "s"), modifier = m) },
        { m -> Tile("Net asset value", pf.nav?.let { Fmt.wholeMoney(it) } ?: "—", if (pf.nav == null) "—" else "${pf.navAccounts} account" + (if (pf.navAccounts == 1) "" else "s") + ", " + positions, modifier = m) },
        { m -> Tile("Cost basis", Fmt.wholeMoney(pf.costBasis), "Total book value", modifier = m) },
        { m -> Tile("Margin used", Fmt.wholeMoney(pf.marginUsed), pf.marginUsedPct?.let { Fmt.pct(it, 1, false) + " of market value" } ?: "—", modifier = m) },
        { m -> Tile("Available margin", pf.availableMargin?.let { Fmt.wholeMoney(it) } ?: "—",
            if (unavailable.isNotEmpty()) "unavailable for " + unavailable.joinToString(", ") else if (pf.availableMargin == null) "—" else "buying power", modifier = m) },
        { m -> Tile("Unrealized P&L", Fmt.signedMoney(pf.unrealized), pf.unrealizedPct?.let { Fmt.pct(it) + if (pf.unrealized >= 0) " gain" else " loss" } ?: "—", color = t.signed(pf.unrealized), modifier = m) },
    )
    TilePager(tiles)
}

@Composable
fun PortfolioScreen(chrome: Chrome, onHolding: (String) -> Unit) {
    val t = LocalTheme.current
    val v = Book.view
    var picked by remember { mutableStateOf<Int?>(null) }
    Column(Modifier.fillMaxSize()) {
        Header(chrome)
        FilterChips()
        if (v == null) { EmptyPage(chrome); return }
        val pf = v.portfolio
        LazyColumn(contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { PortfolioTiles(pf) }
            item {
                val shown = if (pf.allocation.size > 10) 10 else pf.allocation.size
                val top = pf.allocation.take(shown)
                val rest = pf.allocation.drop(shown)
                val items = top.map { Pair(it.symbol, it.value) } + (if (rest.isNotEmpty()) listOf(Pair("Other (${rest.size})", rest.sumOf { it.value })) else emptyList())
                val total = items.sumOf { it.second }
                Card("Allocation") {
                    if (items.isEmpty()) Muted("No open positions in scope.")
                    else Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                        DonutChart(items, picked, { picked = it }, centre = pf.marketValue)
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            for ((i, s) in items.withIndex()) {
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Box(Modifier.size(8.dp).clip(RoundedCornerShape(4.dp)).background(t.pie[i % t.pie.size]))
                                    Text(s.first, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = t.ink, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                                    Text(Fmt.pct(if (total > 0) s.second / total else null, signed = false), fontSize = 13.sp, color = t.ink60)
                                }
                            }
                        }
                    }
                }
            }
            item {
                val rows = v.positions.sortedByDescending { it.unreal }
                Card("Holdings") {
                    if (rows.isEmpty()) Muted("No open positions match these filters.")
                    Column {
                        for ((i, p) in rows.withIndex()) {
                            HoldingRow(p) { onHolding(p.id) }
                            if (i < rows.size - 1) HorizontalDivider(color = t.hair)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Readout(label: String, value: String, color: Color) {
    val t = LocalTheme.current
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, fontSize = 11.sp, color = t.ink55)
        Text(value, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = color)
    }
}

@Composable
private fun Legend(color: Color, label: String) {
    val t = LocalTheme.current
    Row(horizontalArrangement = Arrangement.spacedBy(5.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(8.dp).clip(RoundedCornerShape(2.dp)).background(color))
        Text(label, fontSize = 11.sp, color = t.ink60)
    }
}

/** The month's margin interest, CAD, from the Interest charge rows in scope. */
private fun interestByMonth(cf: com.bagholder.model.CashflowView): Map<String, Double> {
    val out = LinkedHashMap<String, Double>()
    for (r in cf.other) if (r.kind == "Interest charge") out[r.date.take(7)] = (out[r.date.take(7)] ?: 0.0) - r.amountCad
    return out
}

@Composable
fun HoldingRow(p: Position, onClick: () -> Unit) {
    val t = LocalTheme.current
    val dc = p.dayChange
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(p.symbol + (if (p.short) " SHORT" else ""), fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = t.ink, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            Text(Fmt.signedMoney(p.unreal), fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = t.signed(p.unreal))
        }
        Row(Modifier.fillMaxWidth()) {
            Text(p.account + " · Book " + Fmt.wholeMoney(p.cost) + " · Market " + Fmt.wholeMoney(p.mv), fontSize = 13.sp, color = t.ink60, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            Text(Fmt.pct(p.unrealPct), fontSize = 13.sp, color = t.signed(p.unreal))
        }
        Row(Modifier.fillMaxWidth()) {
            Text("Today", fontSize = 13.sp, color = t.ink55, modifier = Modifier.weight(1f))
            Text(if (dc == null) "—" else Fmt.signedMoney(dc) + " · " + Fmt.pct((p.percentChange ?: 0.0) / 100, 2), fontSize = 13.sp, color = if (dc == null) t.ink55 else t.signed(dc))
        }
    }
}

@Composable
fun HoldingDetailScreen(positionId: String, onBack: () -> Unit) {
    val t = LocalTheme.current
    val p = Book.position(positionId)
    if (p == null) { Column(Modifier.fillMaxSize()) { DetailBar("Holding", onBack); Muted("This position is no longer open.") }; return }
    val tr = holdingAsTrade(p)
    var chart by remember { mutableStateOf<Triple<List<Bar>, String, String>?>(null) }
    var timeframe by remember { mutableStateOf<String?>(null) }
    var grade by remember { mutableStateOf(p.grade) }
    var thesis by remember { mutableStateOf(p.thesis) }
    var tags by remember { mutableStateOf(p.tags.joinToString(", ")) }
    fun save() { Book.saveJournal(positionId, JournalEntry(grade, thesis, tags.split(",").map { it.trim() }.filter { it.isNotEmpty() })) }
    LaunchedEffect(positionId, timeframe) { chart = withContext(Dispatchers.IO) { MarketData.bars(tr, timeframe) } }
    Column(Modifier.fillMaxSize()) {
        DetailBar("Holding", onBack)
        LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            item {
                Text(tr.symbol, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = t.ink)
                val parts = mutableListOf<String>()
                if (tr.name.isNotEmpty() && tr.name != tr.symbol) parts.add(tr.name)
                val ticker = Model.listingTicker(tr.underlying)
                if (tr.exchange.isNotEmpty()) parts.add(tr.exchange.uppercase() + ": " + ticker) else if (tr.underlying != tr.symbol) parts.add(ticker)
                Text(parts.joinToString(" · "), fontSize = 14.sp, color = t.ink60)
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(Fmt.money(tr.pnl), fontSize = 28.sp, fontWeight = FontWeight.SemiBold, color = t.signed(tr.pnl))
                    Text(Fmt.pct(tr.pnlPct), fontSize = 17.sp, fontWeight = FontWeight.Medium, color = t.signed(tr.pnl), modifier = Modifier.padding(bottom = 4.dp))
                    Text(tr.currency, fontSize = 13.sp, color = t.ink55, modifier = Modifier.padding(bottom = 6.dp))
                }
            }
            item {
                Card {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        for (tf in listOf("1d", "1w", "1M")) {
                            val on = (chart?.third ?: timeframe) == tf
                            Text(tf.uppercase(), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = if (on) t.chipFg else t.ink55,
                                modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(if (on) t.chipBg else t.well).clickable { timeframe = tf }.padding(horizontal = 9.dp, vertical = 5.dp))
                        }
                    }
                    val c = chart
                    if (c != null && c.first.isNotEmpty()) CandleChart(c.first, tr.fills, atClose = tr.kind == "Options")
                    else Box(Modifier.fillMaxWidth().height(120.dp), contentAlignment = Alignment.Center) { Muted(c?.second ?: "Fetching bars…") }
                }
            }
            item {
                Card {
                    Facts(listOf(
                        "Open" to tr.entryDate, "Close" to "", "Entry" to Fmt.price(tr.entry), "Exit" to Fmt.price(tr.exit),
                        "Qty" to (Fmt.qty(tr.qty) + if (tr.mult > 1) " × ${tr.mult.toInt()}" else ""), "Hold" to Fmt.hold(tr.holdDays), "Account" to tr.account,
                    ))
                }
            }
            item {
                Card("Executions") {
                    Column {
                        for ((i, f) in tr.fills.withIndex()) {
                            Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(f.date + if (f.time.isEmpty()) "" else " " + f.time, fontSize = 14.sp, color = t.ink)
                                    Text(f.sub + " · " + Fmt.qty(abs(f.qty)) + " · " + f.currency + " " + Fmt.price(f.price), fontSize = 13.sp, color = t.ink60)
                                }
                                Text(Fmt.money(f.amount), fontSize = 15.sp, fontWeight = FontWeight.Medium, color = t.signed(f.amount))
                            }
                            if (i < tr.fills.size - 1) HorizontalDivider(color = t.hair)
                        }
                    }
                }
            }
            item {
                Card("Journal") {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        for (g in Model.GRADES) {
                            Box(Modifier.size(44.dp, 36.dp).clip(RoundedCornerShape(8.dp)).background(if (grade == g) t.chipBg else t.well).clickable { grade = if (grade == g) "" else g; save() }, contentAlignment = Alignment.Center) {
                                Text(g, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = if (grade == g) t.chipFg else t.ink75)
                            }
                        }
                    }
                    NoteField(thesis, "Thesis", { thesis = it; save() }, capitalize = true)
                    NoteField(tags, "Tags, comma separated", { tags = it; save() }, single = true)
                }
            }
        }
    }
}

// MARK: - Cashflow

fun rateLine(h: Holding): String {
    var s = Fmt.qty(h.qty) + " · avg " + Fmt.price(h.avg) + " · " + Fmt.perUnit(h.per)
    h.freq?.let { s += " × $it" }
    if (!h.freqVerified) s += " assumed"
    return s
}

@Composable
fun CashflowScreen(chrome: Chrome) {
    val t = LocalTheme.current
    val v = Book.view
    var picked by remember { mutableStateOf<Int?>(null) }
    var distPick by remember { mutableStateOf<Int?>(null) }
    Column(Modifier.fillMaxSize()) {
        Header(chrome)
        FilterChips()
        if (v == null) { EmptyPage(chrome); return }
        val cf = v.cashflow
        LazyColumn(contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (cf.skippedFilters.isNotEmpty()) item { Text("Ignoring " + cf.skippedFilters.joinToString(", ") + ".", fontSize = 13.sp, color = t.ink55) }
            item { CashflowTiles(cf) }
            item {
                // the projected month at the card's top right; the pressed month's distributions,
                // margin interest and net while the chart is pressed
                val projected = cf.holdings.sumOf { (it.annual ?: 0.0) / 12 }
                val interest = interestByMonth(cf)
                val picked = distPick?.let { cf.months.getOrNull(it) }
                Card("Cashflow", trailing = {
                    if (picked != null) {
                        val intr = interest[picked.key] ?: 0.0
                        Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(1.dp)) {
                            Readout("Distributions", Fmt.money(picked.value), t.ink)
                            Readout("Margin interest", Fmt.money(if (intr > 0) -intr else 0.0), t.neg)
                            Readout("Net", Fmt.signedMoney(picked.value - intr), t.signed(picked.value - intr))
                        }
                    } else Text(Fmt.money(projected), fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
                }) {
                    if (cf.months.isEmpty()) Muted("No distributions in this span.")
                    else Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp, Alignment.End), verticalAlignment = Alignment.CenterVertically) {
                            Legend(t.accent, "Distributions")
                            Legend(t.neg, "Margin interest")
                        }
                        PnlBarsChart(cf.months.map { m -> com.bagholder.model.MonthBucket(m.key, m.label).apply { value = m.value; count = m.count } }, distPick, { distPick = it }, color = t.accent,
                            overlay = cf.months.map { interest[it.key] ?: 0.0 })
                    }
                }
            }
            item {
                val items = cf.holdings.map { h ->
                    Pair(h.symbol + if (cf.holdings.count { it.symbol == h.symbol } > 1) " · " + h.account else "", (h.annual ?: 0.0) / 12)
                }.filter { it.second > 0 }.sortedByDescending { it.second }
                val total = items.sumOf { it.second }
                Card("Allocation") {
                    if (items.isEmpty()) Muted("No income holdings in scope.")
                    else Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                        DonutChart(items, picked, { picked = it })
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            for ((i, s) in items.take(8).withIndex()) {
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Box(Modifier.size(8.dp).clip(RoundedCornerShape(4.dp)).background(t.pie[i % t.pie.size]))
                                    Text(s.first, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = t.ink, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                                    Text(Fmt.pct(if (total > 0) s.second / total else null, signed = false), fontSize = 13.sp, color = t.ink60)
                                }
                            }
                        }
                    }
                }
            }
            item {
                Card("Positions") {
                    if (cf.holdings.isEmpty()) Muted("No income holdings in scope.")
                    Column {
                        for ((i, h) in cf.holdings.withIndex()) {
                            Column(Modifier.padding(top = if (i == 0) 0.dp else 10.dp, bottom = if (i == cf.holdings.size - 1) 0.dp else 10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                // the month's projected payout at the right with the yield on cost under it
                                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
                                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                        Text(h.symbol, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
                                        Text(rateLine(h), fontSize = 13.sp, color = t.ink60)
                                    }
                                    Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                        Text(h.annual?.let { Fmt.money(it / 12) + " / mo" } ?: Fmt.DASH, fontSize = 15.sp, fontWeight = FontWeight.Medium, color = t.ink)
                                        Text(Fmt.pct(h.yoc, 2, false), fontSize = 13.sp, color = t.ink60)
                                    }
                                }
                                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                    Fact("Ex-Div", h.nextExDate.ifEmpty { Fmt.DASH }, h.exPast)
                                    Fact("Pay Day", h.nextPayDate.ifEmpty { Fmt.DASH }, h.payPast)
                                }
                            }
                            if (i < cf.holdings.size - 1) HorizontalDivider(color = t.hair)
                        }
                    }
                }
            }
            item {
                Card("History") {
                    if (cf.rows.isEmpty()) Muted("No distributions in this span.")
                    Column {
                        for ((i, r) in cf.rows.take(60).withIndex()) {
                            Row(Modifier.fillMaxWidth().padding(top = if (i == 0) 0.dp else 9.dp, bottom = if (i == minOf(cf.rows.size, 60) - 1) 0.dp else 9.dp), verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(r.symbol, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
                                    var line = r.date
                                    r.qty?.let { line += " · " + Fmt.qty(it) + " × " + Fmt.perUnit(r.per) }
                                    Text(line, fontSize = 13.sp, color = t.ink60, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                                Column(horizontalAlignment = Alignment.End) {
                                    Text(Fmt.money(r.amount), fontSize = 15.sp, fontWeight = FontWeight.Medium, color = t.ink)
                                    Text(r.currency, fontSize = 12.sp, color = t.ink55)
                                }
                            }
                            if (i < minOf(cf.rows.size, 60) - 1) HorizontalDivider(color = t.hair)
                        }
                    }
                }
            }
        }
    }
}

/** YTD and Yield on cost first, then All time with Margin used (or Last 12 months), then the past years. */
@Composable
private fun CashflowTiles(cf: CashflowView) {
    val ytd = cf.tiles.firstOrNull { it.label.endsWith("YTD") }
    val yoc = cf.tiles.firstOrNull { it.label == "Yield on cost" }
    val all = cf.tiles.firstOrNull { it.label == "All time" }
    val margin = cf.tiles.firstOrNull { it.label == "Margin used" || it.label == "Last 12 months" }
    val fixed = setOf("Yield on cost", "All time", "Margin used", "Last 12 months")
    val years = cf.tiles.filter { !it.label.endsWith("YTD") && it.label !in fixed }.reversed()
    val ordered = listOfNotNull(ytd, yoc, all, margin) + years
    val tiles = mutableListOf<@Composable (Modifier) -> Unit>()
    for (tile in ordered) {
        tiles.add { m ->
            if (tile.label == "Yield on cost") Tile(tile.label, Fmt.pct(tile.yield, 2, false), Fmt.money(tile.projected) + " / mo", modifier = m)
            else if (tile.label == "Margin used") Tile(tile.label, Fmt.wholeMoney(tile.marginUsed ?: 0.0), Fmt.wholeMoney(tile.interestPerMonth ?: 0.0) + "/mo margin interest", modifier = m)
            else Tile(tile.label, Fmt.money(tile.total), if (tile.label == "All time") "total earned" else Fmt.money(tile.perMonth) + " / month", modifier = m)
        }
    }
    TilePager(tiles)
}

@Composable
private fun Fact(label: String, value: String, muted: Boolean = false) {
    val t = LocalTheme.current
    Column(verticalArrangement = Arrangement.spacedBy(1.dp)) {
        Text(label.uppercase(), fontSize = 10.sp, fontWeight = FontWeight.Medium, letterSpacing = 0.6.sp, color = t.ink55)
        Text(value, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = if (muted) t.ink55 else t.ink)
    }
}

// MARK: - the filter sheet

private val FIELD_NAMES = mapOf("symbol" to "Symbol", "account" to "Account", "grade" to "Grade", "tag" to "Tag", "side" to "Side", "kind" to "Kind", "exchange" to "Exchange", "result" to "Result")
private val FIELD_ORDER = listOf("symbol", "account", "grade", "tag", "side", "kind", "exchange", "result")

private fun values(field: String, o: Options): List<String> = when (field) {
    "symbol" -> o.symbols; "account" -> o.accounts; "grade" -> o.grades; "tag" -> o.tags
    "side" -> o.sides; "kind" -> o.kinds; "exchange" -> o.exchanges; "result" -> o.results; else -> emptyList()
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun FiltersSheet(onDone: () -> Unit) {
    val t = LocalTheme.current
    val o = Book.view?.options ?: Options(emptyList(), emptyList(), emptyList(), emptyList(), emptyList(), Model.GRADES + "Ungraded", listOf("SELL", "COVER"), listOf("Winners", "Losers", "Breakeven"), emptyList())
    var draft by remember { mutableStateOf(Book.copyFilters(Book.filters)) }
    var query by remember { mutableStateOf("") }
    var tick by remember { mutableIntStateOf(0) }
    fun changed() { tick += 1 }
    fun toggle(field: String, value: String) {
        val vals = (draft.lists[field] ?: emptyList()).toMutableList()
        if (!vals.remove(value)) vals.add(value)
        draft.lists[field] = vals
        changed()
    }
    fun hasMatches(q: String) = FIELD_ORDER.any { f -> values(f, o).any { it.uppercase().contains(q.uppercase()) } }
    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("Clear all", fontSize = 15.sp, color = t.accent, modifier = Modifier.clickable { draft = Filters().also { it.benchmark = Book.filters.benchmark }; changed() }.padding(8.dp))
            Spacer(Modifier.weight(1f))
            Text("Filters", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
            Spacer(Modifier.weight(1f))
            Text("Done", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = t.accent, modifier = Modifier.clickable {
                if (query.isNotEmpty() && !hasMatches(query)) draft.search = query
                Book.applyFilters(draft); onDone()
            }.padding(8.dp))
        }
        Spacer(Modifier.height(8.dp))
        // the search takes focus as the sheet opens, as on the phone
        val searchFocus = remember { FocusRequester() }
        LaunchedEffect(Unit) { searchFocus.requestFocus() }
        Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(t.well).padding(10.dp)) {
            if (query.isEmpty()) Text("Search symbols, accounts, tags…", fontSize = 16.sp, color = t.ink55)
            BasicTextField(query, { query = it }, textStyle = TextStyle(color = t.ink, fontSize = 16.sp), cursorBrush = SolidColor(t.accent), singleLine = true,
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters), modifier = Modifier.focusRequester(searchFocus))
        }
        Spacer(Modifier.height(12.dp))
        key(tick) {
            if (query.isNotEmpty()) {
                val q = query.uppercase()
                val rows = FIELD_ORDER.flatMap { f -> values(f, o).filter { it.uppercase().contains(q) }.map { f to it } }
                LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
                    if (rows.isEmpty()) item { Muted("No value matches. Done searches for \"$query\".") }
                    items(rows) { (f, value) ->
                        val on = (draft.lists[f] ?: emptyList()).contains(value)
                        Row(Modifier.fillMaxWidth().background(if (on) t.well else Color.Transparent).clickable { toggle(f, value) }.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.width(3.dp).height(20.dp).background(if (on) t.chipFg else Color.Transparent))
                            Spacer(Modifier.width(10.dp))
                            Text(value, fontSize = 16.sp, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal, color = t.ink, modifier = Modifier.weight(1f))
                            Text(FIELD_NAMES[f] ?: f, fontSize = 13.sp, color = t.ink55)
                        }
                    }
                }
            } else {
                LazyColumn(contentPadding = PaddingValues(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
                    item {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("DATE", fontSize = 11.sp, fontWeight = FontWeight.Medium, letterSpacing = 1.sp, color = t.ink55)
                            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                for (p in listOf("all", "1d", "1w", "1m", "3m", "6m", "ytd", "1y", "5y")) {
                                    Pill(p.uppercase(), draft.preset == p && draft.years.isEmpty() && draft.from.isEmpty() && draft.to.isEmpty()) { draft.preset = p; draft.years = emptyList(); draft.from = ""; draft.to = ""; changed() }
                                }
                                for (y in o.years) {
                                    Pill(y, draft.years.contains(y)) {
                                        draft.years = (if (draft.years.contains(y)) draft.years - y else draft.years + y).sorted()
                                        draft.preset = "all"; draft.from = ""; draft.to = ""; changed()
                                    }
                                }
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                DateField("From", draft.from) { draft.from = it; if (it.length == 10) { draft.preset = "all"; draft.years = emptyList() }; changed() }
                                DateField("To", draft.to) { draft.to = it; if (it.length == 10) { draft.preset = "all"; draft.years = emptyList() }; changed() }
                            }
                        }
                    }
                    for (f in FIELD_ORDER) {
                        val vals = values(f, o)
                        if (vals.isEmpty()) continue
                        item {
                            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text((FIELD_NAMES[f] ?: f).uppercase(), fontSize = 11.sp, fontWeight = FontWeight.Medium, letterSpacing = 1.sp, color = t.ink55)
                                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                    for (value in vals) Pill(value, (draft.lists[f] ?: emptyList()).contains(value)) { toggle(f, value) }
                                }
                            }
                        }
                    }
                    item {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("RANGES", fontSize = 11.sp, fontWeight = FontWeight.Medium, letterSpacing = 1.sp, color = t.ink55)
                            for ((k, name) in listOf("price" to "Price", "hold" to "Hold", "pnl" to "P&L", "qty" to "Qty")) {
                                val r = draft.ranges[k]!!
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Text(name, fontSize = 15.sp, color = t.ink, modifier = Modifier.width(56.dp))
                                    Pill(">", r.op == ">") { r.op = ">"; changed() }
                                    Pill("<", r.op == "<") { r.op = "<"; changed() }
                                    var text by remember(k) { mutableStateOf(r.v?.let { Fmt.qty(it).replace(",", "") } ?: "") }
                                    Box(Modifier.weight(1f).clip(RoundedCornerShape(8.dp)).background(t.well).padding(8.dp)) {
                                        if (text.isEmpty()) Text("value", fontSize = 15.sp, color = t.ink55)
                                        BasicTextField(text, { text = it; r.v = it.replace(",", "").toDoubleOrNull(); changed() }, textStyle = TextStyle(color = t.ink, fontSize = 15.sp),
                                            cursorBrush = SolidColor(t.accent), singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Pill(text: String, on: Boolean, onClick: () -> Unit) {
    val t = LocalTheme.current
    Text(text, fontSize = 14.sp, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal, color = if (on) t.chipFg else t.ink75,
        modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(if (on) t.chipBg else t.well).clickable(onClick = onClick).padding(horizontal = 11.dp, vertical = 7.dp))
}

@Composable
private fun DateField(label: String, value: String, onChange: (String) -> Unit) {
    val t = LocalTheme.current
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, fontSize = 13.sp, color = t.ink55)
        Box(Modifier.width(120.dp).clip(RoundedCornerShape(8.dp)).background(t.well).padding(8.dp)) {
            if (value.isEmpty()) Text("YYYY-MM-DD", fontSize = 14.sp, color = t.ink55)
            BasicTextField(value, onChange, textStyle = TextStyle(color = t.ink, fontSize = 14.sp), cursorBrush = SolidColor(t.accent), singleLine = true)
        }
    }
}

// MARK: - the menu

@Composable
fun MenuSheet(onConnect: () -> Unit, onDone: () -> Unit) {
    val t = LocalTheme.current
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp).padding(bottom = 32.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("Bagholder", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = t.ink, modifier = Modifier.weight(1f))
            Text("Done", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = t.accent, modifier = Modifier.clickable(onClick = onDone).padding(8.dp))
        }
        Spacer(Modifier.height(8.dp))
        if (Book.connected) {
            MenuRow("Sync now", t.accent) { Book.syncNow(); onDone() }
            MenuRow("Disconnect", t.neg) { Book.disconnect(); onDone() }
        } else {
            MenuRow("Connect Wealthsimple", t.accent, onConnect)
        }
        HorizontalDivider(color = t.hair, modifier = Modifier.padding(vertical = 8.dp))
        Row(Modifier.fillMaxWidth().padding(vertical = 8.dp)) { Text("Activities", fontSize = 15.sp, color = t.ink, modifier = Modifier.weight(1f)); Text("${Book.pull?.activities?.size ?: 0}", fontSize = 15.sp, color = t.ink55) }
        Row(Modifier.fillMaxWidth().padding(vertical = 8.dp)) { Text("Version", fontSize = 15.sp, color = t.ink, modifier = Modifier.weight(1f)); Text(Book.appVersion, fontSize = 15.sp, color = t.ink55) }
    }
}

@Composable
private fun MenuRow(text: String, color: Color, onClick: () -> Unit) {
    Text(text, fontSize = 16.sp, color = color, modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 12.dp))
}

// MARK: - Connect (the Wealthsimple login in a web view; the session cookie is captured from it)

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
            if (name == WSPull.OAUTH_COOKIE && WSPull.jsonWithAccessToken(value) != null) oauth = value
            else if (oauth == null && WSPull.jsonWithAccessToken(value) != null) oauth = value
        }
    }
    val o = oauth ?: return null
    return Pair(o, wssdi)
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun ConnectScreen(onSession: (String, String?) -> Unit, onCancel: () -> Unit) {
    val t = LocalTheme.current
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
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Cancel", fontSize = 16.sp, color = t.accent, modifier = Modifier.clickable(onClick = onCancel).padding(8.dp))
            Spacer(Modifier.weight(1f))
            Text("Connect Wealthsimple", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
            Spacer(Modifier.weight(1f))
            Spacer(Modifier.width(70.dp))
        }
        AndroidView(modifier = Modifier.fillMaxSize(), factory = { context ->
            WebView(context).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                CookieManager.getInstance().setAcceptCookie(true)
                CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
                webViewClient = object : WebViewClient() {}
                loadUrl(WSPull.LOGIN_URL)
            }
        })
    }
}
