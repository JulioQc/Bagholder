// The dashboard and Cashflow drawings, in Compose Canvas: the equity curve,
// the monthly bars, the year pairs, the grade bars, the allocation donut and
// the trade chart. Nothing drawn is synthetic: every mark is a model figure.
package com.bagholder.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
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
import kotlin.math.pow

/** A bar of the trade chart. */
data class Bar(val time: String, val open: Double, val high: Double, val low: Double, val close: Double)

@Composable
private fun AxisLabel(text: String, align: TextAlign = TextAlign.End) {
    val t = LocalTheme.current
    Text(text, fontSize = 11.sp, color = t.ink55, textAlign = align, maxLines = 1)
}

/** Four round `$` ticks from zero to just above the peak. */
fun axisTicks(hi: Double): List<Double> {
    if (hi <= 0) return listOf(0.0, 1.0)
    val raw = hi / 3
    val mag = 10.0.pow(floor(log10(raw)))
    val step = listOf(1.0, 2.0, 2.5, 5.0, 10.0).map { it * mag }.firstOrNull { it >= raw } ?: raw
    return (0..3).map { it * step }
}

/** The equity series with a `$` axis and date labels. */
@Composable
fun EquityCurveChart(series: List<EquityPoint>, height: Int = 220) {
    val t = LocalTheme.current
    val vals = series.map { it.v }
    val hi = vals.maxOrNull() ?: 1.0
    val ticks = axisTicks(hi)
    val top = ticks.last()
    Row(Modifier.fillMaxWidth()) {
        Column(Modifier.height(height.dp), verticalArrangement = Arrangement.SpaceBetween, horizontalAlignment = Alignment.End) {
            for (v in ticks.reversed()) AxisLabel(Fmt.wholeMoney(v))
        }
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Canvas(Modifier.fillMaxWidth().height(height.dp)) {
                if (series.size < 2 || top <= 0) return@Canvas
                val n = (series.size - 1).toFloat()
                fun pt(i: Int) = Offset(i / n * size.width, size.height - ((vals[i] / top) * size.height).toFloat())
                for (v in ticks) {
                    val y = size.height - ((v / top) * size.height).toFloat()
                    drawLine(t.grid, Offset(0f, y), Offset(size.width, y), 1f)
                }
                val fill = Path().apply {
                    moveTo(0f, size.height)
                    for (i in series.indices) lineTo(pt(i).x, pt(i).y)
                    lineTo(size.width, size.height)
                    close()
                }
                drawPath(fill, Brush.verticalGradient(listOf(t.pos.copy(alpha = 0.22f), t.pos.copy(alpha = 0.02f))))
                val line = Path().apply {
                    moveTo(pt(0).x, pt(0).y)
                    for (i in 1 until series.size) lineTo(pt(i).x, pt(i).y)
                }
                drawPath(line, t.pos, style = Stroke(width = 1.6.dp.toPx()))
            }
            Spacer(Modifier.height(6.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                for (l in equityDateLabels(series)) AxisLabel(l)
            }
        }
    }
}

fun equityDateLabels(series: List<EquityPoint>): List<String> {
    if (series.size < 2) return series.map { Fmt.monthAxis(it.d) }
    val a = java.time.LocalDate.parse(series.first().d).toEpochDay()
    val b = java.time.LocalDate.parse(series.last().d).toEpochDay()
    return (0 until 4).map { i -> Fmt.monthAxis(java.time.LocalDate.ofEpochDay(a + (b - a) * i / 3).toString()) }
}

/** One bar per calendar month, positive up, negative down. */
@Composable
fun MonthlyBarsChart(months: List<MonthBucket>, height: Int = 170, onPick: ((MonthBucket) -> Unit)? = null) {
    val t = LocalTheme.current
    val hi = max(months.maxOfOrNull { it.value } ?: 0.0, 0.0)
    val lo = min(months.minOfOrNull { it.value } ?: 0.0, 0.0)
    val span = if (hi - lo == 0.0) 1.0 else hi - lo
    Row(Modifier.fillMaxWidth()) {
        Column(Modifier.width(52.dp).height(height.dp), verticalArrangement = Arrangement.SpaceBetween, horizontalAlignment = Alignment.End) {
            AxisLabel(Fmt.compactMoney(hi))
            if (lo < 0) { AxisLabel("$0"); AxisLabel(Fmt.compactMoney(lo)) } else AxisLabel("$0")
        }
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Canvas(Modifier.fillMaxWidth().height(height.dp).pointerInput(months) {
                detectTapGestures { pos ->
                    val n = max(months.size, 1)
                    val i = (pos.x / (size.width / n)).toInt().coerceIn(0, n - 1)
                    if (months.isNotEmpty()) onPick?.invoke(months[i])
                }
            }) {
                val n = max(months.size, 1).toFloat()
                val pitch = size.width / n
                val barW = max(2f, min(14.dp.toPx(), pitch * 0.6f))
                val zeroY = size.height - (((0 - lo) / span) * size.height).toFloat()
                drawLine(t.hair, Offset(0f, zeroY), Offset(size.width, zeroY), 1f)
                for ((i, m) in months.withIndex()) {
                    val h = ((abs(m.value) / span) * size.height).toFloat()
                    val x = i * pitch + (pitch - barW) / 2
                    val y = if (m.value >= 0) zeroY - h else zeroY
                    drawRect(if (m.value >= 0) t.pos else t.neg, Offset(x, y), Size(barW, max(h, 1.5f)))
                }
            }
            Spacer(Modifier.height(6.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                for (l in monthLabels(months.map { it.key })) AxisLabel(l)
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
                    val zeroFrac = (0 - lo) / span
                    val hFrac = abs(b.pnl) / span
                    Canvas(Modifier.fillMaxWidth().height(height.dp)) {
                        val zeroY = size.height - (zeroFrac * size.height).toFloat()
                        val bh = (hFrac * size.height).toFloat()
                        drawRoundRect(if (b.pnl >= 0) t.pos else t.neg, Offset(0f, if (b.pnl >= 0) zeroY - bh else zeroY), Size(size.width, max(bh, 2f)),
                            cornerRadius = androidx.compose.ui.geometry.CornerRadius(3.dp.toPx()))
                    }
                    val labelTop = if (b.pnl >= 0) (1 - zeroFrac - hFrac) * height - 18 else (1 - zeroFrac + hFrac) * height
                    Text(Fmt.compactMoney(b.pnl), fontSize = 12.sp, fontWeight = FontWeight.Medium, color = t.signed(b.pnl),
                        modifier = Modifier.fillMaxWidth().offset(y = labelTop.coerceIn(0.0, height - 14.0).dp), textAlign = TextAlign.Center)
                }
                Spacer(Modifier.height(4.dp))
                Text("${b.grade} · ${b.n}", fontSize = 12.sp, color = t.ink55)
            }
        }
    }
}

/** The allocation donut: slices largest first from the theme's palette, the total or the picked slice in the centre. */
@Composable
fun DonutChart(slices: List<Pair<String, Double>>, picked: Int?, onPick: (Int?) -> Unit, size: Int = 150) {
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
                Text(Fmt.money(total), fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = t.ink)
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
                    if (f.side == "BUY") { tri.moveTo(cx, py + 4); tri.lineTo(cx - 5, py + 12); tri.lineTo(cx + 5, py + 12) }
                    else { tri.moveTo(cx, py - 4); tri.lineTo(cx - 5, py - 12); tri.lineTo(cx + 5, py - 12) }
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
