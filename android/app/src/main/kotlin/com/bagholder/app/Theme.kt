// The themes, with the web page's tokens (ledger.html): Nocturne on a dark
// appearance, Light on a light one. Colours come from these tokens only.
// Formatting follows SPEC.md §3.
package com.bagholder.app

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import com.bagholder.model.KPI
import com.bagholder.model.Model
import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.floor
import kotlin.math.round

class BHTheme(
    val mat: Color, val bg: Color, val surface: Color, val well: Color, val accent: Color, val accent300: Color, val accent900: Color,
    val ink: Color, val ink75: Color, val ink60: Color, val ink55: Color, val hair: Color, val grid: Color,
    val pos: Color, val neg: Color, val mixed: Color, val chipBg: Color, val chipFg: Color, val pie: List<Color>,
) {
    fun signed(v: Double): Color = if (v > 0.0001) pos else if (v < -0.0001) neg else ink

    companion object {
        private fun hex(v: Long, a: Float = 1f) = Color(((v shr 16) and 0xff).toInt(), ((v shr 8) and 0xff).toInt(), (v and 0xff).toInt()).copy(alpha = a)

        val nocturne = BHTheme(
            mat = hex(0x101220), bg = hex(0x161826), surface = hex(0x232532), well = hex(0x292b31),
            accent = hex(0x9184d9), accent300 = hex(0xd2cefd), accent900 = hex(0x2b2741),
            ink = hex(0xe9e9ed), ink75 = hex(0xe9e9ed, 0.8f), ink60 = hex(0xe9e9ed, 0.68f), ink55 = hex(0xe9e9ed, 0.62f),
            hair = hex(0xe9e9ed, 0.14f), grid = hex(0xe9e9ed, 0.07f), pos = hex(0x6fd39b), neg = hex(0xe0778a), mixed = hex(0x7972a9),
            chipBg = hex(0x2b2741), chipFg = hex(0xd2cefd),
            pie = listOf(hex(0x9184d9), hex(0x6fd39b), hex(0x5fb0e6), hex(0xe8b36a), hex(0xe0778a), hex(0x7fd3c9), hex(0xc48fdc), hex(0xd7c46a), hex(0xe59a6a), hex(0x8fb87a), hex(0xa0a8b8)),
        )

        val light = BHTheme(
            mat = hex(0xe0e2ea), bg = hex(0xeef0f5), surface = hex(0xfafafc), well = hex(0xf1f2f6),
            accent = hex(0x6b5cd6), accent300 = hex(0x4a3bb8), accent900 = hex(0xe9e6fa),
            ink = hex(0x1b1d27), ink75 = hex(0x1b1d27, 0.82f), ink60 = hex(0x1b1d27, 0.72f), ink55 = hex(0x1b1d27, 0.66f),
            hair = hex(0x1b1d27, 0.12f), grid = hex(0x1b1d27, 0.06f), pos = hex(0x2e8a62), neg = hex(0xc0505f), mixed = hex(0x9a95c4),
            chipBg = hex(0xe9e6fa), chipFg = hex(0x4a3bb8),
            pie = listOf(hex(0xa89ee6), hex(0x8fd4b4), hex(0x93c4ec), hex(0xf0c98c), hex(0xeea3ae), hex(0x9adbd4), hex(0xcfaee6), hex(0xe0d48c), hex(0xf2b592), hex(0xb9d69c), hex(0xb6bec9)),
        )
    }
}

val LocalTheme = compositionLocalOf { BHTheme.nocturne }

/** SPEC.md §3. */
object Fmt {
    const val MINUS = "−"
    const val DASH = "—"

    private fun group(v: Double, digits: Int): String {
        val sym = DecimalFormatSymbols(Locale.US)
        val pattern = if (digits > 0) "#,##0." + "0".repeat(digits) else "#,##0"
        return DecimalFormat(pattern, sym).format(v)
    }

    /** `$1,247.41`, `−$286.74` */
    fun money(v: Double?, digits: Int = 2): String {
        if (v == null || !v.isFinite()) return DASH
        val body = "$" + group(abs(v), digits)
        return if (v < 0) MINUS + body else body
    }

    /** `+$20.05` */
    fun signedMoney(v: Double?, digits: Int = 2): String {
        if (v == null || !v.isFinite()) return DASH
        return if (v < 0) money(v, digits) else "+" + money(v, digits)
    }

    /** `$18,622` */
    fun wholeMoney(v: Double?) = money(v, 0)

    /** `$37.8k`, `$1.2M`, `$420`: for chart subtitles and axes */
    fun compactMoney(v: Double, signed: Boolean = false): String {
        val a = abs(v)
        val body = when {
            a >= 1_000_000 -> "$" + String.format(Locale.US, "%.1f", a / 1_000_000).removeSuffix(".0") + "M"
            a >= 10_000 -> "$" + group(round(a / 1000), 0) + "k"
            a >= 1000 -> "$" + String.format(Locale.US, "%.1f", a / 1000).removeSuffix(".0") + "k"
            else -> "$" + group(round(a), 0)
        }
        if (v < 0) return MINUS + body
        return if (signed && v > 0) "+$body" else body
    }

    /** `+0.7%`, `−13.8%` (signed) or `28.81%` (rate) */
    fun pct(v: Double?, digits: Int = 1, signed: Boolean = true): String {
        if (v == null || !v.isFinite()) return DASH
        val body = String.format(Locale.US, "%.${digits}f", abs(v) * 100) + "%"
        if (v < 0) return MINUS + body
        return if (signed) "+$body" else body
    }

    /** `233,580`, `957.90`, `0.000123` */
    fun qty(v: Double): String {
        val a = abs(v)
        if (a == floor(a)) return group(a, 0)
        if (a < 1) return group(a, 6)
        return group(a, 2)
    }

    /** `49.85`, `0.3675`, `0.00123` */
    fun price(v: Double): String {
        val a = abs(v)
        val digits = if (a < 0.01 && a > 0) 5 else if (a < 1) 4 else 2
        return group(a, digits)
    }

    /** `$0.2000` */
    fun perUnit(v: Double?): String {
        if (v == null) return DASH
        return "$" + group(abs(v), if (abs(v) < 1) 4 else 2)
    }

    /** `207d` */
    fun hold(days: Int) = "${days}d"

    /** `Jun '26` */
    fun monthAxis(key: String): String {
        if (key.length < 7) return key
        val m = key.substring(5, 7).toIntOrNull() ?: return key
        if (m !in 1..12) return key
        return Model.MONTHS[m - 1] + " '" + key.substring(2, 4)
    }

    /** `18 Jun '26` */
    fun dayLabel(iso: String): String {
        if (iso.length < 10) return iso
        val d = iso.substring(8, 10).toIntOrNull() ?: return iso
        return "$d " + monthAxis(iso)
    }

    fun profitFactor(k: KPI): String {
        if (k.profitFactorInfinite) return "∞"
        val pf = k.profitFactor ?: return DASH
        return String.format(Locale.US, "%.2f", pf)
    }

    /** `Synced Sep '26` */
    fun syncedLabel(millis: Long?): String {
        if (millis == null) return ""
        return "Synced " + SimpleDateFormat("MMM ''yy", Locale.US).format(Date(millis))
    }
}
