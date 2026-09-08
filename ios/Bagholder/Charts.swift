// The dashboard and Cashflow drawings, in SwiftUI Canvas: the equity curve,
// the monthly bars, the year pairs, the grade bars, the allocation donut and
// the trade chart. Nothing drawn is synthetic: every mark is a model figure.
import SwiftUI

/// A long press on a chart: the x of the first touch is reported the moment the
/// press is recognized, so the readout starts where the finger is, then follows it.
struct ChartPress: UIViewRepresentable {
    var onChange: (CGFloat?, CGFloat) -> Void   // x within the view, or nil when the press ends; the view's width

    func makeUIView(context: Context) -> PressView {
        let v = PressView()
        v.onChange = onChange
        return v
    }

    func updateUIView(_ uiView: PressView, context: Context) { uiView.onChange = onChange }

    final class PressView: UIView {
        var onChange: ((CGFloat?, CGFloat) -> Void)?
        private var origin: CGPoint?

        override init(frame: CGRect) {
            super.init(frame: frame)
            backgroundColor = .clear
            let press = UILongPressGestureRecognizer(target: self, action: #selector(pressed))
            press.minimumPressDuration = 0.2
            press.allowableMovement = 30
            press.cancelsTouchesInView = false
            addGestureRecognizer(press)
        }

        required init?(coder: NSCoder) { nil }

        override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
            origin = touches.first?.location(in: self)
            super.touchesBegan(touches, with: event)
        }

        @objc private func pressed(_ g: UILongPressGestureRecognizer) {
            switch g.state {
            case .began: onChange?((origin ?? g.location(in: self)).x, bounds.width)
            case .changed: onChange?(g.location(in: self).x, bounds.width)
            default: origin = nil; onChange?(nil, bounds.width)
            }
        }
    }
}

/// The equity series, edge to edge and scaled from its low to its high, with four
/// date labels. A long press picks a day: the card shows the amount at its top right
/// and the day sits under the finger at the bottom.
struct EquityCurveChart: View {
    @Environment(\.theme) private var t
    let series: [BHEquityPoint]
    @Binding var pick: Int?
    var height: CGFloat = 160

    var body: some View {
        let vals = series.map { $0.v }
        let (lo, hi) = Self.range(vals)
        VStack(spacing: 6) {
            Canvas { ctx, size in
                guard series.count > 1 else { return }
                let n = CGFloat(series.count - 1)
                func pt(_ i: Int) -> CGPoint {
                    CGPoint(x: CGFloat(i) / n * size.width, y: size.height - CGFloat((vals[i] - lo) / (hi - lo)) * size.height)
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
                if let i = pick, series.indices.contains(i) {
                    let p = pt(i)
                    var hair = Path(); hair.move(to: CGPoint(x: p.x, y: 0)); hair.addLine(to: CGPoint(x: p.x, y: size.height))
                    ctx.stroke(hair, with: .color(t.hair), style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
                    ctx.fill(Path(ellipseIn: CGRect(x: p.x - 4, y: p.y - 4, width: 8, height: 8)), with: .color(t.pos))
                }
            }
            .frame(height: height)
            .overlay(ChartPress { x, width in
                guard let x, width > 0, series.count > 1 else { pick = nil; return }
                pick = max(0, min(series.count - 1, Int((x / width * CGFloat(series.count - 1)).rounded())))
            })
            GeometryReader { geo in
                if let i = pick, series.indices.contains(i) {
                    let x = CGFloat(i) / CGFloat(max(series.count - 1, 1)) * geo.size.width
                    Text(BHFmt.dayLabel(series[i].d)).font(.system(size: 11, weight: .medium)).foregroundStyle(t.ink)
                        .fixedSize().position(x: min(max(x, 36), geo.size.width - 36), y: 7)
                } else {
                    HStack {
                        ForEach(Array(Self.dateLabels(series).enumerated()), id: \.offset) { i, l in
                            if i > 0 { Spacer(minLength: 0) }
                            Text(l).font(.system(size: 11)).foregroundStyle(t.ink55)
                        }
                    }
                }
            }
            .frame(height: 14)
        }
    }

    /// The series' low to its high, each padded by 4 % of the span so the line clears the edges.
    static func range(_ vals: [Double]) -> (Double, Double) {
        let lo = vals.min() ?? 0, hi = vals.max() ?? 1
        let span = hi - lo > 0 ? hi - lo : max(abs(hi), 1)
        return (lo - span * 0.04, hi + span * 0.04)
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
    var countLabel = "trade"
    @State private var pick: Int? = nil

    var body: some View {
        let sc = Self.scale(months, height: height)
        VStack(alignment: .leading, spacing: 6) {
        HStack(spacing: 8) {
            if let i = pick, months.indices.contains(i) {
                Text(months[i].label).font(.system(size: 13)).foregroundStyle(t.ink60)
                Text(BHFmt.money(months[i].value)).font(.system(size: 13, weight: .semibold)).monospacedDigit().foregroundStyle(t.signed(months[i].value))
                Text("\(months[i].count) \(countLabel)" + (months[i].count == 1 ? "" : "s")).font(.system(size: 13)).foregroundStyle(t.ink55)
            } else {
                Text(" ").font(.system(size: 13))
            }
        }
        HStack(alignment: .top, spacing: 8) {
            // the page's axis: the peak, its midpoint, zero and the worst month, each centred on
            // its own line in whole dollars; a label that would touch the one above it is not shown
            ZStack(alignment: .topLeading) {
                ForEach(Array(Self.valueLabels(sc, height: height).enumerated()), id: \.offset) { _, l in
                    Text(l.text).font(.system(size: 11)).foregroundStyle(t.ink55).offset(y: l.y - 7)
                }
            }
            .frame(height: height, alignment: .topLeading)
            VStack(spacing: 6) {
                GeometryReader { geo in
                    let w = geo.size.width
                    let n = CGFloat(max(months.count, 1))
                    let pitch = w / n
                    let barW = max(2, min(14, pitch * 0.6))
                    let zeroY = sc.posH
                    ZStack(alignment: .topLeading) {
                        if sc.posMax > 0 {
                            Path { p in p.move(to: CGPoint(x: 0, y: zeroY / 2)); p.addLine(to: CGPoint(x: w, y: zeroY / 2)) }
                                .stroke(t.grid, lineWidth: 1)
                        }
                        Path { p in p.move(to: CGPoint(x: 0, y: zeroY)); p.addLine(to: CGPoint(x: w, y: zeroY)) }
                            .stroke(t.hair, lineWidth: 1)
                        ForEach(Array(months.enumerated()), id: \.element.key) { i, m in
                            let h = Self.barHeight(m.value, sc, height: height)
                            let x = CGFloat(i) * pitch + (pitch - barW) / 2
                            let y = m.value >= 0 ? zeroY - h : zeroY
                            RoundedRectangle(cornerRadius: 2)
                                .fill((m.value >= 0 ? t.pos : t.neg).opacity(pick == nil || pick == i ? 1 : 0.35))
                                .frame(width: barW, height: max(h, 1.5))
                                .offset(x: x, y: y)
                                .onTapGesture { onPick?(m) }
                        }
                    }
                    .overlay(ChartPress { x, width in
                        guard let x, width > 0, !months.isEmpty else { pick = nil; return }
                        pick = max(0, min(months.count - 1, Int(x / width * CGFloat(months.count))))
                    })
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
    }

    /// ledger.html monthlyCardHtml: the winning months take 35–93 % of the height by their share
    /// of the range, the losing months the rest, each side scaled to its own extreme.
    struct Scale { let posMax: Double; let negMax: Double; let posH: CGFloat }

    static func scale(_ months: [BHMonthBucket], height: CGFloat) -> Scale {
        let posMax = max(months.map { max(0, $0.value) }.max() ?? 0, 0)
        let negMax = max(months.map { max(0, -$0.value) }.max() ?? 0, 0)
        let total = posMax + negMax == 0 ? 1 : posMax + negMax
        var base = negMax > 0 ? min(0.93, max(0.35, posMax / total)) : 0.93
        if !(posMax > 0) && negMax > 0 { base = 0.07 }
        return Scale(posMax: posMax, negMax: negMax, posH: CGFloat(base) * height)
    }

    static func barHeight(_ v: Double, _ sc: Scale, height: CGFloat) -> CGFloat {
        if v >= 0 { return sc.posMax > 0 ? max(1.5, CGFloat(v / sc.posMax) * sc.posH) : 0 }
        return sc.negMax > 0 ? max(1.5, CGFloat(-v / sc.negMax) * (height - sc.posH)) : 0
    }

    static func axisMoney(_ v: Double) -> String {
        v == 0 ? "$0" : (v > 0 ? "+" : "") + BHFmt.wholeMoney(v)
    }

    static func valueLabels(_ sc: Scale, height: CGFloat) -> [(text: String, y: CGFloat)] {
        var candidates: [(String, CGFloat)] = []
        if sc.posMax > 0 { candidates += [(axisMoney(sc.posMax), 0), (axisMoney(sc.posMax / 2), sc.posH / 2)] }
        candidates.append(("$0", sc.posH))
        if sc.negMax > 0 { candidates.append((axisMoney(-sc.negMax), height)) }
        var out: [(text: String, y: CGFloat)] = []
        for (text, y) in candidates {
            if let last = out.last, y - last.y < 15 { continue }
            out.append((text, y))
        }
        return out
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
                        // the bars leave 18 pt above for a positive label and, when there is a loss, 18 pt below for a negative one
                        let top: CGFloat = 18, bottom: CGFloat = lo < 0 ? 18 : 0
                        let ph = geo.size.height - top - bottom
                        let zeroY = top + ph - CGFloat((0 - lo) / span) * ph
                        let bh = CGFloat(abs(b.pnl) / span) * ph
                        ZStack(alignment: .topLeading) {
                            Text(BHFmt.compactMoney(b.pnl))
                                .font(.system(size: 12, weight: .medium)).foregroundStyle(t.signed(b.pnl))
                                .frame(width: geo.size.width)
                                .offset(y: b.pnl >= 0 ? zeroY - bh - 18 : zeroY + bh + 2)
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
    /// An option contract's fills sit on its underlying's bars: marked on their day
    /// at the bar's close, since the premium is not a price of the underlying.
    var atClose: Bool = false
    var height: CGFloat = 220

    var body: some View {
        let priced = atClose ? [] : fills.filter { $0.price > 0 }.map { $0.price }
        let lo = min(bars.map { $0.low }.min() ?? 0, priced.min() ?? Double.greatestFiniteMagnitude)
        let hi = max(bars.map { $0.high }.max() ?? 1, priced.max() ?? 0)
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
                    for f in fills where atClose || f.price > 0 {
                        guard let i = index[String(f.date.prefix(10))] ?? Self.barIndex(bars, on: String(f.date.prefix(10))) else { continue }
                        let cx = CGFloat(i) * pitch + pitch / 2
                        let py = y(atClose ? bars[i].close : f.price)
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

    /// The bar a day falls in, for weekly and monthly bars.
    static func barIndex(_ bars: [BHBar], on day: String) -> Int? {
        var hit: Int?
        for (i, b) in bars.enumerated() where String(b.time.prefix(10)) <= day { hit = i }
        return hit
    }

    static func labels(_ bars: [BHBar]) -> [String] {
        guard bars.count > 1 else { return bars.map { BHFmt.dayLabel(String($0.time.prefix(10))) } }
        let n = min(4, bars.count)
        return (0..<n).map { i in BHFmt.dayLabel(String(bars[(bars.count - 1) * i / (n - 1)].time.prefix(10))) }
    }
}
