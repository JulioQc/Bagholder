// The dashboard and Cashflow drawings, in Compose Canvas: the equity curve,
// the monthly bars, the year pairs, the grade bars, the allocation donut and
// the trade chart. Nothing drawn is synthetic: every mark is a model figure.
package com.bagholder.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.bagholder.model.EquityPoint
import com.bagholder.model.FillRow
import com.bagholder.model.Grades
import com.bagholder.model.Model
import com.bagholder.model.MonthBucket
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.pow

/** A bar of the trade chart. */
data class Bar(val time: String, val open: Double, val high: Double, val low: Double, val close: Double)

@Composable
private fun AxisLabel(text: String, align: TextAlign = TextAlign.End, modifier: Modifier = Modifier) {
    val t = LocalTheme.current
    Text(text, fontSize = 11.sp, color = t.ink55, textAlign = align, maxLines = 1, modifier = modifier)
}

/**
 * ledger.html monthlyCardHtml: the winning months take 35–93 % of the height by their share
 * of the range, the losing months the rest, each side scaled to its own extreme.
 */
class MonthlyScale(val posMax: Double, val negMax: Double, val posH: Float)

fun monthlyScale(months: List<MonthBucket>, height: Float): MonthlyScale {
    val posMax = max(months.maxOfOrNull { max(0.0, it.value) } ?: 0.0, 0.0)
    val negMax = max(months.maxOfOrNull { max(0.0, -it.value) } ?: 0.0, 0.0)
    val total = if (posMax + negMax == 0.0) 1.0 else posMax + negMax
    var base = if (negMax > 0) min(0.93, max(0.35, posMax / total)) else 0.93
    if (!(posMax > 0) && negMax > 0) base = 0.07
    return MonthlyScale(posMax, negMax, (base * height).toFloat())
}

fun monthlyBarHeight(v: Double, sc: MonthlyScale, height: Float): Float {
    if (v >= 0) return if (sc.posMax > 0) max(1.5f, (v / sc.posMax).toFloat() * sc.posH) else 0f
    return if (sc.negMax > 0) max(1.5f, (-v / sc.negMax).toFloat() * (height - sc.posH)) else 0f
}

fun axisMoney(v: Double): String = if (v == 0.0) "$0" else (if (v > 0) "+" else "") + Fmt.wholeMoney(v)

/** The value labels in dp from the top: the peak, its midpoint, zero, the worst month; a label within 15 dp of the one above is dropped. */
fun monthlyValueLabels(sc: MonthlyScale, height: Float): List<Pair<String, Float>> {
    val candidates = mutableListOf<Pair<String, Float>>()
    if (sc.posMax > 0) { candidates.add(axisMoney(sc.posMax) to 0f); candidates.add(axisMoney(sc.posMax / 2) to sc.posH / 2) }
    candidates.add("$0" to sc.posH)
    if (sc.negMax > 0) candidates.add(axisMoney(-sc.negMax) to height)
    val out = mutableListOf<Pair<String, Float>>()
    for ((text, y) in candidates) {
        if (out.isNotEmpty() && y - out.last().second < 15f) continue
        out.add(text to y)
    }
    return out
}

/** Four round `$` ticks from zero to just above the peak. */
fun axisTicks(hi: Double): List<Double> {
    if (hi <= 0) return listOf(0.0, 1.0)
    val raw = hi / 3
    val mag = 10.0.pow(floor(log10(raw)))
    val step = listOf(1.0, 2.0, 2.5, 5.0, 10.0).map { it * mag }.firstOrNull { it >= raw } ?: raw
    return (0..3).map { it * step }
}

/** The readout line above a chart while it is pressed; blank otherwise, so the chart does not move. */
@Composable
private fun Readout(parts: List<Pair<String, Color>>?) {
    val t = LocalTheme.current
    Row(Modifier.height(20.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        for ((text, color) in parts ?: emptyList()) Text(text, fontSize = 13.sp, color = color, fontWeight = if (color == t.ink60 || color == t.ink55) FontWeight.Normal else FontWeight.SemiBold)
    }
}

/** A long press: the index under the finger's first touch at once, then following the drag. */
private fun Modifier.pressReadout(count: Int, onPick: (Int?) -> Unit): Modifier = pointerInput(count) {
    detectDragGesturesAfterLongPress(
        onDragStart = { pos -> if (count > 0) onPick((pos.x / size.width * count).toInt().coerceIn(0, count - 1)) },
        onDrag = { change, _ -> if (count > 0) onPick((change.position.x / size.width * count).toInt().coerceIn(0, count - 1)) },
        onDragEnd = { onPick(null) }, onDragCancel = { onPick(null) })
}

/**
 * The equity series, edge to edge and scaled from its low to its high, with four date
 * labels. A long press picks a day: the card shows the amount at its top right and the
 * day sits under the finger at the bottom.
 */
@Composable
fun EquityCurveChart(series: List<EquityPoint>, pick: Int?, onPick: (Int?) -> Unit, height: Int = 160) {
    val t = LocalTheme.current
    val vals = series.map { it.v }
    val (lo, hi) = equityRange(vals)
    Column(Modifier.fillMaxWidth()) {
        Canvas(Modifier.fillMaxWidth().height(height.dp).pointerInput(series) {
            // the nearest point to the finger, from the first touch on
            val n = series.size
            detectDragGesturesAfterLongPress(
                onDragStart = { pos -> if (n > 1) onPick((pos.x / size.width * (n - 1)).roundToInt().coerceIn(0, n - 1)) },
                onDrag = { change, _ -> if (n > 1) onPick((change.position.x / size.width * (n - 1)).roundToInt().coerceIn(0, n - 1)) },
                onDragEnd = { onPick(null) }, onDragCancel = { onPick(null) })
        }) {
            if (series.size < 2) return@Canvas
            val n = (series.size - 1).toFloat()
            fun pt(i: Int) = Offset(i / n * size.width, size.height - (((vals[i] - lo) / (hi - lo)) * size.height).toFloat())
            // pressed: the series up to the picked day keeps its colour, the rest is dimmed
            val upTo = pick?.takeIf { it in series.indices } ?: (series.size - 1)
            val fill = Path().apply {
                moveTo(0f, size.height)
                for (i in 0..upTo) lineTo(pt(i).x, pt(i).y)
                lineTo(pt(upTo).x, size.height)
                close()
            }
            drawPath(fill, Brush.verticalGradient(listOf(t.pos.copy(alpha = 0.22f), t.pos.copy(alpha = 0.02f))))
            val stroke = Stroke(width = 1.6.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round)
            val line = Path().apply {
                moveTo(pt(0).x, pt(0).y)
                for (i in 1..upTo) lineTo(pt(i).x, pt(i).y)
            }
            drawPath(line, t.pos, style = stroke)
            if (upTo < series.size - 1) {
                val rest = Path().apply {
                    moveTo(pt(upTo).x, pt(upTo).y)
                    for (i in upTo + 1 until series.size) lineTo(pt(i).x, pt(i).y)
                }
                drawPath(rest, t.pos.copy(alpha = 0.3f), style = stroke)
            }
            pick?.let { i ->
                val p = pt(i)
                drawLine(t.ink55, Offset(p.x, 0f), Offset(p.x, size.height), 1f)
                drawCircle(t.surface, 5.dp.toPx(), p)
                drawCircle(t.pos, 5.dp.toPx(), p, style = Stroke(width = 2.dp.toPx()))
            }
        }
        Spacer(Modifier.height(6.dp))
        BoxWithConstraints(Modifier.fillMaxWidth().height(14.dp)) {
            val i = pick
            if (i != null && i in series.indices) {
                val x = i.toFloat() / max(series.size - 1, 1) * maxWidth.value
                Text(Fmt.dayLabel(series[i].d), fontSize = 11.sp, fontWeight = FontWeight.Medium, color = t.ink, maxLines = 1,
                    modifier = Modifier.offset(x = (x - 36f).coerceIn(0f, maxWidth.value - 72f).dp).width(72.dp), textAlign = TextAlign.Center)
            } else {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    for (l in equityDateLabels(series)) AxisLabel(l)
                }
            }
        }
    }
}

/** The series' low to its high, each padded by 4 % of the span so the line clears the edges. */
fun equityRange(vals: List<Double>): Pair<Double, Double> {
    val lo = vals.minOrNull() ?: 0.0
    val hi = vals.maxOrNull() ?: 1.0
    val span = if (hi - lo > 0) hi - lo else max(abs(hi), 1.0)
    return (lo - span * 0.04) to (hi + span * 0.04)
}

fun equityDateLabels(series: List<EquityPoint>): List<String> {
    if (series.size < 2) return series.map { Fmt.monthAxis(it.d) }
    val a = java.time.LocalDate.parse(series.first().d).toEpochDay()
    val b = java.time.LocalDate.parse(series.last().d).toEpochDay()
    return (0 until 4).map { i -> Fmt.monthAxis(java.time.LocalDate.ofEpochDay(a + (b - a) * i / 3).toString()) }
}

/**
 * The Dashboard's P&L bars, edge to edge with no value axis: one bar per month on the
 * page's scale. A long press picks a month: the card shows its P&L at the top right and
 * the month sits under the finger at the bottom; a tap opens it.
 */
@Composable
fun PnlBarsChart(months: List<MonthBucket>, pick: Int?, onPickChange: (Int?) -> Unit, height: Int = 130, color: Color? = null, overlay: List<Double>? = null,
                 onOpen: ((MonthBucket) -> Unit)? = null) {
    // overlay: per month, an amount drawn over the bar from the same baseline at the same width in `neg`
    // (the Cashflow chart's margin interest); the taller of the two sits behind
    val t = LocalTheme.current
    val scaled = if (overlay == null) months else months.mapIndexed { i, m -> MonthBucket(m.key, m.label).apply { value = max(m.value, overlay.getOrElse(i) { 0.0 }); count = m.count } }
    val sc = monthlyScale(scaled, height.toFloat())
    Column(Modifier.fillMaxWidth()) {
        Canvas(Modifier.fillMaxWidth().height(height.dp).pointerInput(months) {
            detectTapGestures { pos ->
                val n = max(months.size, 1)
                val i = (pos.x / (size.width / n)).toInt().coerceIn(0, n - 1)
                if (months.isNotEmpty()) onOpen?.invoke(months[i])
            }
        }.pressReadout(months.size, onPickChange)) {
            val n = max(months.size, 1).toFloat()
            val pitch = size.width / n
            val barW = max(2f, pitch - 4.dp.toPx())   // the page's bars: 5 px apart, filling the month's slot
            val zeroY = sc.posH.dp.toPx()
            drawLine(t.hair, Offset(0f, zeroY), Offset(size.width, zeroY), 1f)
            for ((i, m) in months.withIndex()) {
                val h = monthlyBarHeight(m.value, sc, height.toFloat()).dp.toPx()
                val x = i * pitch + (pitch - barW) / 2
                val y = if (m.value >= 0) zeroY - h else zeroY
                val dim = pick != null && pick != i
                val alpha = if (dim) 0.35f else 1f
                val ov = overlay?.getOrElse(i) { 0.0 } ?: 0.0
                val ho = if (ov > 0) monthlyBarHeight(ov, sc, height.toFloat()).dp.toPx() else 0f
                val bar = { drawRect((color ?: if (m.value >= 0) t.pos else t.neg).copy(alpha = alpha), Offset(x, y), Size(barW, max(h, 1.5f))) }
                val over = { drawRect(t.neg.copy(alpha = alpha), Offset(x, zeroY - ho), Size(barW, ho)) }
                if (ho > h) { over(); bar() } else { bar(); if (ho > 0) over() }
            }
        }
        Spacer(Modifier.height(6.dp))
        BoxWithConstraints(Modifier.fillMaxWidth().height(14.dp)) {
            val i = pick
            if (i != null && i in months.indices) {
                val x = (i + 0.5f) / max(months.size, 1) * maxWidth.value
                Text(months[i].label, fontSize = 11.sp, fontWeight = FontWeight.Medium, color = t.ink, maxLines = 1,
                    modifier = Modifier.offset(x = (x - 30f).coerceIn(0f, maxWidth.value - 60f).dp).width(60.dp), textAlign = TextAlign.Center)
            } else {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    for (l in monthLabels(months.map { it.key })) AxisLabel(l)
                }
            }
        }
    }
}

/** One bar per calendar month, positive up, negative down; a long press reads the month, amount and count. */
@Composable
fun MonthlyBarsChart(months: List<MonthBucket>, height: Int = 170, countLabel: String = "trade", onPick: ((MonthBucket) -> Unit)? = null) {
    val t = LocalTheme.current
    val sc = monthlyScale(months, height.toFloat())
    var pick by remember { mutableStateOf<Int?>(null) }
    Column {
    Readout(pick?.let { i -> val m = months[i]; listOf(m.label to t.ink60, Fmt.money(m.value) to t.signed(m.value), ("${m.count} $countLabel" + if (m.count == 1) "" else "s") to t.ink55) })
    Row(Modifier.fillMaxWidth()) {
        // the page's axis: the peak, its midpoint, zero and the worst month, each centred on
        // its own line in whole dollars; a label that would touch the one above it is not shown
        Box(Modifier.height(height.dp)) {
            for ((text, y) in monthlyValueLabels(sc, height.toFloat())) {
                AxisLabel(text, TextAlign.Start, Modifier.offset(y = (y - 7).dp))
            }
        }
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Canvas(Modifier.fillMaxWidth().height(height.dp).pointerInput(months) {
                detectTapGestures { pos ->
                    val n = max(months.size, 1)
                    val i = (pos.x / (size.width / n)).toInt().coerceIn(0, n - 1)
                    if (months.isNotEmpty()) onPick?.invoke(months[i])
                }
            }.pressReadout(months.size) { pick = it }) {
                val n = max(months.size, 1).toFloat()
                val pitch = size.width / n
                val barW = max(2f, min(14.dp.toPx(), pitch * 0.6f))
                val zeroY = sc.posH.dp.toPx()
                if (sc.posMax > 0) drawLine(t.grid, Offset(0f, zeroY / 2), Offset(size.width, zeroY / 2), 1f)
                drawLine(t.hair, Offset(0f, zeroY), Offset(size.width, zeroY), 1f)
                for ((i, m) in months.withIndex()) {
                    val h = monthlyBarHeight(m.value, sc, height.toFloat()).dp.toPx()
                    val x = i * pitch + (pitch - barW) / 2
                    val y = if (m.value >= 0) zeroY - h else zeroY
                    val dim = pick != null && pick != i
                    drawRect((if (m.value >= 0) t.pos else t.neg).copy(alpha = if (dim) 0.35f else 1f), Offset(x, y), Size(barW, max(h, 1.5f)))
                }
            }
            Spacer(Modifier.height(6.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                for (l in monthLabels(months.map { it.key })) AxisLabel(l)
            }
        }
    }
    }
}

fun monthLabels(keys: List<String>): List<String> {
    if (keys.size < 2) return keys.map { Fmt.monthAxis(it) }
    val n = min(4, keys.size)
    return (0 until n).map { i -> Fmt.monthAxis(keys[(keys.size - 1) * i / (n - 1)]) }
}

/** Two equal-height bars, the account's year and the index's, scaled together. */
@Composable
fun YearPairBars(mine: Double?, index: Double?, scale: Double) {
    val t = LocalTheme.current
    Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
        for ((v, color) in listOf(mine to t.pos, index to t.mixed)) {
            Canvas(Modifier.fillMaxWidth().height(8.dp)) {
                val frac = if (scale > 0) min(1.0, abs(v ?: 0.0) / scale) else 0.0
                drawRoundRect(if ((v ?: 0.0) < 0) t.neg else color, size = Size(max(2f, (size.width * frac).toFloat()), size.height),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(3.dp.toPx()))
            }
        }
    }
}

/** Four bars, A B C F, with the CAD sum above and the count below each. */
@Composable
fun GradeBarsChart(grades: Grades, height: Int = 150) {
    val t = LocalTheme.current
    val hi = max(grades.buckets.maxOfOrNull { it.pnl } ?: 0.0, 0.0)
    val lo = min(grades.buckets.minOfOrNull { it.pnl } ?: 0.0, 0.0)
    val span = if (hi - lo == 0.0) 1.0 else hi - lo
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        for (b in grades.buckets) {
            Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                Box(Modifier.fillMaxWidth().height(height.dp)) {
                    // the bars leave 18 dp above for a positive label and, when there is a loss, 18 dp below for a negative one
                    val top = 18.0
                    val bottom = if (lo < 0) 18.0 else 0.0
                    val ph = height - top - bottom
                    val zeroFrac = (0 - lo) / span
                    val hFrac = abs(b.pnl) / span
                    val zeroY = top + ph - zeroFrac * ph
                    val bh = hFrac * ph
                    Canvas(Modifier.fillMaxWidth().height(height.dp)) {
                        val y = (if (b.pnl >= 0) zeroY - bh else zeroY).dp.toPx()
                        drawRoundRect(if (b.pnl >= 0) t.pos else t.neg, Offset(0f, y), Size(size.width, max(bh.dp.toPx(), 2f)),
                            cornerRadius = androidx.compose.ui.geometry.CornerRadius(3.dp.toPx()))
                    }
                    val labelTop = if (b.pnl >= 0) zeroY - bh - 18 else zeroY + bh + 2
                    Text(Fmt.compactMoney(b.pnl), fontSize = 12.sp, fontWeight = FontWeight.Medium, color = t.signed(b.pnl),
                        modifier = Modifier.fillMaxWidth().offset(y = labelTop.dp), textAlign = TextAlign.Center)
                }
                Spacer(Modifier.height(4.dp))
                Text("${b.grade} · ${b.n}", fontSize = 12.sp, color = t.ink55)
            }
        }
    }
}

/** The allocation donut: slices largest first from the theme's palette, the total or the picked slice in the centre. */
@Composable
fun DonutChart(slices: List<Pair<String, Double>>, picked: Int?, onPick: (Int?) -> Unit, size: Int = 150, centre: Double? = null) {
    val t = LocalTheme.current
    val total = slices.sumOf { it.second }
    Box(Modifier.size(size.dp), contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(size.dp).pointerInput(slices, picked) {
            detectTapGestures { pos ->
                val c = Offset(this.size.width / 2f, this.size.height / 2f)
                var ang = atan2((pos.y - c.y).toDouble(), (pos.x - c.x).toDouble()) + PI / 2
                if (ang < 0) ang += 2 * PI
                var start = 0.0
                var hit: Int? = null
                for ((i, s) in slices.withIndex()) {
                    if (total <= 0) break
                    val end = start + s.second / total * 2 * PI
                    if (ang >= start && ang < end) { hit = i; break }
                    start = end
                }
                onPick(if (hit == picked) null else hit)
            }
        }) {
            val r = this.size.minDimension / 2
            val ring = r * 0.30f
            var start = -90f
            for ((i, s) in slices.withIndex()) {
                if (total <= 0) break
                val sweep = (s.second / total * 360).toFloat()
                val color = t.pie[i % t.pie.size]
                drawArc(if (picked == null || picked == i) color else color.copy(alpha = 0.35f), start, sweep, false,
                    topLeft = Offset(ring / 2, ring / 2), size = Size(this.size.width - ring, this.size.height - ring), style = Stroke(width = ring))
                start += sweep
            }
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            if (picked != null && picked in slices.indices) {
                Text(slices[picked].first, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
                Text(Fmt.money(slices[picked].second), fontSize = 13.sp, color = t.ink75)
                Text(Fmt.pct(if (total > 0) slices[picked].second / total else null, signed = false), fontSize = 12.sp, color = t.ink55)
            } else {
                Text(if (centre != null) Fmt.wholeMoney(centre) else Fmt.money(total), fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
            }
        }
    }
}

/** The bar a day falls in, for weekly and monthly bars. */
fun barIndex(bars: List<Bar>, day: String): Int? {
    var hit: Int? = null
    for ((i, b) in bars.withIndex()) if (b.time.take(10) <= day) hit = i
    return hit
}

/** The trade chart: candlesticks for the bars the sources answered with, the
 * executions marked on their day at their price (or at the bar's close for an
 * option contract on its underlying). Nothing else is drawn. */
@Composable
fun CandleChart(bars: List<Bar>, fills: List<FillRow>, atClose: Boolean = false, height: Int = 220) {
    val t = LocalTheme.current
    val priced = if (atClose) emptyList() else fills.filter { it.price > 0 }.map { it.price }
    val lo = min(bars.minOfOrNull { it.low } ?: 0.0, priced.minOrNull() ?: Double.MAX_VALUE)
    val hi = max(bars.maxOfOrNull { it.high } ?: 1.0, priced.maxOrNull() ?: 0.0)
    val pad = (hi - lo) * 0.08
    val top = hi + pad
    val bottom = max(0.0, lo - pad)
    val span = if (top - bottom == 0.0) 1.0 else top - bottom
    val ticks = (0..3).map { bottom + span * it / 3 }
    Row(Modifier.fillMaxWidth()) {
        Column(Modifier.height(height.dp), verticalArrangement = Arrangement.SpaceBetween, horizontalAlignment = Alignment.End) {
            for (v in ticks.reversed()) AxisLabel(Fmt.price(v))
        }
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Canvas(Modifier.fillMaxWidth().height(height.dp)) {
                if (bars.isEmpty()) return@Canvas
                val n = bars.size.toFloat()
                val pitch = size.width / n
                val bw = max(1.5f, min(9.dp.toPx(), pitch * 0.6f))
                fun y(v: Double) = size.height - (((v - bottom) / span) * size.height).toFloat()
                for (v in ticks) drawLine(t.grid, Offset(0f, y(v)), Offset(size.width, y(v)), 1f)
                for ((i, b) in bars.withIndex()) {
                    val cx = i * pitch + pitch / 2
                    val color = if (b.close >= b.open) t.pos else t.neg
                    drawLine(color, Offset(cx, y(b.high)), Offset(cx, y(b.low)), 1f)
                    drawRect(color, Offset(cx - bw / 2, min(y(b.open), y(b.close))), Size(bw, max(1f, abs(y(b.open) - y(b.close)))))
                }
                val index = HashMap<String, Int>()
                for ((i, b) in bars.withIndex()) index.putIfAbsent(b.time.take(10), i)
                for (f in fills) {
                    if (!atClose && f.price <= 0) continue
                    val i = index[f.date.take(10)] ?: barIndex(bars, f.date.take(10)) ?: continue
                    val cx = i * pitch + pitch / 2
                    val py = y(if (atClose) bars[i].close else f.price)
                    val tri = Path()
                    val d4 = 4.dp.toPx(); val d5 = 5.dp.toPx(); val d12 = 12.dp.toPx()   // the phone's sizes, in dp not px
                    if (f.side == "BUY") { tri.moveTo(cx, py + d4); tri.lineTo(cx - d5, py + d12); tri.lineTo(cx + d5, py + d12) }
                    else { tri.moveTo(cx, py - d4); tri.lineTo(cx - d5, py - d12); tri.lineTo(cx + d5, py - d12) }
                    tri.close()
                    drawPath(tri, if (f.side == "BUY") t.accent else t.accent300)
                }
            }
            Spacer(Modifier.height(6.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                for (l in barLabels(bars)) AxisLabel(l)
            }
        }
    }
}

fun barLabels(bars: List<Bar>): List<String> {
    if (bars.size < 2) return bars.map { Fmt.dayLabel(it.time.take(10)) }
    val n = min(4, bars.size)
    return (0 until n).map { i -> Fmt.dayLabel(bars[(bars.size - 1) * i / (n - 1)].time.take(10)) }
}

