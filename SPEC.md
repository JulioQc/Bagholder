# Bagholder specification

This file is the authority on what the app shows and how each figure is computed. Any change to the page, whether it comes from a design handoff or from code, is checked against this file before it is committed. If a change needs a definition here to be different, this file changes first and the reason is recorded in the commit.

The model lives in `model.py` and is served as JSON by `GET /api/model`. The page, `ledger.html`, only renders that JSON. It performs no matching, no aggregation and no currency conversion of its own. The one exception is dividing an annual figure by twelve to show it per month.

## 1. Principles

- **Accuracy over convenience.** A number on the page is either exactly what this file defines or it is not shown. A blank is rendered as an em dash.
- **Payout frequency is verified from the fund's own record, every day.** Each dividend payer's declared distribution history is fetched from TMX Money, the public record the fund itself publishes, and refetched whenever the stored copy is more than 20 hours old, on start and on every sync. Frequency is computed from the gaps between the most recent ex-dates in that record, not from any stored setting, so it is correct from the first holding day even with no payment history, and a schedule change is picked up after two payments at the new cadence. Only when a fund has no declared record does the holding's own received payments stand in, and only a fund that has paid exactly once is treated as monthly until its second payment.
- **Currency.** Every figure that belongs to one trade, position, fill or distribution is in that instrument's own currency, with no prefix and no conversion. Every figure that adds trades or distributions together is in CAD, converted on the date of each fill or payment with the Bank of Canada rate. The app is for Wealthsimple users, so CAD is the home currency and is never labelled: a currency code appears only in the FX column of a per-instrument row, never on a tile, a total, or as a prefix on an amount.
- **Raw data is never rewritten.** Wealthsimple activity rows are stored once and left as received. Everything derived is recomputed from them.
- **Nothing is added that was not asked for.** No captions, tooltips, notes or helper text beyond what this file lists. Browser tooltips (`title` attributes) do not belong on cards or chart elements; the only hover readouts are the custom ones on the equity curve, monthly P&L and monthly distributions charts.

## 2. Definitions

### Trade

A trade is one round trip: a position in one account, symbol and currency going from flat, through open, back to flat. Lots are matched first-in first-out within that account, symbol and currency. Its id is `rt:` followed by the id of the activity that opened it. A trade always has a close date; there is no open trade.

- **Options.** Contracts are matched per contract. A multileg fill is a roll: the far leg is opened in the same trade and the whole chain, from the first short to the last buy-back or expiry, is one trade named after the last contract. Expiry closes a contract at zero. Assignment closes the option at zero, keeping the premium, and delivers the shares at the strike into the share book.
- **Crypto.** Matched like shares. Staking rewards open a lot at zero cost and carry a `reward` flag.
- **Splits.** Inferred from Wealthsimple's corporate action markers and applied to the open lots on the split date.
- **Manual and imported trades** enter the same activity table and are matched the same way.

Per-trade fields, all in the trade's currency unless stated:

| Field | Definition |
|---|---|
| Open | Earliest entry date among the trade's lots |
| Close | Latest exit date |
| Symbol | The instrument; for a rolled chain, the last contract |
| Exchange | Listing venue from the security record (TSX, TSX-V, CSE, Cboe Canada, NYSE, NASDAQ, NYSE American, NYSE Arca); `Crypto` for crypto |
| Qty | Units matched (shares, contracts or coins) |
| Entry | Quantity-weighted average entry price |
| Exit | Quantity-weighted average exit price |
| FX | Currency code, CAD or USD |
| P&L | Sum over lots of (exit − entry) × qty × multiplier for longs, reversed for shorts, minus entry and exit commissions |
| P&L % | P&L divided by the entry basis (entry × qty × multiplier) |
| Hold | Calendar days from Open to Close |
| P&L (CAD) | The same P&L with each leg's notional converted on its own fill date; equals P&L for CAD trades |
| Grade, thesis, tags | Journal entries keyed by the trade id |

### Position

An open position is the lots still held in one account, symbol, currency and direction. Its id is the round-trip id of the lot that opened it, so a note written on the position is the note of the trade it becomes.

| Field | Definition |
|---|---|
| Qty | Units held |
| Avg cost | Cost ÷ (qty × multiplier) |
| Book | Sum of lot qty × price × multiplier |
| Price | Live quote, refreshed every minute while the app runs: TMX Money or Cboe Canada for shares and ETFs, Coinbase for crypto in the position's currency, and for a US-listed option the bid/ask midpoint while both are quoted, else its last trade, else its previous close. Otherwise the last fill price in the history, and the Price cell says so |
| Market | Qty × Price × multiplier |
| P&L | Market − Book for longs, Book − Market for shorts, with the percentage over Book |
| Hold | Quantity-weighted days since each lot was opened |
| Allocation | Book ÷ total Book of all positions in scope |

### Distribution

A cashflow row is one Dividend, Interest, Withholding tax or Interest charge activity. Only Dividend rows feed the Cashflow page's totals, chart and holdings. Each row keeps its native amount and a CAD amount converted on its date.

### Distribution rate for a holding

1. Preferred: the fund's declared record from TMX Money. Per-unit amount is the latest distribution that has gone ex. Payments per year come from the gaps between its recent ex-dates.
2. Otherwise: the holding's own received payments. Per-unit amount is the latest payment's unit amount. Payments per year come from the gaps between the last payment dates.

Payments per year is the median of the last three gaps snapped to the nearest of 52, 26, 24, 12, 6, 4, 2 or 1. With fewer than two dates it is unknown; then, and only then, 12 is assumed.

Annual income for a holding = per-unit amount × payments per year × qty.

### Equity and returns

- **Equity series.** Daily net liquidation value from Wealthsimple, all accounts combined, or one account when the account filter selects exactly one.
- **Yearly return.** Daily returns net of deposits and withdrawals, chain-linked over the calendar year. A balance under 1 % of the account's all-time peak is pre-history: a year that never clears it is not shown, and a year in which the account first clears it part way through is measured from that first point, so the first real deposit is never read as a return. The S&P 500 is measured over the same span as the account's year.
- **Index.** S&P 500 from FRED daily closes (Stooq as fallback), or the S&P/TSX Composite or the S&P/TSX 60 from TMX Money's daily series (`^TSX`, `^TX60`), over the same span as the account's year.
- **Avg annualized.** Yearly returns compounded and annualized over the days they cover; years shorter than 30 days are skipped.
- **Max drawdown.** Largest peak-to-trough fall of the flow-adjusted equity index, so money moved in or out is neither a gain nor a loss. Reported as a percentage, the CAD equivalent at the peak, and the trough date.

### Market data

| Source | Data | Refresh |
|---|---|---|
| Bank of Canada Valet | USD/CAD, one rate per business day | New days are appended at start, after every sync, and on the hourly check once the table is 6 hours old; a day's rate is written once and never rewritten |
| FRED (Stooq fallback) | S&P 500 daily close | Same: new days appended, never rewritten |
| TMX Money | S&P/TSX Composite and S&P/TSX 60 daily closes, from 2016 | Same clock as the S&P 500 |
| TMX Money | Quotes for held shares and ETFs on TSX, TSX-V, CSE and US exchanges. TMX names a listing by its venue (bare for TSX and TSX-V, `:CNX` for the CSE, `:AQL` for Cboe Canada, `:US` for US exchanges); the venue in the security record picks the form, and when that form answers nothing the other forms for the record's currency are asked for a quote, the one naming a matching venue is remembered for the symbol, and the query is repeated with it. A listing whose venue is missing or one TMX does not name (an ATS such as Alpha) starts from its currency's usual form and is settled the same way. No venue is handled as a special case | Every minute while running |
| Cboe Canada (cboe.com) | Quotes for held shares and ETFs listed on Cboe Canada | Every minute while running |
| Coinbase | Spot price of each held crypto asset, in the currency the position is booked in | Every minute while running |
| Coinbase Exchange | Daily and hourly candles of crypto assets, first link of the crypto chart chain | On demand for the chart; the archive keeps them |
| Yahoo Finance | Daily and hourly bars, second link of every chart chain: shares and ETFs under the venue suffix (`.TO`, `.V`, `.CN`, `.NE`, none for US), crypto pairs in the position's currency. Bars are stamped in the exchange's own time zone, standard or daylight as the day requires. Yahoo rate-limits bursts, so it is asked one request at a time, two seconds apart, left alone for ten minutes after a refusal, never asked again that day for a symbol it does not carry, and never asked by the background sweep, only for a chart someone opens | On demand for the chart; the archive keeps them |
| Cboe (delayed chains) | Bid, ask, last trade and previous close of each held US-listed option contract | Every minute while running |
| TMX Money | Declared distribution record of every Canadian-listed dividend payer | Refetched once its stored copy is older than 20 hours; the check runs hourly and after every sync |
| Wealthsimple | Activities, balances, accounts, NAV history | Full sync once, then incremental, automatically on weekdays after 2 PM Mountain while running; the session is refreshed without a new sign-in |

Each declared record carries its own fetch stamp, separate from the quote's, so the quote loop keeping a price fresh never makes the fund's distribution history look fresh.

A USD transaction is converted at the Bank of Canada rate for its own date, looked up from that table when the model is built. The table is append-only, so a transaction's CAD value never changes once its day's rate is in. The Bank publishes a day's rate at 16:30 Eastern; the hourly check fetches it as soon as it is out, so a USD trade made during the day is converted at its own day's rate from that afternoon. Before that it uses the latest earlier rate.

### Versions and the update check

A version is a GitHub release tagged `vMAJOR.MINOR.PATCH`; commits alone are not versions. `APP_VERSION` in `bagholder.py` is bumped in the commit a release is cut from, and the running version is shown in the header as small muted text to the right of the Bagholder wordmark; nothing about versions appears in the menu. Once a day, and at start, the app asks GitHub for the latest release; when its tag is newer than the running version the header shows an "Update available" link to that release, beside the version at the top left. The request carries nothing but the app's version in its user agent; a failed check, or no release yet, is silent.

### Freshness of what is on the page

The page polls the server every 30 seconds and, whenever the data version changes, which any new activity, NAV point, FX rate, benchmark close, distribution or quote does, and which the turn of the calendar day does too, fetches the current model and redraws in place. So year tiles, YTD and anything measured to today roll over at midnight on their own, with or without new data. The browser never navigates or reloads: window and table scroll positions, the open position panel and the filter popover all stay where they were. The redraw is deferred until the next page change while a trade is open or a note is being typed, so nothing is overwritten under the user.

| Value | Feeds from | Fresh within |
|---|---|---|
| Trades, executions, journal, dashboard tiles and cards, distribution history, YTD and All time income | Wealthsimple activities and NAV, converted with BoC rates | The next sync: weekdays after 2 PM Mountain, or Sync now |
| Annualized returns vs S&P 500, drawdown | NAV from sync; S&P 500 from FRED | Sync for NAV; 6 hours for the index |
| Position Price, Market, P&L, Allocation; Cashflow Market and Current yield | Live quote | One minute for shares, ETFs, crypto and US-listed options |
| Cashflow Distribution, Projected, Yield on cost, Current yield | Declared record from TMX | 20 hours, or the next sync, whichever comes first |

Every instrument Wealthsimple offers has a live price source. TMX Money carries a Cboe Canada listing's declared record under the `:AQL` symbol form (the former NEO exchange), which the app asks for; its price still comes from Cboe's own feed, never from TMX's delayed quote.

## 3. Formatting

| Kind | Rule | Examples |
|---|---|---|
| Money | `$` and thousands separators, no currency prefix, minus as `−` | `$1,247.41`, `−$286.74` |
| Signed money | Leading `+` when zero or positive | `+$20.05` |
| Whole money | As money with no decimals | `$18,622` |
| Percent | Signed for P&L, unsigned for rates. One decimal, except two for a position's P&L % and for yields | `+0.7%`, `−13.8%`, `+3.45%`, `28.81%` |
| Quantity | Thousands separators; no decimals for whole numbers; two decimals under a whole, six when under one | `233,580`, `957.90`, `0.000123` |
| Price | Two decimals; four under $1; five under $0.01 | `49.85`, `0.3675`, `0.00123` |
| Distribution per unit | `$` with four decimals under $1, else two | `$0.2000` |
| Hold | Whole days with `d` | `207d` |
| Dates | ISO `YYYY-MM-DD` in tables; `Jun '26` on chart axes; `18 Jun '26` in chart hovers | |
| Missing | Em dash | `—` |

Positive amounts use the theme's green, negative its red, both on the P&L figure and its percentage.

## 4. Pages

All pages share the header (brand and version, sync status, filter, menu), the tab row and the current filter set. A short-lived notice from an action (session refreshed, trade added, folder scanned, or an error) takes the sync status's place for four seconds; it is red only when it reports an error. A sync error appears once: on the "No activity yet" page it is shown in full beneath the page's button and the header keeps its plain status; everywhere else it takes the header's sync status.

**Connecting.** Connect Wealthsimple opens one Chrome window on the app's own profile at Wealthsimple's sign-in page, and the header reads `Waiting for Wealthsimple login…` with a Cancel button beside it. The wait ends the moment any of these happens: the session is captured (the app then closes the window itself and syncs); the window is closed or Chrome quit, which the app notices as the absence of any window in its own Chrome, checked every 1.5 seconds, whether or not Chrome itself is still running (the header shows `The Chrome window closed before a session showed up. Choose Connect Wealthsimple to try again.`); Cancel is pressed (the app closes the window); or three minutes pass. Nothing is ever relaunched: a closed window stays closed until Connect is pressed again, and pressing Connect while the app's window is still open brings that window forward instead of opening another. The launch on Connect is the only way the app ever opens a browser window; it never asks a running Chrome to open one. Each Connect is a numbered attempt with its own watcher; the watcher looks for the window every half second and tries a capture every 1.5 seconds, keeps each DevTools call to two seconds, and the page asks the server every half second while it waits, so a closed window shows in the header within about a second; and a watcher from an earlier attempt exits without touching a later attempt's window. The server logs each of these steps to its terminal (`bagholder login: …`).

### Dashboard

Six KPI tiles in one row, all in CAD over the trades in scope:

| Tile | Value | Subtitle |
|---|---|---|
| Realized P&L | Sum of P&L (CAD) | Trade count |
| Win rate | Winning trades ÷ all trades | Wins, losses and breakevens |
| Profit factor | Gross wins ÷ gross losses; `∞` with no losses | Gross W and L |
| Expectancy | Realized P&L ÷ trade count | Average win and average loss |
| Max drawdown | Drawdown percentage | CAD fall and trough month |
| Avg annualized | Annualized return | Number of years used |

Cards:

- **Equity curve.** The equity series in scope with a `$` axis and six date labels; hover shows the value and day.
- **Annualized returns.** Title `Annualized returns` with a switch at the right, `S&P 500`, `S&P/TSX` or `TSX 60`, choosing the index the years are compared against; the choice is remembered on this machine and is not a filter. Subtitle `Vs <index>`. Every year, newest first, each with the account's return and the index's return and two equal-height bars; the list scrolls inside the card, which takes its height from the equity curve beside it and never grows past it. Footer, fixed below the list: `Outperformed <index> in N of M years.`
- **Monthly P&L.** One bar per calendar month of close date, CAD, six axis labels; hover shows the month and trade count; click opens the trade or filters to that month. The value axis labels the top, the midpoint, zero and the bottom; a label that would touch the one above it is not shown, so the bottom label goes when the losing months are small next to the winning ones.
- **Grade vs P&L.** Four bars, A B C F, CAD sum per grade with the count under each.
- **By symbol.** Symbol, P&L (CAD), Trades, Win rate, Avg hold, grouped by underlying, sorted by P&L; click opens or filters.
- **Review queue.** Closed trades missing a grade or a thesis, newest first.

### Trades

Table columns in this order: Open · Close · Symbol · Exchange · Qty · Entry · Exit · FX · P&L · P&L % · Hold · Grade · Tags. Every column sorts. FX is centred; numbers are right-aligned. Column widths are fixed proportions of the table so they do not shift with content; the table scrolls sideways only when its card is narrower than 1150 px. Long symbols truncate with an ellipsis and show in full on hover. Newest close first by default.

Trade detail: symbol, then name, exchange and listing ticker as `Name · EXCHANGE: TICKER` (the underlying's ticker for an option, listing suffixes such as .TO dropped); P&L and P&L % in the trade's currency; the trade chart; facts Open, Close, Entry, Exit, Hold, Account; an executions table with When · Side · Qty · FX · Price · Amount where Side reads `BUY` or `SELL` for shares and crypto and, for options, what the fill did in this trade (`BUY TO OPEN`, `SELL TO CLOSE`, …); a fill that closed one trade and opened the next says `(close + open)`; and the journal with thesis, grade and tags. The browser Back button returns to the list at the same scroll position.

**Trade chart.** Real bars for the trade's span, ten days either side, drawn with TradingView Lightweight Charts served from the app itself. The chart is candlesticks or nothing: every bar drawn has an open, high, low and close from its source, a line is never drawn through closes or through the executions, and a span the source has no bars for shows `No price history for this span.` in the chart's place. A timeframe switch above the chart offers whichever of 1H, 4H, 1D, 1W and 1M the instrument's source can supply, nothing else; the active one is highlighted. The default follows the trade's length: 1H up to 2 days, 4H up to 10, 1D up to 180, 1W up to about 3 years, 1M beyond, or the nearest coarser one offered; a timeframe the user picks is kept for that trade while the page is open. The chart opens framed on the trade with a margin of about 15% of its length either side, never stretched edge to edge. Weekly and monthly bars are aggregated from daily ones (Monday-start weeks, calendar months); 4H from hourly. Candlesticks when the source gives open, high, low and close; a line of closes when it gives closes only. Every execution is marked on its day at its price: an up arrow below the bar for a buy, a down arrow above for a sell, labelled with signed quantity and price. Wheel or pinch zooms the time axis, dragging pans, and the view a user set is kept while they stay on the trade. Labels appear once no more than 40 executions are in view; the arrows are always shown. A fill with no price, a staking reward, is marked on its day when bars exist. When no history source covers the instrument, the priced executions themselves are plotted on a zoomable time axis. Nothing on the chart is synthetic.

| Instrument | History source | Timeframes | Reach |
|---|---|---|---|
| Shares and ETFs on every venue Wealthsimple lists (TSX, TSX-V, CSE, Cboe Canada, US exchanges) | The chain: TMX Money under the venue's form (daily series; one-minute bars aggregated into session-aligned 1H and 4H, 9:30 start, 13:30 split), then Yahoo Finance under each venue suffix of the currency (daily; hourly bars, session-aligned) | 1H and 4H for trades within the past two years; 1D, 1W, 1M | Daily: full listing history. Hourly: one year from TMX, two from Yahoo |
| Crypto | The chain: the Coinbase Exchange market and the Yahoo pair in the position's currency, then the USD market and pair converted at the Bank of Canada rate of the bar's day (a bar whose day has no published rate is dropped, never guessed) | 1H, 4H, 1D, 1W, 1M for every trade | Full history |
| Options | The underlying stock's bars, from the sources above, with the contract's executions marked by time and labelled with contract quantity and premium; the underlying is named in the header's listing line, nothing sits beside the timeframe buttons. A second view, Contract, shows the contract's own premium: the app folds the delayed mark it fetches every minute for each held contract into 1H and 4H bars during the session, so every contract held while the app runs gets a premium chart that the archive keeps for good | Underlying: as the underlying. Contract: 1H, 4H from the day the app first held it | |

**Source chain.** No single free source covers every venue, so each instrument has an ordered list of candidate sources and symbol forms (the tables above). A fetch asks them in order and the first with bars for the span wins; a source whose intraday reach stops short of the span is skipped rather than asked for a partial answer. The winner is remembered per symbol and asked first next time; if it later has nothing for a new span, the rest of the chain is tried again. A symbol no source carries shows the chart's empty state. Nothing is hand-mapped per ticker.

Intraday bars and execution times are shown in the viewer's local time.

**Bar archive.** The sources keep bars for a limited time, so the app keeps its own. A background sweep fetches the hourly and four-hour bars of every instrument traded or held in the past year, and the daily bars of any whose source forgets them (none of the current sources does), a dozen instruments per pass with passes back to back while there is a backlog and every five minutes once there is none, and tops each one up once a day from its last stored bar. A chart request never waits on this: when the bars it wants are not stored yet it shows the daily chart and switches on its own once they are. When a fetch produces nothing for a timeframe, that timeframe is not offered for the next ten minutes and the sources are left alone; it is tried again after that. Bars once stored are never dropped, so a trade keeps its intraday chart however old it gets. The only trades without intraday bars are those already older than the source's reach when the app first saw them.

The TradingView credit the library's licence requires is the library's own small logo in the chart's bottom-left corner, nothing in the menu.

Bars are cached in the database. Closed days are written once and never rewritten; the newest day may be replaced. A span reaching the present is refetched once its copy is 20 hours old.

### Positions

Table columns: Symbol · Qty · Avg cost · Price · FX · Book · Market · P&L · Hold · Allocation, sorted by allocation. P&L reads `+$20.05 (+3.45%)`. Selecting a row opens the panel: name and exchange, unrealized P&L and percentage, Qty (with Wealthsimple's balance if it differs), Hold, Avg cost, Price, Book value, Market value, FX, Allocation, the lots with Date · Qty · Price · Amount, and the running note.

### Cashflow

Five tiles in the style of the dashboard tiles, CAD, dividends in scope:

| Tile | Value | Subtitle |
|---|---|---|
| Two years ago, last year, by calendar year, rolling over on January 1 | Sum received that year | Average per paying month |
| YTD | Sum received this year | Average per paying month |
| All time | Sum received | Average per paying month |
| Yield on cost | Annual income of all rated holdings ÷ their book cost | Received in the last twelve months, on the book cost |

**Monthly distributions.** One bar per month from the first payment to the current month (or to the end of the date filter), CAD, an empty bar for a month with nothing paid yet, six axis labels, hover shows month and amount.

**Cashflow Positions.** One row per open long position in a dividend-paying symbol, per account:

| Column | Definition |
|---|---|
| Holding | Symbol |
| Qty | Units held |
| Avg | Average cost per unit |
| Book | Book value |
| Market | Market value of that position |
| Distribution | Per-unit amount from the rate above |
| YTD | CAD received from this symbol this calendar year |
| All time | CAD received from this symbol ever |
| Ex-Div | The ex-date of the next distribution still to be paid, whether or not it has gone ex; when nothing is left to pay, of the last known one. From the fund's declared record (TSX, TSX-V, CSE and Cboe Canada listings all have one on TMX); without a record, the ex-date TMX reports on the quote. A date before today is shown muted |
| Pay Day | The pay date of that same distribution; without a record, the date of the last payment received. A date before today is shown muted; the pay day itself is not |
| Projected | Expected monthly income: annual income ÷ 12 |
| Yield on cost | Per-unit amount × payments per year ÷ average cost |
| Current yield | Per-unit amount × payments per year ÷ current price |

Avg and Market belong to the row's own position, matched by position id, never by symbol.

**Allocation and Distribution history** share one row, the Allocation card about 38% of the width on the left, the history the rest on the right, both 380px tall with their contents scrolling inside. The history table has fixed column widths (Date 14%, Symbol 11%, Type 12%, Account 22%, Qty 12%, Distribution 16%, Amount 13%) so spacing is even whatever the rows hold; the Account cell truncates with an ellipsis at its column width, so a long account name cannot push the table past its card.

**Allocation.** A donut of the income holdings in scope, each holding's share of the whole by market value or by projected monthly income, chosen with a Market / Projected switch that is remembered on this machine. Slices are ordered largest first and coloured from an eight-colour palette defined per theme: saturated on the dark themes, pastel in Light so the slices sit as softly on the page as its other colours do. The donut fills the card's height; the centre reads the total, or the hovered slice's value, symbol and share; the legend beside it is an aligned grid of symbol, value and share, vertically centred on the donut. No browser tooltips.

**Distribution history.** Date · Symbol · Type · Account · Qty · Distribution · Amount, newest first, amounts in native currency, scrolling inside its card.

## 5. Filters

One filter set applies to every page: Date (presets 1D 1W 1M 3M 6M YTD 1Y 5Y, years, or a range), Account, Symbol, Grade, Tag, Side, Kind, Exchange, Result, and ranges on Price, Hold, P&L and Qty. Trades are scoped by close date. Cashflow honours only Date, Account and Symbol and says which other filters it ignored.

## 6. Layout

- The app sits inside a rounded panel with a 24 px margin on a darker mat, in all three themes: Nocturne (default), Midnight (green accents, monospace numerals), Light. The Bagholder wordmark is identical in every theme. Tag chips, the selected grade and tag suggestions take the accent colour, except in Midnight, where the accent is the gain green: there they are neutral grey, so a tag or grade never reads as a gain or a loss.
- No table may extend past its card or clip a cell at a window 1340 px wide or wider. Below that a table may scroll sideways inside its card, never the page.
- Table headers are uppercase, one line, level with each other regardless of alignment, and a centred header sits exactly over the centre of its values.
- Scrollbars appear only while scrolling and only inside tables.
- Colours come from theme tokens only.

## 7. Verification before a UI commit

1. Every displayed figure is traced to the model field this file names for it, and the meaning matches, not just the field's existence.
2. The page is rendered against a copy of real data at 1200, 1340, 1440 and 1680 px. On every page, including a trade detail, no table overflows its container and no cell content is clipped at 1340 px and above.
3. Header boxes are measured to be at one height, and centred headers at zero offset from their column's centre.
4. Any lookup between tables uses ids, and is exercised with a synthetic duplicate symbol in a second account.
5. `python3 -m unittest test_store test_model` passes.
6. If any step fails, nothing is committed and the finding is reported first.
