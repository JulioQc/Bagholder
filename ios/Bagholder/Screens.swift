// The pages: Dashboard, Trades, Positions, Cashflow, the trade and position
// detail, the filter sheet and the menu. Every figure comes from BHView; a
// screen is a layout of those figures, not a new definition of them.
import SwiftUI

// MARK: - root

struct RootView: View {
    @Environment(\.colorScheme) private var scheme
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var book = Book()
    @State private var tab = 0
    @State private var showFilters = false
    @State private var showMenu = false
    @State private var showConnect = false

    var body: some View {
        let t: BHTheme = scheme == .dark ? .nocturne : .light
        ZStack(alignment: .bottom) {
            Group {
                switch tab {
                case 0: NavigationStack { DashboardScreen(book: book, tab: $tab, chrome: chrome).ignoresSafeArea(.keyboard) }
                case 1: NavigationStack { TradesScreen(book: book, chrome: chrome).ignoresSafeArea(.keyboard) }
                case 2: NavigationStack { PositionsScreen(book: book, chrome: chrome).ignoresSafeArea(.keyboard) }
                default: NavigationStack { CashflowScreen(book: book, chrome: chrome).ignoresSafeArea(.keyboard) }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            TabBar(tab: $tab)
        }
        .background(t.bg.ignoresSafeArea())
        .environment(\.theme, t)
        .tint(t.accent)
        .sheet(isPresented: $showFilters) { FiltersSheet(book: book).environment(\.theme, t) }
        // the login opens once the menu has gone, so the web view sits in the key window
        // (passkeys and AutoFill need that; presenting over a dismissing sheet leaves it behind)
        .sheet(isPresented: $showMenu) { MenuSheet(book: book).environment(\.theme, t) }
        .fullScreenCover(isPresented: $showConnect) { ConnectLoginView(book: book, isPresented: $showConnect).environment(\.theme, t) }
        .onAppear {
            book.handleAppear()
            // the login engine starts after the first frame is on screen, not during launch
            if !book.connected { DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { book.warmLogin() } }
        }
        .onChange(of: scenePhase) { _, p in if p == .active { book.handleAppear() } else if p == .background { book.handleBackground() } }
    }

    private var chrome: Chrome {
        Chrome(onFilters: { showFilters = true }, onMenu: { showMenu = true; book.warmLogin() }, onConnect: { showConnect = true })
    }
}

struct Chrome {
    var onFilters: () -> Void
    var onMenu: () -> Void
    var onConnect: () -> Void
}

private struct TabBar: View {
    @Environment(\.theme) private var t
    @Binding var tab: Int
    private let items: [(String, String)] = [("Dashboard", "gauge.with.dots.needle.33percent"), ("Trades", "list.bullet.rectangle"), ("Positions", "briefcase"), ("Cashflow", "dollarsign.circle")]

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(items.enumerated()), id: \.offset) { i, item in
                Button { tab = i } label: {
                    VStack(spacing: 4) {
                        Rectangle().fill(tab == i ? t.accent : .clear).frame(height: 2)
                        Image(systemName: item.1).font(.system(size: 18)).frame(height: 22)
                        Text(item.0).font(.system(size: 11, weight: tab == i ? .semibold : .regular))
                    }
                    .foregroundStyle(tab == i ? t.ink : t.ink55)
                    .frame(maxWidth: .infinity)
                    .padding(.bottom, 6)
                }
                .buttonStyle(.plain)
            }
        }
        .background(t.surface.ignoresSafeArea(edges: .bottom))
        .overlay(alignment: .top) { Rectangle().fill(t.hair).frame(height: 1) }
    }
}

// MARK: - shared pieces

/// The filter button's funnel: SF Symbols has none, so it is the same outline the Android app draws.
struct FunnelIcon: Shape {
    func path(in r: CGRect) -> Path {
        let u = r.width / 24
        var p = Path()
        p.move(to: CGPoint(x: 4 * u, y: 5 * u)); p.addLine(to: CGPoint(x: 20 * u, y: 5 * u)); p.addLine(to: CGPoint(x: 14 * u, y: 12.5 * u))
        p.addLine(to: CGPoint(x: 14 * u, y: 19 * u)); p.addLine(to: CGPoint(x: 10 * u, y: 21 * u)); p.addLine(to: CGPoint(x: 10 * u, y: 12.5 * u)); p.closeSubpath()
        return p
    }
}

/// Brand, sync status, filter and menu buttons.
struct Header: View {
    @Environment(\.theme) private var t
    @ObservedObject var book: Book
    let chrome: Chrome

    var body: some View {
        HStack(spacing: 10) {
            ZStack {
                RoundedRectangle(cornerRadius: 8).fill(t.accent900)
                Image(systemName: "bag").font(.system(size: 14, weight: .semibold)).foregroundStyle(t.accent300)
            }
            .frame(width: 30, height: 30)
            Text("Bagholder").font(.system(size: 19, weight: .bold)).foregroundStyle(t.ink).fixedSize().layoutPriority(2)
            Text(Book.appVersion).font(.system(size: 11)).foregroundStyle(t.ink55).fixedSize().layoutPriority(2)
            Spacer(minLength: 6)
            Text(book.headerStatus)
                .font(.system(size: 13)).foregroundStyle(book.statusIsError ? t.neg : t.ink60)
                .lineLimit(1).truncationMode(.tail).minimumScaleFactor(0.85)
            Button(action: chrome.onFilters) {
                ZStack(alignment: .topTrailing) {
                    FunnelIcon().stroke(t.ink75, style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round)).frame(width: 18, height: 18)
                        .frame(width: 38, height: 38).background(RoundedRectangle(cornerRadius: 9).fill(t.surface))
                    if book.filters.isActive { Circle().fill(t.accent).frame(width: 8, height: 8).offset(x: 2, y: -2) }
                }
            }
            .buttonStyle(.plain)
            Button(action: chrome.onMenu) {
                Image(systemName: "line.3.horizontal").font(.system(size: 15, weight: .medium)).foregroundStyle(t.ink75)
                    .frame(width: 38, height: 38).background(RoundedRectangle(cornerRadius: 9).fill(t.surface))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 16)
        .padding(.top, 6)
        .padding(.bottom, 8)
    }
}

/// The current filter set as chips, each removable.
struct FilterChips: View {
    @Environment(\.theme) private var t
    @ObservedObject var book: Book

    var body: some View {
        let chips = Self.chips(book.filters)
        if !chips.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(chips, id: \.key) { c in
                        HStack(spacing: 0) {
                            Text(c.field).font(.system(size: 14)).foregroundStyle(t.ink60).padding(.leading, 10).padding(.trailing, 6)
                            Text(c.value).font(.system(size: 14, weight: .medium)).foregroundStyle(t.chipFg)
                                .padding(.horizontal, 8).padding(.vertical, 5).background(RoundedRectangle(cornerRadius: 6).fill(t.chipBg))
                            Button { book.setFilters(Self.removing(c.key, from: book.filters)) } label: {
                                Image(systemName: "xmark").font(.system(size: 10, weight: .bold)).foregroundStyle(t.ink55).padding(.horizontal, 10)
                            }
                            .buttonStyle(.plain)
                        }
                        .padding(.vertical, 4)
                        .background(RoundedRectangle(cornerRadius: 8).fill(t.surface))
                    }
                }
                .padding(.horizontal, 16)
            }
            .padding(.bottom, 8)
        }
    }

    struct Chip { var key: String; var field: String; var value: String }

    static func chips(_ f: BHFilters) -> [Chip] {
        var out: [Chip] = []
        if !f.from.isEmpty || !f.to.isEmpty {
            out.append(Chip(key: "date", field: "Date", value: (f.from.isEmpty ? "…" : f.from) + " → " + (f.to.isEmpty ? "…" : f.to)))
        } else if !f.years.isEmpty {
            out.append(Chip(key: "date", field: "Date", value: f.years.joined(separator: ", ")))
        } else if f.preset != "all" {
            out.append(Chip(key: "date", field: "Date", value: f.preset.uppercased()))
        }
        let names = ["account": "Account", "symbol": "Symbol", "grade": "Grade", "tag": "Tag", "kind": "Kind", "exchange": "Exchange", "side": "Side", "result": "Result"]
        for k in BHFilters.listKeys {
            let vals = f.lists[k] ?? []
            if !vals.isEmpty { out.append(Chip(key: "list:" + k, field: (names[k] ?? k) + (vals.count == 1 ? " is" : " in"), value: vals.joined(separator: ", "))) }
        }
        let rnames = ["price": "Price", "hold": "Hold", "pnl": "P&L", "qty": "Qty"]
        for k in BHFilters.rangeKeys {
            if let r = f.ranges[k], let v = r.v { out.append(Chip(key: "range:" + k, field: rnames[k] ?? k, value: r.op + " " + BHFmt.qty(v))) }
        }
        if !f.search.isEmpty { out.append(Chip(key: "search", field: "Search", value: f.search)) }
        return out
    }

    static func removing(_ key: String, from f: BHFilters) -> BHFilters {
        var g = f
        if key == "date" { g.from = ""; g.to = ""; g.years = []; g.preset = "all" }
        else if key.hasPrefix("list:") { g.lists[String(key.dropFirst(5))] = [] }
        else if key.hasPrefix("range:") { g.ranges[String(key.dropFirst(6))]?.v = nil }
        else if key == "search" { g.search = "" }
        return g
    }
}

struct Card<Content: View>: View {
    static var headerHeight: CGFloat { 24 }
    @Environment(\.theme) private var t
    var title: String? = nil
    var subtitle: String? = nil
    var trailing: AnyView? = nil
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if title != nil || trailing != nil {
                // one header height whatever sits at the right, so cards in a row match
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 2) {
                        if let title { Text(title).font(.system(size: 15, weight: .semibold)).foregroundStyle(t.ink) }
                        if let subtitle { Text(subtitle).font(.system(size: 13)).foregroundStyle(t.ink55) }
                    }
                    Spacer()
                    if let trailing { trailing }
                }
                .frame(minHeight: Card.headerHeight, alignment: .top)
            }
            content
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(t.surface))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(t.hair, lineWidth: 1))
    }
}

struct Tile: View {
    @Environment(\.theme) private var t
    let label: String
    let value: String
    let subtitle: String
    var color: Color? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label.uppercased()).font(.system(size: 11, weight: .medium)).tracking(1).foregroundStyle(t.ink55)
            Text(value).font(.system(size: 24, weight: .medium)).monospacedDigit().foregroundStyle(color ?? t.ink).lineLimit(1).minimumScaleFactor(0.7)
            Text(subtitle).font(.system(size: 12)).foregroundStyle(t.ink60).lineLimit(1)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(t.surface))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(t.hair, lineWidth: 1))
    }
}

/// A row of full-width pages swiped sideways, at a fixed height, with the indicator
/// below: 4 pt dots at 24 % ink, the current page a 14 × 4 accent pill that slides on swipe.
struct PagedRow<Page: View>: View {
    @Environment(\.theme) private var t
    let count: Int
    let height: CGFloat
    @ViewBuilder let page: (Int) -> Page
    @State private var current = 0

    var body: some View {
        VStack(spacing: 10) {
            TabView(selection: $current) {
                ForEach(0..<max(count, 1), id: \.self) { i in
                    page(i).frame(maxHeight: .infinity, alignment: .top).tag(i)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .frame(height: height)
            if count > 1 {
                HStack(spacing: 5) {
                    ForEach(0..<count, id: \.self) { i in
                        Capsule()
                            .fill(i == current ? t.accent : t.ink.opacity(0.24))
                            .frame(width: i == current ? 14 : 4, height: 4)
                    }
                }
                .animation(.easeInOut(duration: 0.2), value: current)
            }
        }
    }
}

/// Two tiles per page, swiped sideways: the phone's version of the tile row.
struct TilePager: View {
    let tiles: [Tile]

    var body: some View {
        let pages = stride(from: 0, to: tiles.count, by: 2).map { Array(tiles[$0..<min($0 + 2, tiles.count)]) }
        PagedRow(count: pages.count, height: 96) { i in
            HStack(spacing: 12) {
                ForEach(Array(pages[i].enumerated()), id: \.offset) { _, tile in tile }
                if pages[i].count == 1 { Color.clear.frame(maxWidth: .infinity) }
            }
        }
    }
}

struct GradeBadge: View {
    @Environment(\.theme) private var t
    let grade: String

    var body: some View {
        let fg: Color = grade == "A" || grade == "B" ? t.pos : (grade == "F" ? t.neg : (grade == "C" ? t.ink75 : t.ink55))
        Text(grade.isEmpty ? BHFmt.dash : grade)
            .font(.system(size: 13, weight: .semibold)).foregroundStyle(fg)
            .frame(width: 30, height: 30)
            .background(RoundedRectangle(cornerRadius: 7).fill(fg.opacity(0.14)))
    }
}

struct TagChip: View {
    @Environment(\.theme) private var t
    let text: String
    var body: some View {
        Text(text).font(.system(size: 12, weight: .medium)).foregroundStyle(t.chipFg)
            .padding(.horizontal, 8).padding(.vertical, 5).background(RoundedRectangle(cornerRadius: 6).fill(t.chipBg))
    }
}

/// The page with nothing to show (SPEC.md §4).
struct EmptyPage: View {
    @Environment(\.theme) private var t
    @ObservedObject var book: Book
    let chrome: Chrome

    var body: some View {
        VStack(spacing: 14) {
            Spacer()
            if book.phase == .pulling {
                Text("Pulling your history").font(.system(size: 22, weight: .semibold)).foregroundStyle(t.ink)
                Text("The first sync can take a minute.").font(.system(size: 15)).foregroundStyle(t.ink60)
            } else {
                Text("No activity yet").font(.system(size: 22, weight: .semibold)).foregroundStyle(t.ink)
                if book.connected {
                    Text("Nothing has come back from Wealthsimple yet.").font(.system(size: 15)).foregroundStyle(t.ink60)
                    Button("Sync now") { book.syncNow() }.buttonStyle(.borderedProminent)
                } else {
                    Text("Connect Wealthsimple to pull your trades.").font(.system(size: 15)).foregroundStyle(t.ink60)
                    Button("Connect Wealthsimple", action: chrome.onConnect).buttonStyle(.borderedProminent)
                }
                if case .failed(let msg) = book.phase {
                    Text(msg).font(.system(size: 14)).foregroundStyle(t.neg).multilineTextAlignment(.center).padding(.horizontal, 32)
                }
            }
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }
}

// MARK: - Dashboard

struct DashboardScreen: View {
    @Environment(\.theme) private var t
    @ObservedObject var book: Book
    @Binding var tab: Int
    let chrome: Chrome
    @State private var symbolSort = "pnl"
    @State private var symbolDesc = true
    @State private var equityPick: Int? = nil
    @State private var pnlPick: Int? = nil

    /// The swiping row's cards share one body height; the row is that plus the card's header and padding.
    static let bodyHeight: CGFloat = 150
    static let rowHeight: CGFloat = bodyHeight + 12 + Card<EmptyView>.headerHeight + 24

    var body: some View {
        VStack(spacing: 0) {
            Header(book: book, chrome: chrome)
            FilterChips(book: book)
            if let v = book.view {
                ScrollView(showsIndicators: false) {
                    VStack(spacing: 12) {
                        tiles(v)
                        Card(title: "Equity", trailing: AnyView(equityAmount(v))) {
                            if v.equity.series.count > 1 { EquityCurveChart(series: v.equity.series, pick: $equityPick) }
                            else { Text("No equity history for this span.").font(.system(size: 14)).foregroundStyle(t.ink55) }
                        }
                        // Annual returns, P&L and Grade vs P&L: one swiping row of equal cards
                        PagedRow(count: 3, height: Self.rowHeight) { i in
                            switch i {
                            case 0: AnyView(annualized(v))
                            case 1: AnyView(pnl(v))
                            default: AnyView(Card(title: "Grade vs P&L") { GradeBarsChart(grades: v.grades, height: Self.bodyHeight - 20).frame(height: Self.bodyHeight, alignment: .top) })
                            }
                        }
                        bySymbol(v)
                        queue(v)
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 90)
                }
            } else {
                EmptyPage(book: book, chrome: chrome)
            }
        }
        .background(t.bg)
        .toolbar(.hidden, for: .navigationBar)
        .navigationDestination(for: String.self) { id in TradeDetailScreen(book: book, tradeId: id) }
    }

    private func tiles(_ v: BHView) -> some View {
        let k = v.kpi
        let dd = v.equity.drawdown
        let ann = v.equity.annualized
        let tiles: [Tile] = [
            Tile(label: "Realized P&L", value: BHFmt.money(k.realized), subtitle: "\(k.count) trade" + (k.count == 1 ? "" : "s"), color: t.signed(k.realized)),
            Tile(label: "Win rate", value: BHFmt.pct(k.winRate, signed: false), subtitle: "\(k.wins) W · \(k.losses) L" + (k.breakeven > 0 ? " · \(k.breakeven) BE" : "")),
            Tile(label: "Profit factor", value: BHFmt.profitFactor(k), subtitle: "W " + BHFmt.wholeMoney(k.grossWin) + " · L " + BHFmt.wholeMoney(k.grossLoss)),
            Tile(label: "Expectancy", value: BHFmt.money(k.expectancy), subtitle: "avg W " + BHFmt.wholeMoney(k.avgWin) + " · L " + BHFmt.wholeMoney(abs(k.avgLoss))),
            Tile(label: "Max drawdown", value: dd.pct.map { BHFmt.pct($0) } ?? BHFmt.dash,
                 subtitle: dd.abs.map { BHFmt.compactMoney($0) + " · " + BHFmt.monthAxis(dd.at) } ?? BHFmt.dash, color: dd.pct.map { $0 < 0 ? t.neg : t.ink }),
            Tile(label: "Avg annualized", value: BHFmt.pct(ann.rate), subtitle: ann.count > 0 ? "over \(ann.count) year" + (ann.count == 1 ? "" : "s") : BHFmt.dash,
                 color: ann.rate.map { t.signed($0) }),
        ]
        return TilePager(tiles: tiles)
    }

    private func annualized(_ v: BHView) -> some View {
        let scale = v.years.flatMap { [abs($0.r), abs($0.spR ?? 0)] }.max() ?? 1
        let picker = Menu {
            ForEach(["SP500", "TSX", "TSX60"], id: \.self) { key in
                Button(BHModel.benchmarkLabels[key] ?? key) { book.setBenchmark(key) }
            }
        } label: {
            HStack(spacing: 4) {
                Text("Vs " + v.benchmarkLabel).font(.system(size: 13, weight: .medium))
                Image(systemName: "chevron.down").font(.system(size: 10, weight: .semibold))
            }
            .foregroundStyle(t.ink75).padding(.horizontal, 10).padding(.vertical, 4).background(RoundedRectangle(cornerRadius: 7).fill(t.well))
        }
        // the years scroll inside the card's fixed body
        return Card(title: "Annual returns", trailing: AnyView(picker)) {
            if v.years.isEmpty {
                Text("No equity history for this span.").font(.system(size: 14)).foregroundStyle(t.ink55).frame(height: Self.bodyHeight, alignment: .top)
            } else {
                ScrollView(showsIndicators: false) {
                    VStack(spacing: 12) {
                        ForEach(v.years.reversed(), id: \.year) { y in
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(y.year).font(.system(size: 16, weight: .medium)).foregroundStyle(t.ink)
                                    Spacer()
                                    HStack(spacing: 4) {
                                        Text(BHFmt.pct(y.r)).foregroundStyle(t.signed(y.r))
                                        Text("/").foregroundStyle(t.ink55)
                                        Text(BHFmt.pct(y.spR)).foregroundStyle(y.spR.map { t.signed($0) } ?? t.ink55)
                                    }
                                    .font(.system(size: 15, weight: .medium)).monospacedDigit()
                                }
                                YearPairBars(mine: y.r, index: y.spR, scale: scale)
                            }
                        }
                    }
                }
                .frame(height: Self.bodyHeight)
            }
        }
    }

    /// The P&L in scope at the card's top right; the pressed month's while the chart is pressed.
    private func pnl(_ v: BHView) -> some View {
        let value = pnlPick.flatMap { i in v.monthly.indices.contains(i) ? v.monthly[i].value : nil } ?? v.monthly.reduce(0.0) { $0 + $1.value }
        let amount = Text(BHFmt.money(value)).font(.system(size: 15, weight: .semibold)).monospacedDigit().foregroundStyle(t.signed(value))
        return Card(title: "P&L", trailing: AnyView(amount)) {
            if v.monthly.isEmpty { Text("No closed trades in this span.").font(.system(size: 14)).foregroundStyle(t.ink55).frame(height: Self.bodyHeight, alignment: .top) }
            else {
                PnlBarsChart(months: v.monthly, pick: $pnlPick, height: Self.bodyHeight - 20) { m in
                    var f = book.filters
                    f.preset = "all"; f.years = []
                    f.from = m.key + "-01"
                    f.to = BHModel.shiftDate(BHModel.shiftDate(m.key + "-01", 31).prefix(7) + "-01", -1)
                    book.setFilters(f)
                    tab = 1
                }
            }
        }
    }

    /// The current equity at the card's top right; the pressed day's while the chart is pressed.
    private func equityAmount(_ v: BHView) -> some View {
        let point = equityPick.flatMap { i in v.equity.series.indices.contains(i) ? v.equity.series[i] : nil } ?? v.equity.series.last
        return Group {
            if let point {
                Text(BHFmt.money(point.v)).font(.system(size: 15, weight: .semibold)).monospacedDigit().foregroundStyle(t.ink)
            }
        }
    }

    static func symbolLine(_ r: BHSymbolRow) -> String {
        let trades = "\(r.n) trade" + (r.n == 1 ? "" : "s")
        return trades + " · " + BHFmt.pct(r.winRate, signed: false) + " win · " + BHFmt.hold(Int(r.avgHold.rounded())) + " avg"
    }

    static let symbolSorts: [(key: String, label: String)] = [("pnl", "P&L"), ("n", "Trades"), ("winRate", "Win rate"), ("avgHold", "Avg hold")]

    static func symbolValue(_ r: BHSymbolRow, _ key: String) -> Double {
        switch key {
        case "n": return Double(r.n)
        case "winRate": return r.winRate
        case "avgHold": return r.avgHold
        default: return r.pnl
        }
    }

    private func bySymbol(_ v: BHView) -> some View {
        let label = (Self.symbolSorts.first { $0.key == symbolSort }?.label ?? "P&L") + (symbolDesc ? " ▼" : " ▲")
        let rows = v.bySymbol.sorted {
            let a = Self.symbolValue($0, symbolSort), b = Self.symbolValue($1, symbolSort)
            if a != b { return symbolDesc ? a > b : a < b }
            return $0.symbol < $1.symbol
        }
        let menu = Menu {
            ForEach(Self.symbolSorts, id: \.key) { sort in
                Button {
                    if symbolSort == sort.key { symbolDesc.toggle() } else { symbolSort = sort.key; symbolDesc = true }
                } label: {
                    if symbolSort == sort.key { Label(sort.label, systemImage: symbolDesc ? "arrow.down" : "arrow.up") } else { Text(sort.label) }
                }
            }
        } label: {
            Text(label).font(.system(size: 13, weight: .medium)).foregroundStyle(t.ink60)
        }
        return Card(title: "By symbol", trailing: AnyView(menu)) {
            if rows.isEmpty { Text("No closed trades in this span.").font(.system(size: 14)).foregroundStyle(t.ink55) }
            VStack(spacing: 0) {
                ForEach(Array(rows.prefix(12).enumerated()), id: \.element.symbol) { i, r in
                    Button {
                        var f = book.filters
                        f.lists["symbol"] = [r.symbol]
                        book.setFilters(f)
                        tab = 1
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(r.symbol).font(.system(size: 16, weight: .semibold)).foregroundStyle(t.ink)
                                Text(Self.symbolLine(r)).font(.system(size: 13)).foregroundStyle(t.ink60)
                            }
                            Spacer()
                            Text(BHFmt.wholeMoney(r.pnl)).font(.system(size: 17, weight: .medium)).monospacedDigit().foregroundStyle(t.signed(r.pnl))
                        }
                        .padding(.top, i == 0 ? 0 : 12)
                        .padding(.bottom, i == min(rows.count, 12) - 1 ? 0 : 12)
                    }
                    .buttonStyle(.plain)
                    if i < min(rows.count, 12) - 1 { Divider().overlay(t.hair) }
                }
            }
        }
    }

    private func queue(_ v: BHView) -> some View {
        Card(title: "Review queue") {
            if v.queue.isEmpty { Text("Every closed trade has a grade and a thesis.").font(.system(size: 14)).foregroundStyle(t.ink55) }
            VStack(spacing: 8) {
                ForEach(v.queue.prefix(8), id: \.id) { q in
                    NavigationLink(value: q.id) {
                        HStack {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(q.symbol).font(.system(size: 16, weight: .semibold)).foregroundStyle(t.ink)
                                Text(q.date + " · " + q.missing.prefix(1).uppercased() + q.missing.dropFirst()).font(.system(size: 13)).foregroundStyle(t.ink60)
                            }
                            Spacer()
                            Text(BHFmt.money(q.pnl)).font(.system(size: 17, weight: .medium)).monospacedDigit().foregroundStyle(t.signed(q.pnl))
                        }
                        .padding(14)
                        .background(RoundedRectangle(cornerRadius: 10).fill(t.well))
                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(t.hair, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}

// MARK: - Trades

enum TradeSort: String, CaseIterable {
    case close = "Close date", open = "Open date", pnl = "P&L", pnlPct = "P&L %", hold = "Hold", symbol = "Symbol"
}

struct TradesScreen: View {
    @Environment(\.theme) private var t
    @ObservedObject var book: Book
    let chrome: Chrome
    @State private var sort: TradeSort = .close
    @State private var ascending = false

    var body: some View {
        VStack(spacing: 0) {
            Header(book: book, chrome: chrome)
            FilterChips(book: book)
            if let v = book.view {
                let trades = sorted(v.trades)
                ScrollView(showsIndicators: false) {
                    LazyVStack(spacing: 0) {
                        HStack {
                            Text("\(trades.count) closed · sorted by \(sort.rawValue.lowercased())").font(.system(size: 14)).foregroundStyle(t.ink60)
                            Spacer()
                            Menu {
                                ForEach(TradeSort.allCases, id: \.self) { s in Button(s.rawValue) { if sort == s { ascending.toggle() } else { sort = s; ascending = false } } }
                            } label: {
                                HStack(spacing: 6) {
                                    Image(systemName: ascending ? "arrow.up" : "arrow.down").font(.system(size: 11, weight: .semibold))
                                    Text("Sort").font(.system(size: 14, weight: .medium))
                                }
                                .foregroundStyle(t.ink75).padding(.horizontal, 12).padding(.vertical, 8)
                                .background(RoundedRectangle(cornerRadius: 8).fill(t.surface)).overlay(RoundedRectangle(cornerRadius: 8).stroke(t.hair, lineWidth: 1))
                            }
                        }
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        ForEach(trades, id: \.id) { tr in
                            NavigationLink(value: tr.id) { TradeCard(trade: tr) }.buttonStyle(.plain)
                            Divider().overlay(t.hair).padding(.horizontal, 16)
                        }
                        if trades.isEmpty {
                            Text(v.tradeTotal == 0 ? "No closed trades yet." : "No closed trades match these filters.").font(.system(size: 14)).foregroundStyle(t.ink55).padding(.top, 40)
                        }
                    }
                    .padding(.bottom, 90)
                }
            } else {
                EmptyPage(book: book, chrome: chrome)
            }
        }
        .background(t.bg)
        .toolbar(.hidden, for: .navigationBar)
        .navigationDestination(for: String.self) { id in TradeDetailScreen(book: book, tradeId: id) }
    }

    private func sorted(_ trades: [BHTrade]) -> [BHTrade] {
        let s = trades.sorted { a, b in
            switch sort {
            case .close: return (a.exitDate, a.id) < (b.exitDate, b.id)
            case .open: return (a.entryDate, a.id) < (b.entryDate, b.id)
            case .pnl: return a.pnlCad < b.pnlCad
            case .pnlPct: return (a.pnlPct ?? -1e18) < (b.pnlPct ?? -1e18)
            case .hold: return a.holdDays < b.holdDays
            case .symbol: return (a.symbol, a.exitDate) < (b.symbol, b.exitDate)
            }
        }
        return ascending ? s : s.reversed()
    }
}

/// One trade, as the mockup stacks them.
struct TradeCard: View {
    @Environment(\.theme) private var t
    let trade: BHTrade

    var body: some View {
        let dates = trade.entryDate + " → " + trade.exitDate
        let meta = [BHFmt.hold(trade.holdDays), BHFmt.price(trade.entry) + " → " + BHFmt.price(trade.exit), trade.currency].joined(separator: " · ")
        let color = t.signed(trade.pnl)
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline) {
                Text(trade.symbol).font(.system(size: 17, weight: .semibold)).foregroundStyle(t.ink).lineLimit(1)
                Spacer()
                Text(BHFmt.money(trade.pnl)).font(.system(size: 17, weight: .semibold)).monospacedDigit().foregroundStyle(color)
            }
            HStack {
                Text(dates).font(.system(size: 14)).monospacedDigit().foregroundStyle(t.ink60)
                Spacer()
                Text(BHFmt.pct(trade.pnlPct)).font(.system(size: 14)).monospacedDigit().foregroundStyle(color)
            }
            HStack(alignment: .center) {
                Text(meta).font(.system(size: 14)).monospacedDigit().foregroundStyle(t.ink60)
                Spacer()
                HStack(spacing: 6) {
                    ForEach(trade.tags.prefix(2), id: \.self) { TagChip(text: $0) }
                    GradeBadge(grade: trade.grade)
                }
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 14)
        .contentShape(Rectangle())
    }
}

struct TradeDetailScreen: View {
    @Environment(\.theme) private var t
    @ObservedObject var book: Book
    let tradeId: String
    @State private var chart: (bars: [BHBar], reason: String, timeframe: String)? = nil
    @State private var timeframe: String? = nil
    @State private var grade = ""
    @State private var thesis = ""
    @State private var tags = ""
    @State private var loaded = false

    var body: some View {
        Group {
            if let tr = book.trade(id: tradeId) {
                ScrollView(showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 14) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(tr.symbol).font(.system(size: 22, weight: .bold)).foregroundStyle(t.ink)
                            Text(listingLine(tr)).font(.system(size: 14)).foregroundStyle(t.ink60)
                        }
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text(BHFmt.money(tr.pnl)).font(.system(size: 28, weight: .semibold)).monospacedDigit().foregroundStyle(t.signed(tr.pnl))
                            Text(BHFmt.pct(tr.pnlPct)).font(.system(size: 17, weight: .medium)).monospacedDigit().foregroundStyle(t.signed(tr.pnl))
                            Text(tr.currency).font(.system(size: 13)).foregroundStyle(t.ink55)
                        }
                        Card {
                            HStack(spacing: 6) {
                                ForEach(["1d", "1w", "1M"], id: \.self) { tf in
                                    let on = (chart?.timeframe ?? timeframe) == tf
                                    Button(tf.uppercased()) { timeframe = tf }
                                        .font(.system(size: 12, weight: .semibold)).foregroundStyle(on ? t.chipFg : t.ink55)
                                        .padding(.horizontal, 9).padding(.vertical, 5)
                                        .background(RoundedRectangle(cornerRadius: 6).fill(on ? t.chipBg : t.well))
                                        .buttonStyle(.plain)
                                }
                                Spacer()
                            }
                            if let c = chart, !c.bars.isEmpty {
                                CandleChart(bars: c.bars, fills: tr.fills, atClose: tr.kind == "Options")
                            } else {
                                Text(chart?.reason ?? "Fetching bars…").font(.system(size: 14)).foregroundStyle(t.ink55).frame(maxWidth: .infinity, minHeight: 120)
                            }
                        }
                        Card {
                            facts(tr)
                        }
                        Card(title: "Executions") {
                            VStack(spacing: 0) {
                                ForEach(Array(tr.fills.enumerated()), id: \.element.id) { i, f in
                                    HStack(alignment: .center) {
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(f.date + (f.time.isEmpty ? "" : " " + f.time)).font(.system(size: 14)).monospacedDigit().foregroundStyle(t.ink)
                                            Text(f.sub + " · " + BHFmt.qty(abs(f.qty)) + " · " + f.currency + " " + BHFmt.price(f.price)).font(.system(size: 13)).monospacedDigit().foregroundStyle(t.ink60)
                                        }
                                        Spacer()
                                        Text(BHFmt.money(f.amount)).font(.system(size: 15, weight: .medium)).monospacedDigit().foregroundStyle(t.signed(f.amount))
                                    }
                                    .padding(.vertical, 8)
                                    if i < tr.fills.count - 1 { Divider().overlay(t.hair) }
                                }
                            }
                        }
                        Card(title: "Journal") {
                            journal(tr)
                        }
                    }
                    .padding(16)
                    .padding(.bottom, 90)
                }
                .task(id: tradeId + "|" + (timeframe ?? "")) {
                    if !loaded { grade = tr.grade; thesis = tr.thesis; tags = tr.tags.joined(separator: ", "); loaded = true }
                    chart = await MarketData.bars(for: tr, timeframe: timeframe)
                }
            } else {
                Text("This trade is no longer in the book.").foregroundStyle(t.ink55)
            }
        }
        .background(t.bg)
        .navigationTitle("Trade")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(t.bg, for: .navigationBar)
    }

    private func listingLine(_ tr: BHTrade) -> String {
        var parts: [String] = []
        if !tr.name.isEmpty && tr.name != tr.symbol { parts.append(tr.name) }
        let ticker = BHModel.listingTicker(tr.underlying)
        if !tr.exchange.isEmpty { parts.append(tr.exchange.uppercased() + ": " + ticker) } else if tr.underlying != tr.symbol { parts.append(ticker) }
        return parts.joined(separator: " · ")
    }

    private func facts(_ tr: BHTrade) -> some View {
        let rows: [(String, String)] = [
            ("Open", tr.entryDate), ("Close", tr.exitDate), ("Entry", BHFmt.price(tr.entry)), ("Exit", BHFmt.price(tr.exit)),
            ("Qty", BHFmt.qty(tr.qty) + (tr.mult > 1 ? " × \(Int(tr.mult))" : "")), ("Hold", BHFmt.hold(tr.holdDays)), ("Account", tr.account),
            ("P&L (CAD)", BHFmt.money(tr.pnlCad)),
        ]
        return VStack(spacing: 0) {
            ForEach(Array(rows.enumerated()), id: \.offset) { i, r in
                HStack {
                    Text(r.0).font(.system(size: 14)).foregroundStyle(t.ink60)
                    Spacer()
                    Text(r.1).font(.system(size: 14, weight: .medium)).monospacedDigit().foregroundStyle(t.ink)
                }
                .padding(.vertical, 7)
                if i < rows.count - 1 { Divider().overlay(t.hair) }
            }
        }
    }

    private func journal(_ tr: BHTrade) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                ForEach(BHModel.grades, id: \.self) { g in
                    Button {
                        grade = grade == g ? "" : g
                        save()
                    } label: {
                        Text(g).font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(grade == g ? t.chipFg : t.ink75)
                            .frame(width: 44, height: 36)
                            .background(RoundedRectangle(cornerRadius: 8).fill(grade == g ? t.chipBg : t.well))
                    }
                    .buttonStyle(.plain)
                }
                Spacer()
            }
            TextField("Thesis", text: $thesis, axis: .vertical)
                .lineLimit(2...6)
                .font(.system(size: 15)).foregroundStyle(t.ink)
                .padding(10).background(RoundedRectangle(cornerRadius: 8).fill(t.well))
                .onChange(of: thesis) { _, _ in save() }
            TextField("Tags, comma separated", text: $tags)
                .font(.system(size: 15)).foregroundStyle(t.ink)
                .autocorrectionDisabled().textInputAutocapitalization(.never)
                .padding(10).background(RoundedRectangle(cornerRadius: 8).fill(t.well))
                .onChange(of: tags) { _, _ in save() }
        }
    }

    private func save() {
        let list = tags.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        book.saveJournal(id: tradeId, BHJournalEntry(grade: grade, thesis: thesis, tags: list))
    }
}

// MARK: - Positions

struct PositionsScreen: View {
    @Environment(\.theme) private var t
    @ObservedObject var book: Book
    let chrome: Chrome

    var body: some View {
        VStack(spacing: 0) {
            Header(book: book, chrome: chrome)
            FilterChips(book: book)
            if let v = book.view {
                let s = v.positionsSummary
                ScrollView(showsIndicators: false) {
                    LazyVStack(spacing: 0) {
                        HStack(spacing: 0) {
                            Text("\(s.count) open · Book " + BHFmt.wholeMoney(s.book) + " · P&L ").font(.system(size: 14)).foregroundStyle(t.ink60)
                            Text(BHFmt.signedMoney(s.unreal, digits: 0)).font(.system(size: 14, weight: .medium)).monospacedDigit().foregroundStyle(t.signed(s.unreal))
                            Spacer()
                        }
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        ForEach(v.positions, id: \.id) { p in
                            NavigationLink(value: p.id) { PositionCard(position: p) }.buttonStyle(.plain)
                            Divider().overlay(t.hair).padding(.horizontal, 16)
                        }
                        if v.positions.isEmpty {
                            Text("No open positions.").font(.system(size: 14)).foregroundStyle(t.ink55).padding(.top, 40)
                        }
                    }
                    .padding(.bottom, 90)
                }
            } else {
                EmptyPage(book: book, chrome: chrome)
            }
        }
        .background(t.bg)
        .toolbar(.hidden, for: .navigationBar)
        .navigationDestination(for: String.self) { id in PositionDetailScreen(book: book, positionId: id) }
    }
}

struct PositionCard: View {
    @Environment(\.theme) private var t
    let position: BHPosition

    var body: some View {
        let p = position
        let line1 = (p.short ? "SHORT " : "") + BHFmt.qty(p.qty) + " · " + BHFmt.price(p.avg) + " → " + BHFmt.price(p.last) + " · " + p.currency
        let line2 = "Book " + BHFmt.wholeMoney(p.cost) + " · Market " + BHFmt.wholeMoney(p.mv) + " · " + BHFmt.hold(p.held)
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline) {
                Text(p.symbol).font(.system(size: 17, weight: .semibold)).foregroundStyle(t.ink).lineLimit(1)
                Spacer()
                Text(BHFmt.signedMoney(p.unreal)).font(.system(size: 17, weight: .semibold)).monospacedDigit().foregroundStyle(t.signed(p.unreal))
            }
            HStack {
                Text(line1).font(.system(size: 14)).monospacedDigit().foregroundStyle(t.ink60)
                Spacer()
                Text(BHFmt.pct(p.unrealPct, digits: 2)).font(.system(size: 14)).monospacedDigit().foregroundStyle(t.signed(p.unreal))
            }
            HStack {
                Text(line2).font(.system(size: 14)).monospacedDigit().foregroundStyle(t.ink60)
                Spacer()
                Text(BHFmt.pct(p.alloc, signed: false)).font(.system(size: 13, weight: .medium)).foregroundStyle(t.chipFg)
                    .padding(.horizontal, 8).padding(.vertical, 4).background(RoundedRectangle(cornerRadius: 6).fill(t.chipBg))
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 14)
        .contentShape(Rectangle())
    }
}

struct PositionDetailScreen: View {
    @Environment(\.theme) private var t
    @ObservedObject var book: Book
    let positionId: String
    @State private var thesis = ""
    @State private var tags = ""
    @State private var loaded = false

    var body: some View {
        Group {
            if let p = book.position(id: positionId) {
                ScrollView(showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 14) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(p.symbol).font(.system(size: 22, weight: .bold)).foregroundStyle(t.ink)
                            Text([p.name != p.symbol ? p.name : "", p.exchange].filter { !$0.isEmpty }.joined(separator: " · ")).font(.system(size: 14)).foregroundStyle(t.ink60)
                        }
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text(BHFmt.signedMoney(p.unreal)).font(.system(size: 28, weight: .semibold)).monospacedDigit().foregroundStyle(t.signed(p.unreal))
                            Text(BHFmt.pct(p.unrealPct, digits: 2)).font(.system(size: 17, weight: .medium)).monospacedDigit().foregroundStyle(t.signed(p.unreal))
                            Text(p.currency).font(.system(size: 13)).foregroundStyle(t.ink55)
                        }
                        Card {
                            let rows: [(String, String)] = [
                                ("Qty", BHFmt.qty(p.qty)), ("Hold", BHFmt.hold(p.held)), ("Avg cost", BHFmt.price(p.avg)),
                                ("Price", BHFmt.price(p.last) + (p.priceSource == "quote" ? "" : " · last fill " + p.lastAt)),
                                ("Book value", BHFmt.money(p.cost)), ("Market value", BHFmt.money(p.mv)), ("FX", p.currency),
                                ("Allocation", BHFmt.pct(p.alloc, signed: false)), ("Account", p.account),
                            ]
                            VStack(spacing: 0) {
                                ForEach(Array(rows.enumerated()), id: \.offset) { i, r in
                                    HStack {
                                        Text(r.0).font(.system(size: 14)).foregroundStyle(t.ink60)
                                        Spacer()
                                        Text(r.1).font(.system(size: 14, weight: .medium)).monospacedDigit().foregroundStyle(t.ink).multilineTextAlignment(.trailing)
                                    }
                                    .padding(.vertical, 7)
                                    if i < rows.count - 1 { Divider().overlay(t.hair) }
                                }
                            }
                        }
                        Card(title: "Lots") {
                            VStack(spacing: 0) {
                                ForEach(Array(p.lots.enumerated()), id: \.offset) { i, l in
                                    HStack {
                                        Text(l.opened).font(.system(size: 14)).monospacedDigit().foregroundStyle(t.ink)
                                        Spacer()
                                        Text(BHFmt.qty(l.qty) + " · " + BHFmt.price(l.price)).font(.system(size: 14)).monospacedDigit().foregroundStyle(t.ink60)
                                        Text(BHFmt.money(l.basis)).font(.system(size: 14, weight: .medium)).monospacedDigit().foregroundStyle(t.ink).frame(width: 110, alignment: .trailing)
                                    }
                                    .padding(.vertical, 7)
                                    if i < p.lots.count - 1 { Divider().overlay(t.hair) }
                                }
                            }
                        }
                        Card(title: "Note") {
                            VStack(alignment: .leading, spacing: 12) {
                                TextField("Thesis", text: $thesis, axis: .vertical).lineLimit(2...6)
                                    .font(.system(size: 15)).foregroundStyle(t.ink).padding(10).background(RoundedRectangle(cornerRadius: 8).fill(t.well))
                                    .onChange(of: thesis) { _, _ in save() }
                                TextField("Tags, comma separated", text: $tags)
                                    .font(.system(size: 15)).foregroundStyle(t.ink).autocorrectionDisabled().textInputAutocapitalization(.never)
                                    .padding(10).background(RoundedRectangle(cornerRadius: 8).fill(t.well))
                                    .onChange(of: tags) { _, _ in save() }
                            }
                        }
                    }
                    .padding(16)
                    .padding(.bottom, 90)
                }
                .task(id: positionId) {
                    if !loaded { thesis = p.thesis; tags = p.tags.joined(separator: ", "); loaded = true }
                }
            } else {
                Text("This position is no longer open.").foregroundStyle(t.ink55)
            }
        }
        .background(t.bg)
        .navigationTitle("Position")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(t.bg, for: .navigationBar)
    }

    private func save() {
        let list = tags.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        let old = book.journal[positionId] ?? BHJournalEntry()
        book.saveJournal(id: positionId, BHJournalEntry(grade: old.grade, thesis: thesis, tags: list))
    }
}

// MARK: - Cashflow

struct CashflowScreen: View {
    @Environment(\.theme) private var t
    @ObservedObject var book: Book
    let chrome: Chrome
    @AppStorage("bagholder.allocationBy") private var allocBy = "market"
    @State private var picked: Int?
    @State private var distPick: Int? = nil

    var body: some View {
        VStack(spacing: 0) {
            Header(book: book, chrome: chrome)
            FilterChips(book: book)
            if let v = book.view {
                let cf = v.cashflow
                ScrollView(showsIndicators: false) {
                    VStack(spacing: 12) {
                        if !cf.skipped.isEmpty {
                            Text("Ignoring " + cf.skipped.joined(separator: ", ") + ".").font(.system(size: 13)).foregroundStyle(t.ink55).frame(maxWidth: .infinity, alignment: .leading)
                        }
                        tiles(cf)
                        distributions(cf)
                        allocation(cf)
                        holdings(cf)
                        history(cf)
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 90)
                }
            } else {
                EmptyPage(book: book, chrome: chrome)
            }
        }
        .background(t.bg)
        .toolbar(.hidden, for: .navigationBar)
    }

    private func tiles(_ cf: BHCashflowView) -> some View {
        func tile(_ tile: BHTile) -> Tile {
            if tile.label == "Yield on cost" {
                return Tile(label: tile.label, value: BHFmt.pct(tile.yield, digits: 2, signed: false), subtitle: BHFmt.wholeMoney(tile.earned) + " on " + BHFmt.wholeMoney(tile.book))
            }
            return Tile(label: tile.label, value: BHFmt.money(tile.total), subtitle: BHFmt.money(tile.perMonth) + " / month")
        }
        // YTD and Yield on cost first, then All time and the past years
        let ytd = cf.tiles.first { $0.label.hasSuffix("YTD") }
        let yoc = cf.tiles.first { $0.label == "Yield on cost" }
        let all = cf.tiles.first { $0.label == "All time" }
        let years = cf.tiles.filter { !$0.label.hasSuffix("YTD") && $0.label != "Yield on cost" && $0.label != "All time" }.reversed()
        let ordered = [ytd, yoc, all].compactMap { $0 } + years
        return TilePager(tiles: ordered.map(tile))
    }

    /// The projected month at the card's top right; the pressed month's payout while the chart is pressed.
    private func distributions(_ cf: BHCashflowView) -> some View {
        let projected = cf.holdings.reduce(0.0) { $0 + ($1.annual ?? 0) / 12 }
        let value = distPick.flatMap { i in cf.months.indices.contains(i) ? cf.months[i].value : nil } ?? projected
        let amount = Text(BHFmt.money(value)).font(.system(size: 15, weight: .semibold)).monospacedDigit().foregroundStyle(t.ink)
        return Card(title: "Distributions", trailing: AnyView(amount)) {
            if cf.months.isEmpty { Text("No distributions in this span.").font(.system(size: 14)).foregroundStyle(t.ink55) }
            else {
                PnlBarsChart(months: cf.months.map { BHMonthBucket(key: $0.key, label: $0.label, value: $0.value, count: $0.count) }, pick: $distPick, color: t.accent)
            }
        }
    }

    private func allocation(_ cf: BHCashflowView) -> some View {
        let items: [(label: String, value: Double)] = cf.holdings.map { h in
            (h.symbol + (cf.holdings.filter { $0.symbol == h.symbol }.count > 1 ? " · " + h.account : ""), allocBy == "projected" ? (h.annual ?? 0) / 12 : h.qty * h.last)
        }.filter { $0.value > 0 }.sorted { $0.value > $1.value }
        let total = items.reduce(0.0) { $0 + $1.value }
        let switcher = HStack(spacing: 0) {
            ForEach(["market", "projected"], id: \.self) { k in
                Button(k == "market" ? "Market" : "Projected") { allocBy = k; picked = nil }
                    .font(.system(size: 13, weight: .medium)).foregroundStyle(allocBy == k ? t.ink : t.ink55)
                    .padding(.horizontal, 10).padding(.vertical, 4)
                    .background(RoundedRectangle(cornerRadius: 7).fill(allocBy == k ? t.well : .clear))
            }
        }
        return Card(title: "Allocation", trailing: AnyView(switcher)) {
            if items.isEmpty { Text("No income holdings in scope.").font(.system(size: 14)).foregroundStyle(t.ink55) }
            else {
                HStack(alignment: .center, spacing: 16) {
                    DonutChart(slices: items, picked: picked, onPick: { picked = $0 }, size: 150)
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(Array(items.prefix(8).enumerated()), id: \.offset) { i, s in
                            HStack(spacing: 8) {
                                Circle().fill(t.pie[i % t.pie.count]).frame(width: 8, height: 8)
                                Text(s.label).font(.system(size: 13, weight: .medium)).foregroundStyle(t.ink).lineLimit(1)
                                Spacer()
                                Text(BHFmt.pct(total > 0 ? s.value / total : nil, signed: false)).font(.system(size: 13)).monospacedDigit().foregroundStyle(t.ink60)
                            }
                        }
                    }
                }
            }
        }
    }

    private func holdings(_ cf: BHCashflowView) -> some View {
        Card(title: "Positions") {
            if cf.holdings.isEmpty { Text("No income holdings in scope.").font(.system(size: 14)).foregroundStyle(t.ink55) }
            VStack(spacing: 0) {
                ForEach(Array(cf.holdings.enumerated()), id: \.element.id) { i, h in
                    // the month's projected payout at the right with the yield on cost under it
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(h.symbol).font(.system(size: 16, weight: .semibold)).foregroundStyle(t.ink)
                                Text(Self.rateLine(h)).font(.system(size: 13)).monospacedDigit().foregroundStyle(t.ink60)
                            }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(h.annual.map { BHFmt.money($0 / 12) + " / mo" } ?? BHFmt.dash).font(.system(size: 15, weight: .medium)).monospacedDigit().foregroundStyle(t.ink)
                                Text(BHFmt.pct(h.yoc, digits: 2, signed: false)).font(.system(size: 13)).monospacedDigit().foregroundStyle(t.ink60)
                            }
                        }
                        HStack(spacing: 12) {
                            fact("Ex-Div", h.nextExDate.isEmpty ? BHFmt.dash : h.nextExDate, muted: h.exPast)
                            fact("Pay Day", h.nextPayDate.isEmpty ? BHFmt.dash : h.nextPayDate, muted: h.payPast)
                        }
                    }
                    .padding(.top, i == 0 ? 0 : 10)
                    .padding(.bottom, i == cf.holdings.count - 1 ? 0 : 10)
                    if i < cf.holdings.count - 1 { Divider().overlay(t.hair) }
                }
            }
        }
    }

    static func rateLine(_ h: BHHolding) -> String {
        var s = BHFmt.qty(h.qty) + " · avg " + BHFmt.price(h.avg) + " · " + BHFmt.perUnit(h.per)
        if let f = h.freq { s += " × \(f)" }
        if !h.freqVerified { s += " assumed" }
        return s
    }

    private func fact(_ label: String, _ value: String, muted: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label.uppercased()).font(.system(size: 10, weight: .medium)).tracking(0.6).foregroundStyle(t.ink55)
            Text(value).font(.system(size: 13, weight: .medium)).monospacedDigit().foregroundStyle(muted ? t.ink55 : t.ink)
        }
    }

    static func historyLine(_ r: BHCashRow) -> String {
        var s = r.date
        if let q = r.qty { s += " · " + BHFmt.qty(q) + " × " + BHFmt.perUnit(r.per) }
        return s
    }

    private func history(_ cf: BHCashflowView) -> some View {
        Card(title: "History") {
            if cf.rows.isEmpty { Text("No distributions in this span.").font(.system(size: 14)).foregroundStyle(t.ink55) }
            VStack(spacing: 0) {
                ForEach(Array(cf.rows.prefix(60).enumerated()), id: \.element.id) { i, r in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(r.symbol).font(.system(size: 15, weight: .semibold)).foregroundStyle(t.ink)
                            Text(Self.historyLine(r)).font(.system(size: 13)).monospacedDigit().foregroundStyle(t.ink60).lineLimit(1)
                        }
                        Spacer()
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(BHFmt.money(r.amount)).font(.system(size: 15, weight: .medium)).monospacedDigit().foregroundStyle(t.ink)
                            Text(r.currency).font(.system(size: 12)).foregroundStyle(t.ink55)
                        }
                    }
                    .padding(.top, i == 0 ? 0 : 9)
                    .padding(.bottom, i == min(cf.rows.count, 60) - 1 ? 0 : 9)
                    if i < min(cf.rows.count, 60) - 1 { Divider().overlay(t.hair) }
                }
            }
        }
    }
}

// MARK: - the filter sheet

struct FiltersSheet: View {
    @Environment(\.theme) private var t
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var book: Book
    @State private var draft: BHFilters = BHFilters()
    @State private var query = ""
    @FocusState private var searchFocused: Bool

    private let fieldNames = ["symbol": "Symbol", "account": "Account", "grade": "Grade", "tag": "Tag", "side": "Side", "kind": "Kind", "exchange": "Exchange", "result": "Result"]
    private let fieldOrder = ["symbol", "account", "grade", "tag", "side", "kind", "exchange", "result"]

    var body: some View {
        let o = book.view?.options ?? BHOptions()
        NavigationStack {
            VStack(spacing: 0) {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass").foregroundStyle(t.ink55)
                    TextField("Search symbols, accounts, tags…", text: $query)
                        .focused($searchFocused).autocorrectionDisabled().textInputAutocapitalization(.characters)
                        .font(.system(size: 16)).foregroundStyle(t.ink)
                    if !query.isEmpty { Button { query = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(t.ink55) } }
                }
                .padding(10).background(RoundedRectangle(cornerRadius: 10).fill(t.well)).padding(16)
                if !query.isEmpty {
                    matches(o)
                } else {
                    fields(o)
                }
            }
            .background(t.bg)
            .navigationTitle("Filters")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Clear all") { draft = BHFilters(); draft.benchmark = book.filters.benchmark } }
                ToolbarItem(placement: .topBarTrailing) { Button("Done") { apply(); dismiss() } }
            }
            .toolbarBackground(t.bg, for: .navigationBar)
        }
        .onAppear { draft = book.filters; searchFocused = true }
        .presentationDetents([.large])
        .presentationBackground(t.bg)
    }

    private func apply() {
        if !query.isEmpty && !hasMatches(query) { draft.search = query }
        book.setFilters(draft)
    }

    private func values(_ field: String, _ o: BHOptions) -> [String] {
        switch field {
        case "symbol": return o.symbols
        case "account": return o.accounts
        case "grade": return o.grades
        case "tag": return o.tags
        case "side": return o.sides
        case "kind": return o.kinds
        case "exchange": return o.exchanges
        case "result": return o.results
        default: return []
        }
    }

    private func hasMatches(_ q: String) -> Bool {
        let o = book.view?.options ?? BHOptions()
        return fieldOrder.contains { f in values(f, o).contains { $0.uppercased().contains(q.uppercased()) } }
    }

    private func matches(_ o: BHOptions) -> some View {
        let q = query.uppercased()
        let rows: [(String, String)] = fieldOrder.flatMap { f in values(f, o).filter { $0.uppercased().contains(q) }.map { (f, $0) } }
        return ScrollView {
            VStack(spacing: 0) {
                if rows.isEmpty {
                    Text("No value matches. Done searches for \"\(query)\".").font(.system(size: 14)).foregroundStyle(t.ink55).padding()
                }
                ForEach(Array(rows.enumerated()), id: \.offset) { _, r in
                    let on = (draft.lists[r.0] ?? []).contains(r.1)
                    Button { toggle(r.0, r.1) } label: {
                        HStack {
                            Rectangle().fill(on ? t.chipFg : .clear).frame(width: 3)
                            Text(r.1).font(.system(size: 16, weight: on ? .semibold : .regular)).foregroundStyle(t.ink)
                            Spacer()
                            Text(fieldNames[r.0] ?? r.0).font(.system(size: 13)).foregroundStyle(t.ink55)
                        }
                        .padding(.vertical, 10).padding(.trailing, 16)
                        .background(on ? t.well : .clear)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.leading, 10)
        }
    }

    private func toggle(_ field: String, _ value: String) {
        var vals = draft.lists[field] ?? []
        if let i = vals.firstIndex(of: value) { vals.remove(at: i) } else { vals.append(value) }
        draft.lists[field] = vals
    }

    private func fields(_ o: BHOptions) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("DATE").font(.system(size: 11, weight: .medium)).tracking(1).foregroundStyle(t.ink55)
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            ForEach(["all", "1d", "1w", "1m", "3m", "6m", "ytd", "1y", "5y"], id: \.self) { p in
                                pill(p.uppercased(), on: draft.preset == p && draft.years.isEmpty && draft.from.isEmpty && draft.to.isEmpty) {
                                    draft.preset = p; draft.years = []; draft.from = ""; draft.to = ""
                                }
                            }
                            ForEach(o.years, id: \.self) { y in
                                pill(y, on: draft.years.contains(y)) {
                                    if let i = draft.years.firstIndex(of: y) { draft.years.remove(at: i) } else { draft.years.append(y) }
                                    draft.years.sort(); draft.preset = "all"; draft.from = ""; draft.to = ""
                                }
                            }
                        }
                    }
                    HStack {
                        dateField("From", $draft.from)
                        dateField("To", $draft.to)
                    }
                }
                ForEach(fieldOrder, id: \.self) { f in
                    let vals = values(f, o)
                    if !vals.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text((fieldNames[f] ?? f).uppercased()).font(.system(size: 11, weight: .medium)).tracking(1).foregroundStyle(t.ink55)
                            FlowLayout(spacing: 6) {
                                ForEach(vals, id: \.self) { v in
                                    pill(v, on: (draft.lists[f] ?? []).contains(v)) { toggle(f, v) }
                                }
                            }
                        }
                    }
                }
                VStack(alignment: .leading, spacing: 8) {
                    Text("RANGES").font(.system(size: 11, weight: .medium)).tracking(1).foregroundStyle(t.ink55)
                    ForEach([("price", "Price"), ("hold", "Hold"), ("pnl", "P&L"), ("qty", "Qty")], id: \.0) { k, name in
                        HStack(spacing: 8) {
                            Text(name).font(.system(size: 15)).foregroundStyle(t.ink).frame(width: 56, alignment: .leading)
                            Picker("", selection: Binding(get: { draft.ranges[k]?.op ?? ">" }, set: { draft.ranges[k]?.op = $0 })) {
                                Text(">").tag(">"); Text("<").tag("<")
                            }
                            .pickerStyle(.segmented).frame(width: 90)
                            TextField("value", text: Binding(
                                get: { draft.ranges[k]?.v.map { BHFmt.qty($0).replacingOccurrences(of: ",", with: "") } ?? "" },
                                set: { draft.ranges[k]?.v = Double($0.replacingOccurrences(of: ",", with: "")) }))
                                .keyboardType(.numbersAndPunctuation).font(.system(size: 15)).foregroundStyle(t.ink)
                                .padding(8).background(RoundedRectangle(cornerRadius: 8).fill(t.well))
                        }
                    }
                }
            }
            .padding(16)
        }
    }

    private func pill(_ text: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(text).font(.system(size: 14, weight: on ? .semibold : .regular)).foregroundStyle(on ? t.chipFg : t.ink75)
                .padding(.horizontal, 11).padding(.vertical, 7)
                .background(RoundedRectangle(cornerRadius: 8).fill(on ? t.chipBg : t.well))
        }
        .buttonStyle(.plain)
    }

    private func dateField(_ label: String, _ text: Binding<String>) -> some View {
        HStack(spacing: 6) {
            Text(label).font(.system(size: 13)).foregroundStyle(t.ink55)
            TextField("YYYY-MM-DD", text: text).font(.system(size: 14)).monospacedDigit().foregroundStyle(t.ink)
                .keyboardType(.numbersAndPunctuation).autocorrectionDisabled()
                .padding(8).background(RoundedRectangle(cornerRadius: 8).fill(t.well))
                .onChange(of: text.wrappedValue) { _, v in if v.count == 10 { draft.preset = "all"; draft.years = [] } }
        }
    }
}

/// Wraps its children onto as many rows as they need.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 360
        var x: CGFloat = 0, y: CGFloat = 0, rowH: CGFloat = 0
        for s in subviews {
            let sz = s.sizeThatFits(.unspecified)
            if x + sz.width > width && x > 0 { x = 0; y += rowH + spacing; rowH = 0 }
            x += sz.width + spacing
            rowH = max(rowH, sz.height)
        }
        return CGSize(width: width, height: y + rowH)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x: CGFloat = 0, y: CGFloat = 0, rowH: CGFloat = 0
        for s in subviews {
            let sz = s.sizeThatFits(.unspecified)
            if x + sz.width > bounds.width && x > 0 { x = 0; y += rowH + spacing; rowH = 0 }
            s.place(at: CGPoint(x: bounds.minX + x, y: bounds.minY + y), proposal: ProposedViewSize(sz))
            x += sz.width + spacing
            rowH = max(rowH, sz.height)
        }
    }
}

// MARK: - the menu

struct MenuSheet: View {
    @Environment(\.theme) private var t
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var book: Book
    @State private var showConnect = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    if book.connected {
                        Button("Sync now") { book.syncNow(); dismiss() }.disabled(book.phase == .pulling)
                        Button("Disconnect", role: .destructive) { book.disconnect(); dismiss() }
                    } else {
                        // the login opens over the menu at once; waiting for the menu to dismiss first left the tap dead
                        Button("Connect Wealthsimple") { showConnect = true }
                    }
                }
                .listRowBackground(t.surface)
                Section {
                    HStack { Text("Activities"); Spacer(); Text("\(book.result?.activities.count ?? 0)").foregroundStyle(t.ink55) }
                    HStack { Text("Version"); Spacer(); Text(Book.appVersion).foregroundStyle(t.ink55) }
                }
                .listRowBackground(t.surface)
            }
            .fullScreenCover(isPresented: $showConnect) { ConnectLoginView(book: book, isPresented: $showConnect).environment(\.theme, t) }
            .onChange(of: book.connected) { _, on in if on { dismiss() } }
            .scrollContentBackground(.hidden)
            .background(t.bg)
            .navigationTitle("Bagholder")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
            .toolbarBackground(t.bg, for: .navigationBar)
        }
        .presentationDetents([.medium])
        .presentationBackground(t.bg)
    }
}
