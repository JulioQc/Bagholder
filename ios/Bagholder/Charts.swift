// The dashboard and Cashflow drawings, in SwiftUI Canvas: the equity curve,
// the monthly bars, the year pairs, the grade bars, the allocation donut and
// the trade chart. Nothing drawn is synthetic: every mark is a model figure.
import SwiftUI

/// The equity series with a `$` axis and date labels.
struct EquityCurveChart: View {
    @Environment(\.theme) private var t
    let series: [BHEquityPoint]
    var height: CGFloat = 220

    var body: some View {
        let vals = series.map { $0.v }
        let hi = vals.max() ?? 1
        let lo = 0.0
        let ticks = Self.axisTicks(hi)
        HStack(alignment: .top, spacing: 8) {
            VStack(alignment: .trailing, spacing: 0) {
                ForEach(Array(ticks.reversed().enumerated()), id: \.offset) { i, v in
                    Text(BHFmt.wholeMoney(v)).font(.system(size: 11)).foregroundStyle(t.ink55)
                    if i < ticks.count - 1 { Spacer(minLength: 0) }
                }
            }
            .frame(height: height)
            VStack(spacing: 6) {
                Canvas { ctx, size in
                    guard series.count > 1, hi > lo else { return }
                    let n = CGFloat(series.count - 1)
                    let top = ticks.last ?? hi
                    func pt(_ i: Int) -> CGPoint {
                        CGPoint(x: CGFloat(i) / n * size.width, y: size.height - CGFloat((vals[i] - lo) / (top - lo)) * size.height)
                    }
                    for v in ticks {
                        let y = size.height - CGFloat((v - lo) / (top - lo)) * size.height
                        var g = Path(); g.move(to: CGPoint(x: 0, y: y)); g.addLine(to: CGPoint(x: size.width, y: y))
                        ctx.stroke(g, with: .color(t.grid), lineWidth: 1)
                    }
                    var fill = Path()
                    fill.move(to: CGPoint(x: 0, y: size.height))
                    for i in series.indices { fill.addLine(to: pt(i)) }
                    fill.addLine(to: CGPoint(x: size.width, y: size.height))
                    fill.closeSubpath()
                    ctx.fill(fill, with: .linearGradient(Gradient(colors: [t.pos.opacity(0.22), t.pos.opacity(0.02)]), startPoint: .zero, endPoint: CGPoint(x: 0, y: size.height)))
                    var line = Path()
                    line.move(to: pt(0))
                    for i in 1..<series.count { line.addLine(to: pt(i)) }
                    ctx.stroke(line, with: .color(t.pos), style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round))
                }
                .frame(height: height)
                HStack {
                    ForEach(Array(Self.dateLabels(series).enumerated()), id: \.offset) { i, l in
                        if i > 0 { Spacer(minLength: 0) }
                        Text(l).font(.system(size: 11)).foregroundStyle(t.ink55)
                    }
                }
            }
        }
    }

    /// Four round `$` ticks from zero to just above the peak.
    static func axisTicks(_ hi: Double) -> [Double] {
        guard hi > 0 else { return [0, 1] }
        let raw = hi / 3
        let mag = pow(10, floor(log10(raw)))
        let step = [1.0, 2.0, 2.5, 5.0, 10.0].map { $0 * mag }.first { $0 >= raw } ?? raw
        return (0...3).map { Double($0) * step }
    }

    static func dateLabels(_ series: [BHEquityPoint]) -> [String] {
        guard let first = series.first, let last = series.last, series.count > 1 else { return series.map { BHFmt.monthAxis($0.d) } }
        let a = BHModel.dayNumber(first.d) ?? 0, b = BHModel.dayNumber(last.d) ?? 0
        let n = 4
        return (0..<n).map { i in BHFmt.monthAxis(BHModel.isoDate(fromDayNumber: a + (b - a) * i / (n - 1))) }
    }
}

/// One bar per calendar month, positive up, negative down, with the value axis
/// labelled at the top, the midpoint, zero and the bottom.
struct MonthlyBarsChart: View {
    @Environment(\.theme) private var t
    let months: [BHMonthBucket]
    var height: CGFloat = 170
    var onPick: ((BHMonthBucket) -> Void)?

    var body: some View {
        let hi = max(months.map { $0.value }.max() ?? 0, 0)
        let lo = min(months.map { $0.value }.min() ?? 0, 0)
        let span = (hi - lo) == 0 ? 1 : (hi - lo)
        HStack(alignment: .top, spacing: 8) {
            VStack(alignment: .trailing, spacing: 0) {
                Text(BHFmt.compactMoney(hi)).font(.system(size: 11)).foregroundStyle(t.ink55)
                Spacer(minLength: 0)
                if lo < 0 {
                    Text("$0").font(.system(size: 11)).foregroundStyle(t.ink55)
                        .offset(y: CGFloat(-(lo / span)) * height - height / 2 + 6)
                    Spacer(minLength: 0)
                    Text(BHFmt.compactMoney(lo)).font(.system(size: 11)).foregroundStyle(t.ink55)
                } else {
                    Text("$0").font(.system(size: 11)).foregroundStyle(t.ink55)
                }
            }
            .frame(width: 52, height: height)
            VStack(spacing: 6) {
                GeometryReader { geo in
                    let w = geo.size.width
                    let n = CGFloat(max(months.count, 1))
                    let pitch = w / n
                    let barW = max(2, min(14, pitch * 0.6))
                    let zeroY = height - CGFloat((0 - lo) / span) * height
                    ZStack(alignment: .topLeading) {
                        Path { p in p.move(to: CGPoint(x: 0, y: zeroY)); p.addLine(to: CGPoint(x: w, y: zeroY)) }
                            .stroke(t.hair, lineWidth: 1)
                        ForEach(Array(months.enumerated()), id: \.element.key) { i, m in
                            let h = CGFloat(abs(m.value) / span) * height
                            let x = CGFloat(i) * pitch + (pitch - barW) / 2
                            let y = m.value >= 0 ? zeroY - h : zeroY
                            RoundedRectangle(cornerRadius: 2)
                                .fill(m.value >= 0 ? t.pos : t.neg)
                                .frame(width: barW, height: max(h, 1.5))
                                .offset(x: x, y: y)
                                .onTapGesture { onPick?(m) }
                        }
                    }
                }
                .frame(height: height)
                HStack {
                    ForEach(Array(Self.labels(months).enumerated()), id: \.offset) { i, l in
                        if i > 0 { Spacer(minLength: 0) }
                        Text(l).font(.system(size: 11)).foregroundStyle(t.ink55)
                    }
                }
            }
        }
    }

    static func labels(_ months: [BHMonthBucket]) -> [String] {
        guard months.count > 1 else { return months.map { BHFmt.monthAxis($0.key) } }
        let n = min(4, months.count)
        return (0..<n).map { i in BHFmt.monthAxis(months[(months.count - 1) * i / (n - 1)].key) }
    }
}

/// Two equal-height bars, the account's year and the index's, scaled together.
struct YearPairBars: View {
    @Environment(\.theme) private var t
    let mine: Double?
    let index: Double?
    let scale: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            bar(mine, t.pos)
            bar(index, t.mixed)
        }
    }

    private func bar(_ v: Double?, _ color: Color) -> some View {
        GeometryReader { geo in
            let frac = scale > 0 ? min(1, abs(v ?? 0) / scale) : 0
            RoundedRectangle(cornerRadius: 3)
                .fill((v ?? 0) < 0 ? t.neg : color)
                .frame(width: max(2, geo.size.width * CGFloat(frac)), height: 8)
        }
        .frame(height: 8)
    }
}

/// Four bars, A B C F, with the CAD sum above and the count below each.
struct GradeBarsChart: View {
    @Environment(\.theme) private var t
    let grades: BHGrades
    var height: CGFloat = 150

    var body: some View {
        let hi = max(grades.buckets.map { $0.pnl }.max() ?? 0, 0)
        let lo = min(grades.buckets.map { $0.pnl }.min() ?? 0, 0)
        let span = (hi - lo) == 0 ? 1 : (hi - lo)
        HStack(alignment: .top, spacing: 12) {
            ForEach(grades.buckets, id: \.grade) { b in
                VStack(spacing: 4) {
                    GeometryReader { geo in
                        let h = geo.size.height
                        let zeroY = h - CGFloat((0 - lo) / span) * h
                        let bh = CGFloat(abs(b.pnl) / span) * h
                        ZStack(alignment: .topLeading) {
                            Text(BHFmt.compactMoney(b.pnl))
                                .font(.system(size: 12, weight: .medium)).foregroundStyle(t.signed(b.pnl))
                                .frame(width: geo.size.width)
                                .offset(y: (b.pnl >= 0 ? zeroY - bh : zeroY + bh) - (b.pnl >= 0 ? 18 : 0))
                            RoundedRectangle(cornerRadius: 3)
                                .fill(b.pnl >= 0 ? t.pos : t.neg)
                                .frame(width: geo.size.width, height: max(bh, 2))
                                .offset(y: b.pnl >= 0 ? zeroY - bh : zeroY)
                        }
                    }
                    .frame(height: height)
                    Text("\(b.grade) · \(b.n)").font(.system(size: 12)).foregroundStyle(t.ink55)
                }
            }
        }
    }
}

/// The allocation donut: slices largest first from the theme's palette, the
/// total (or the picked slice) in the centre.
struct DonutChart: View {
    @Environment(\.theme) private var t
    let slices: [(label: String, value: Double)]
    var picked: Int?
    var onPick: ((Int?) -> Void)?
    var size: CGFloat = 170

    var body: some View {
        let total = slices.reduce(0.0) { $0 + $1.value }
        ZStack {
            Canvas { ctx, sz in
                let c = CGPoint(x: sz.width / 2, y: sz.height / 2)
                let r = min(sz.width, sz.height) / 2
                let ring = r * 0.30
                var start = -Double.pi / 2
                for (i, s) in slices.enumerated() where total > 0 {
                    let end = start + s.value / total * 2 * Double.pi
                    var p = Path()
                    p.addArc(center: c, radius: r, startAngle: .radians(start), endAngle: .radians(end), clockwise: false)
                    p.addArc(center: c, radius: r - ring, startAngle: .radians(end), endAngle: .radians(start), clockwise: true)
                    p.closeSubpath()
                    let color = t.pie[i % t.pie.count]
                    ctx.fill(p, with: .color(picked == nil || picked == i ? color : color.opacity(0.35)))
                    start = end
                }
            }
            VStack(spacing: 2) {
                if let i = picked, slices.indices.contains(i) {
                    Text(slices[i].label).font(.system(size: 13, weight: .semibold)).foregroundStyle(t.ink)
                    Text(BHFmt.money(slices[i].value)).font(.system(size: 13)).foregroundStyle(t.ink75)
                    Text(BHFmt.pct(total > 0 ? slices[i].value / total : nil, signed: false)).font(.system(size: 12)).foregroundStyle(t.ink55)
                } else {
                    Text(BHFmt.money(total)).font(.system(size: 15, weight: .semibold)).foregroundStyle(t.ink)
                }
            }
        }
        .frame(width: size, height: size)
        .contentShape(Circle())
        .onTapGesture { location in
            let c = CGPoint(x: size / 2, y: size / 2)
            let dx = location.x - c.x, dy = location.y - c.y
            var ang = atan2(dy, dx) + Double.pi / 2
            if ang < 0 { ang += 2 * Double.pi }
            var start = 0.0
            var hit: Int?
            for (i, s) in slices.enumerated() where total > 0 {
                let end = start + s.value / total * 2 * Double.pi
                if ang >= start && ang < end { hit = i; break }
                start = end
            }
            onPick?(hit == picked ? nil : hit)
        }
    }
}

/// One OHLC bar of the trade chart.
struct BHBar: Equatable {
    var time: String   // ISO day, or ISO instant for intraday bars
    var open: Double, high: Double, low: Double, close: Double
}

/// The trade chart: candlesticks for the bars the sources answered with, the
/// executions marked on their day at their price. Nothing else is drawn.
struct CandleChart: View {
    @Environment(\.theme) private var t
    let bars: [BHBar]
    let fills: [BHFillRow]
    var height: CGFloat = 220

    var body: some View {
        let lo = min(bars.map { $0.low }.min() ?? 0, fills.filter { $0.price > 0 }.map { $0.price }.min() ?? Double.greatestFiniteMagnitude)
        let hi = max(bars.map { $0.high }.max() ?? 1, fills.filter { $0.price > 0 }.map { $0.price }.max() ?? 0)
        let pad = (hi - lo) * 0.08
        let top = hi + pad, bottom = max(0, lo - pad)
        let span = top - bottom == 0 ? 1 : top - bottom
        let ticks = stride(from: 0, through: 3, by: 1).map { bottom + span * Double($0) / 3 }
        HStack(alignment: .top, spacing: 8) {
            VStack(alignment: .trailing, spacing: 0) {
                ForEach(Array(ticks.reversed().enumerated()), id: \.offset) { i, v in
                    Text(BHFmt.price(v)).font(.system(size: 11)).foregroundStyle(t.ink55)
                    if i < ticks.count - 1 { Spacer(minLength: 0) }
                }
            }
            .frame(height: height)
            VStack(spacing: 6) {
                Canvas { ctx, size in
                    guard !bars.isEmpty else { return }
                    let n = CGFloat(bars.count)
                    let pitch = size.width / n
                    let bw = max(1.5, min(9, pitch * 0.6))
                    func y(_ v: Double) -> CGFloat { size.height - CGFloat((v - bottom) / span) * size.height }
                    for v in ticks {
                        var g = Path(); g.move(to: CGPoint(x: 0, y: y(v))); g.addLine(to: CGPoint(x: size.width, y: y(v)))
                        ctx.stroke(g, with: .color(t.grid), lineWidth: 1)
                    }
                    for (i, b) in bars.enumerated() {
                        let cx = CGFloat(i) * pitch + pitch / 2
                        let up = b.close >= b.open
                        let color = up ? t.pos : t.neg
                        var wick = Path(); wick.move(to: CGPoint(x: cx, y: y(b.high))); wick.addLine(to: CGPoint(x: cx, y: y(b.low)))
                        ctx.stroke(wick, with: .color(color), lineWidth: 1)
                        let body = CGRect(x: cx - bw / 2, y: min(y(b.open), y(b.close)), width: bw, height: max(1, abs(y(b.open) - y(b.close))))
                        ctx.fill(Path(body), with: .color(color))
                    }
                    let index = Dictionary(bars.enumerated().map { (String($0.element.time.prefix(10)), $0.offset) }, uniquingKeysWith: { a, _ in a })
                    for f in fills where f.price > 0 {
                        guard let i = index[String(f.date.prefix(10))] else { continue }
                        let cx = CGFloat(i) * pitch + pitch / 2
                        let py = y(f.price)
                        var tri = Path()
                        if f.side == "BUY" {
                            tri.move(to: CGPoint(x: cx, y: py + 4)); tri.addLine(to: CGPoint(x: cx - 5, y: py + 12)); tri.addLine(to: CGPoint(x: cx + 5, y: py + 12))
                        } else {
                            tri.move(to: CGPoint(x: cx, y: py - 4)); tri.addLine(to: CGPoint(x: cx - 5, y: py - 12)); tri.addLine(to: CGPoint(x: cx + 5, y: py - 12))
                        }
                        tri.closeSubpath()
                        ctx.fill(tri, with: .color(f.side == "BUY" ? t.accent : t.accent300))
                    }
                }
                .frame(height: height)
                HStack {
                    ForEach(Array(Self.labels(bars).enumerated()), id: \.offset) { i, l in
                        if i > 0 { Spacer(minLength: 0) }
                        Text(l).font(.system(size: 11)).foregroundStyle(t.ink55)
                    }
                }
            }
        }
    }

    static func labels(_ bars: [BHBar]) -> [String] {
        guard bars.count > 1 else { return bars.map { BHFmt.dayLabel(String($0.time.prefix(10))) } }
        let n = min(4, bars.count)
        return (0..<n).map { i in BHFmt.dayLabel(String(bars[(bars.count - 1) * i / (n - 1)].time.prefix(10))) }
    }
}
