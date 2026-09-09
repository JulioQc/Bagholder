// The themes, with the web page's tokens (ledger.html): Nocturne on a dark
// appearance, Light on a light one. Colours come from these tokens only.
// Formatting follows SPEC.md §3.
import SwiftUI

struct BHTheme {
    let mat, bg, surface, well, accent, accent300, accent900, ink, ink75, ink60, ink55, hair, grid, pos, neg, mixed, chipBg, chipFg: Color
    let pie: [Color]

    static func hex(_ v: UInt32, _ a: Double = 1) -> Color {
        Color(red: Double((v >> 16) & 0xff) / 255, green: Double((v >> 8) & 0xff) / 255, blue: Double(v & 0xff) / 255, opacity: a)
    }

    static let nocturne = BHTheme(
        mat: hex(0x101220), bg: hex(0x161826), surface: hex(0x232532), well: hex(0x292b31),
        accent: hex(0x9184d9), accent300: hex(0xd2cefd), accent900: hex(0x2b2741),
        ink: hex(0xe9e9ed), ink75: hex(0xe9e9ed, 0.8), ink60: hex(0xe9e9ed, 0.68), ink55: hex(0xe9e9ed, 0.62),
        hair: hex(0xe9e9ed, 0.14), grid: hex(0xe9e9ed, 0.07), pos: hex(0x6fd39b), neg: hex(0xe0778a), mixed: hex(0x7972a9),
        chipBg: hex(0x2b2741), chipFg: hex(0xd2cefd),
        pie: [hex(0x9184d9), hex(0x6fd39b), hex(0x5fb0e6), hex(0xe8b36a), hex(0xe0778a), hex(0x7fd3c9), hex(0xc48fdc), hex(0xd7c46a)]
    )

    static let light = BHTheme(
        mat: hex(0xe0e2ea), bg: hex(0xeef0f5), surface: hex(0xfafafc), well: hex(0xf1f2f6),
        accent: hex(0x6b5cd6), accent300: hex(0x4a3bb8), accent900: hex(0xe9e6fa),
        ink: hex(0x1b1d27), ink75: hex(0x1b1d27, 0.82), ink60: hex(0x1b1d27, 0.72), ink55: hex(0x1b1d27, 0.66),
        hair: hex(0x1b1d27, 0.12), grid: hex(0x1b1d27, 0.06), pos: hex(0x2e8a62), neg: hex(0xc0505f), mixed: hex(0x9a95c4),
        chipBg: hex(0xe9e6fa), chipFg: hex(0x4a3bb8),
        pie: [hex(0xa89ee6), hex(0x8fd4b4), hex(0x93c4ec), hex(0xf0c98c), hex(0xeea3ae), hex(0x9adbd4), hex(0xcfaee6), hex(0xe0d48c)]
    )

    func signed(_ v: Double) -> Color { v > 0.0001 ? pos : (v < -0.0001 ? neg : ink) }
}

private struct BHThemeKey: EnvironmentKey {
    static let defaultValue = BHTheme.nocturne
}

extension EnvironmentValues {
    var theme: BHTheme {
        get { self[BHThemeKey.self] }
        set { self[BHThemeKey.self] = newValue }
    }
}

/// SPEC.md §3.
enum BHFmt {
    static let minus = "\u{2212}"
    static let dash = "\u{2014}"

    private static func group(_ v: Double, _ digits: Int) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.minimumFractionDigits = digits
        f.maximumFractionDigits = digits
        f.groupingSeparator = ","
        f.decimalSeparator = "."
        f.usesGroupingSeparator = true
        return f.string(from: NSNumber(value: v)) ?? String(format: "%.\(digits)f", v)
    }

    /// `$1,247.41`, `−$286.74`
    static func money(_ v: Double?, digits: Int = 2) -> String {
        guard let v = v, v.isFinite else { return dash }
        let body = "$" + group(abs(v), digits)
        return v < 0 ? minus + body : body
    }

    /// `+$20.05`
    static func signedMoney(_ v: Double?, digits: Int = 2) -> String {
        guard let v = v, v.isFinite else { return dash }
        return v < 0 ? money(v, digits: digits) : "+" + money(v, digits: digits)
    }

    /// `$18,622`
    static func wholeMoney(_ v: Double?) -> String { money(v, digits: 0) }

    /// `$37.8k`, `$1.2M`, `$420,000`: for chart subtitles and axes, signed when asked
    static func compactMoney(_ v: Double, signed: Bool = false) -> String {
        let a = abs(v)
        let body: String
        if a >= 1_000_000 { body = "$" + String(format: "%.1f", a / 1_000_000).replacingOccurrences(of: ".0", with: "") + "M" }
        else if a >= 10_000 { body = "$" + group((a / 1000).rounded(), 0) + "k" }
        else if a >= 1000 { body = "$" + String(format: "%.1f", a / 1000).replacingOccurrences(of: ".0", with: "") + "k" }
        else { body = "$" + group(a.rounded(), 0) }
        if v < 0 { return minus + body }
        return signed && v > 0 ? "+" + body : body
    }

    /// `+0.7%`, `−13.8%` (signed) or `28.81%` (rate)
    static func pct(_ v: Double?, digits: Int = 1, signed: Bool = true) -> String {
        guard let v = v, v.isFinite else { return dash }
        let body = String(format: "%.\(digits)f", abs(v) * 100) + "%"
        if v < 0 { return minus + body }
        return signed ? "+" + body : body
    }

    /// `233,580`, `957.90`, `0.000123`
    static func qty(_ v: Double) -> String {
        let a = abs(v)
        if a == a.rounded() { return group(a, 0) }
        if a < 1 { return group(a, 6) }
        return group(a, 2)
    }

    /// `49.85`, `0.3675`, `0.00123`
    static func price(_ v: Double) -> String {
        let a = abs(v)
        let digits = a < 0.01 && a > 0 ? 5 : (a < 1 ? 4 : 2)
        return group(a, digits)
    }

    /// `$0.2000`
    static func perUnit(_ v: Double?) -> String {
        guard let v = v else { return dash }
        return "$" + group(abs(v), abs(v) < 1 ? 4 : 2)
    }

    /// `207d`
    static func hold(_ days: Int) -> String { "\(days)d" }

    /// `Jun '26`
    static func monthAxis(_ key: String) -> String {
        guard key.count >= 7, let m = Int(key.dropFirst(5).prefix(2)), (1...12).contains(m) else { return key }
        return BHModel.months[m - 1] + " '" + key.dropFirst(2).prefix(2)
    }

    /// `18 Jun '26`
    static func dayLabel(_ iso: String) -> String {
        guard iso.count >= 10, let d = Int(iso.dropFirst(8).prefix(2)) else { return iso }
        return "\(d) " + monthAxis(iso)
    }

    static func profitFactor(_ k: BHKPI) -> String {
        if k.profitFactorInfinite { return "∞" }
        guard let pf = k.profitFactor else { return dash }
        return String(format: "%.2f", pf)
    }

    /// `Synced Sep '26`, from an ISO instant
    static func syncedLabel(_ date: Date?) -> String {
        guard let date = date else { return "" }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MMM ''yy"
        return "Synced " + f.string(from: date)
    }
}
