# Bagholder specification

This file is the authority on what the app shows and how each figure is computed, on every platform. Any change to a screen, whether it comes from a design handoff or from code, is checked against this file before it is committed. If a change needs a definition here to be different, this file changes first and the reason is recorded in the commit.

The model is defined by `model.py`, the reference implementation; the iOS and Android apps carry their own implementations of it (`ios/Bagholder/Model.swift` + `ModelView.swift`, `android/model`), and the shared cases in `tests/cases` hold all three to the same answers. On the desktop the model is served as JSON by `GET /api/model` and the page, `ledger.html`, only renders that JSON: no matching, no aggregation and no currency conversion of its own, the one exception being dividing an annual figure by twelve to show it per month. On a phone the same figures are computed on the device from the same rows. Sections 2 and 3 define the figures for every platform; sections 4 to 7 describe the web page; section 8 describes the phone.

## 1. Principles

- **Accuracy over convenience.** A number on the page is either exactly what this file defines or it is not shown. A blank is rendered as an em dash.
- **Payout frequency is verified from the fund's own record, every day.** Each dividend payer's declared distribution history is fetched from TMX Money, the public record the fund itself publishes, and refetched whenever the stored copy is more than 20 hours old, on start and on every sync. Frequency is computed from the gaps between the most recent ex-dates in that record, not from any stored setting, so it is correct from the first holding day even with no payment history, and a schedule change is picked up after two payments at the new cadence. Only when a fund has no declared record does the holding's own received payments stand in, and only a fund that has paid exactly once is treated as monthly until its second payment.
- **Currency.** Every figure that belongs to one trade, position, fill or distribution is in that instrument's own currency, with no prefix and no conversion. Every figure that adds trades or distributions together is in CAD, converted on the date of each fill or payment with the Bank of Canada rate. The app is for Wealthsimple users, so CAD is the home currency and is never labelled: a currency code appears only in the FX column of a per-instrument row, never on a tile, a total, or as a prefix on an amount.
- **Raw data is never rewritten by Bagholder.** Wealthsimple activity rows are stored as received and never edited here. When Wealthsimple revises a row of its own (a dividend it files as a zero-cash placeholder on the record date becomes the paid dividend on pay day, under the same id), the stored copy is replaced by Wealthsimple's current version, keeping its id and so its journal. Everything derived is recomputed from the rows.
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
| Yahoo Finance | Daily and hourly bars, second link of every chart chain: shares and ETFs under the venue suffix (`.TO`, `.V`, `.CN`, `.NE`, none for US), crypto pairs in the position's currency. Bars are stamped in the exchange's own time zone, standard or daylight as the day requires. Yahoo refuses the app's usual request headers, so it is asked with a plain browser signature of its own; it rate-limits bursts, so it is asked one request at a time, two seconds apart, left alone for ten minutes after a refusal, never asked again that day for a symbol it does not carry, and never asked by the background sweep, only for a chart someone opens | On demand for the chart; the archive keeps them |
| Cboe (delayed chains) | Bid, ask, last trade and previous close of each held US-listed option contract | Every minute while running |
| TMX Money | Declared distribution record of every Canadian-listed dividend payer | Refetched once its stored copy is older than 20 hours; the check runs hourly and after every sync |
| Wealthsimple | Activities, balances, accounts, NAV history | Full sync once, then incremental from fourteen days before the newest stored row (Wealthsimple files a row under the day it belongs to, which can be earlier than rows already stored), automatically on weekdays after 2 PM Mountain while running; the session is refreshed without a new sign-in |
| Wealthsimple | Per account: net liquidation value, cash balances, buying power (`marginV3.trading.buyingPower`, the figure its margin page labels Margin available, or the reason it is unavailable) | At every sync, and every five minutes while running and connected |

Each declared record carries its own fetch stamp, separate from the quote's, so the quote loop keeping a price fresh never makes the fund's distribution history look fresh.

**Source outcomes.** Every request to a source records its outcome, and that is what the chart's empty state reports (see the trade chart). Nothing about sources appears in the menu. A symbol a source does not carry is not a failure of the source.

A USD transaction is converted at the Bank of Canada rate for its own date, looked up from that table when the model is built. The table is append-only, so a transaction's CAD value never changes once its day's rate is in. The Bank publishes a day's rate at 16:30 Eastern; the hourly check fetches it as soon as it is out, so a USD trade made during the day is converted at its own day's rate from that afternoon. Before that it uses the latest earlier rate.

### Versions and the update check

A version is a GitHub release tagged `vMAJOR.MINOR.PATCH`; commits alone are not versions, and the desktop and the phone apps carry one number (how a release is cut is in `CLAUDE.md`). The running version is shown in the header as small muted text to the right of the Bagholder wordmark; on the web nothing about versions appears in the menu. At every start, and every hour while running, the app asks GitHub for the latest release; when its tag is newer than the running version the header shows, beside the version at the top left, an "Update to vX.Y.Z" button when the app can install it itself, else an "Update available" link to that release.

**Updating from the page.** `python3 bagholder.py` runs a small supervisor whose only job is to run the server as a child in the same console and start it again when it exits asking to be restarted. Pressing the update button: a git checkout on a clean master does `git pull --ff-only`; any other copy downloads the release's web archive (`bagholder-vX.Y.Z-web.zip`) and its `.sha256` from GitHub, checks the checksum, compiles every Python file in it, keeps the current files under the home folder's `previous`, and puts the new ones in place. The header reads `Downloading…`, `Installing…`, `Restarting…`; the server then stops, the supervisor starts the new one on the same port, and the page reloads itself when it sees a new version answering. If the new server dies within twenty seconds the supervisor puts the previous files back and starts that version again, and the header says the update failed. The button refuses while a sync is running, and a git checkout with local changes or on another branch is asked to pull by hand. Only a press of the button starts any of this. A release carries the archive and checksum as assets, so the process needs nothing but the GitHub release. The request carries nothing but the app's version in its user agent; a failed check, or no release yet, is silent.

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

All pages share the header (brand and version, sync status, filter, menu), the tab row and the current filter set. With nothing open and nothing being typed, the Left and Right arrow keys move between the tabs in their order, Dashboard to Cashflow, stopping at the ends. A short-lived notice from an action (session refreshed, trade added, folder scanned, or an error) takes the sync status's place for four seconds; it is red only when it reports an error. A sync error appears once: on the "No activity yet" page it is shown in full beneath the page's button and the header keeps its plain status; everywhere else it takes the header's sync status.

**The menu.** Two of its items remove things, and they do not overlap. `Clear data` deletes every stored row from this machine: the activities, accounts, balances and NAV history synced from Wealthsimple, imported and added trades, the journal, and the downloaded market data (FX, benchmark, distributions, quotes, price history and bars); it keeps the Wealthsimple login, so the next `Sync now` pulls the history again without signing in. `Disconnect` deletes the Wealthsimple login and nothing else; the stored rows stay. It is always in the menu: live whenever a login is saved, connected or not (a login whose refresh Wealthsimple refused is still one to delete), and greyed when there is none. Each asks once before acting.

**The page with nothing to show.** No image (the mark already sits in the header). Not connected: `No activity yet`, a line inviting the user to connect, and a Connect Wealthsimple button. Connected and syncing: `Pulling your history`, a line saying the first sync can take a minute, and no button (the header shows the sync step). Connected with nothing back: `No activity yet`, a line saying nothing has come back yet, and a Sync now button. A sync error, when there is one, sits beneath in full.

**Connecting.** Connect Wealthsimple opens one Chrome window on the app's own profile at Wealthsimple's sign-in page, and the header reads `Waiting for Wealthsimple login…` with a Cancel button beside it. The wait ends the moment any of these happens: the session is captured and made the app's own (the app refreshes the captured token at once, so the login on disk is one Wealthsimple has issued to the app, not a copy of the browser's; only then does it close the window itself and sync; a capture whose refresh Wealthsimple refuses is not a connection, and the watcher keeps looking while the window is up); the window is closed or Chrome quit, which the app notices as the absence of any window in its own Chrome, checked every 1.5 seconds, whether or not Chrome itself is still running (the header shows `The Chrome window closed before a session showed up. Choose Connect Wealthsimple to try again.`); Cancel is pressed (the app closes the window); or three minutes pass. Nothing is ever relaunched: a closed window stays closed until Connect is pressed again, and pressing Connect while the app's window is still open brings that window forward instead of opening another. The launch on Connect is the only way the app ever opens a browser window; it never asks a running Chrome to open one. Each Connect is a numbered attempt with its own watcher; the watcher looks for the window every half second with a half-second timeout, a separate thread tries a capture every 1.5 seconds so a capture call stuck on a window that just closed never delays the watcher, and the page asks the server every half second while it waits, so a closed window shows in the header within about a second; and a watcher from an earlier attempt exits without touching a later attempt's window. The server logs each of these steps to its terminal (`bagholder login: …`).

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

**Trade chart.** Real bars for the trade's span, ten days either side, drawn with TradingView Lightweight Charts served from the app itself. The chart is candlesticks or nothing: every bar drawn has an open, high, low and close from its source, and a line is never drawn through closes or through the executions. When there are no bars the chart's place says why, from what the sources actually answered: a source that failed is named with its failure (`TMX Money could not be reached.`, `Yahoo Finance refused the request (too many).`), otherwise `No bars for this span from TMX Money or Yahoo Finance.` naming the sources that were asked. Nobody has to look at a terminal. A timeframe switch above the chart offers whichever of 1H, 4H, 1D, 1W and 1M the instrument's source can supply, nothing else; the active one is highlighted. The default follows the trade's length: 1H up to 2 days, 4H up to 10, 1D up to 180, 1W up to about 3 years, 1M beyond, or the nearest coarser one offered; a timeframe the user picks is kept for that trade while the page is open. The chart opens framed on the trade with a margin of about 15% of its length either side, never stretched edge to edge. Weekly and monthly bars are aggregated from daily ones (Monday-start weeks, calendar months); 4H from hourly. Candlesticks when the source gives open, high, low and close; a line of closes when it gives closes only. Every execution is marked on its day at its price: an up arrow below the bar for a buy, a down arrow above for a sell, labelled with signed quantity and price. Wheel or pinch zooms the time axis, dragging pans, and the view a user set is kept while they stay on the trade. Labels appear once no more than 40 executions are in view; the arrows are always shown. A fill with no price, a staking reward, is marked on its day when bars exist. When no history source covers the instrument, the priced executions themselves are plotted on a zoomable time axis. Nothing on the chart is synthetic.

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

### Portfolio

Six tiles in the style of the dashboard tiles, CAD aggregates over the accounts in scope (every account when the filter names none):

| Tile | Value | Subtitle |
|---|---|---|
| Market value | Market value of the open positions in scope, converted at today's rate | `across N open positions` |
| Net asset value | Sum of Wealthsimple's net liquidation value per account, as Wealthsimple states it; every open account counts, cash accounts included, so it differs from Market value by the cash; closed accounts never count | `N accounts, N positions`, or `—` when no account in scope reports one |
| Cost basis | Book value of the open positions in scope | `Total book value` |
| Margin used | The negative cash balances of the accounts in scope, one per currency, shown positive, converted to CAD | Its share of Market value |
| Available margin | Sum of Wealthsimple's buying power over the open margin accounts in scope, the figure Wealthsimple labels Margin available. Only margin accounts are asked: every self-directed account answers the same query with the cash it could buy with, which is not margin | `buying power`; `unavailable for <account>` when Wealthsimple cannot price a security in it; `—` with no margin account in scope |
| Unrealized P&L | Unrealized P&L of the open positions in scope, converted at today's rate | Its percentage of Cost basis, `gain` or `loss` |

Nothing on the tab is derived beyond these sums: Max buying power, Portfolio value and the interest panel of Wealthsimple's margin page have no source and are not shown.

**Allocation.** A donut of the open positions in scope by market value in CAD, one slice each up to ten, otherwise the ten largest and `Other (N)`, coloured from the eleven-colour palette; the centre reads `Market value` and the total, or the hovered slice's value and share; the legend is each slice's symbol and share. The card takes the height of the Holdings card beside it and does not grow. No toggle.

**Holdings.** One row per open position: Symbol (`SHORT` on a short; the account is the row's title text, not shown) · Avg (average cost per unit) · Last (the current price) · Book · Market · Change ($) · Change (%) · Unrealized P&L (`+$20.05 (+3.4%)`), sorted by Unrealized P&L; the two Change columns are the day's move on the position from its quote's change and percent change, `—` without a quote. Avg, Last, Book, Market and the changes are in the position's currency. The table shows ten rows and scrolls inside the card past that.

**A holding.** Clicking a row opens the holding on the page a trade opens (§Trades), the position standing in for the trade: the symbol, name and listing; the unrealized P&L and its percentage at the top right; the chart with the fills so far; Open, Close (blank, since it is open), Entry (average cost), Exit (the current price), Hold (the days so far), Account; the executions; the thesis, grade and tags. The holding and the trade it becomes when it closes share one journal entry, keyed by the round trip that opened it, so what is written here is the trade's journal on that day.

**Refresh.** Net liquidation values, cash balances and buying power are read at every sync and again every five minutes while the app runs and is connected, so the tiles move with the day instead of waiting for the daily sync.

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

One filter set applies to every page: Date (presets 1D 1W 1M 3M 6M YTD 1Y 5Y, years, or a range), Account, Symbol, Grade, Tag, Side, Kind, Exchange, Result, and ranges on Price, Hold, P&L and Qty. Trades are scoped by close date. Cashflow honours only Date, Account and Symbol and says which other filters it ignored. The filter popover opens on a search box above the field list. Typing lists every value from the list fields that contains the text (symbols first, then account, grade, tag, side, kind, exchange, result, each row naming its field), the first match highlighted; the keyboard stays in the box throughout, as in any command palette: the arrows move the highlight, which starts on the first match, Enter toggles the highlighted value on or off, Backspace edits the text (or, with the box empty, deselects the highlighted value), Tab goes straight to Done, then Clear all, then back to the box, and Shift+Tab runs that ring backwards, so Enter on either button finishes without the mouse; a click on a row toggles it too; the text and the list stay so several values can be picked in a row, a picked value marked by a short bar along the row's left edge in the chip colour of the theme (the accent, or neutral in Midnight where the accent is the gain green) on top of the row's shading, drawn inside the row so no text moves, and the box keeps focus throughout. When no value matches, the text is the free-text Search filter, applied as before. ⌘K on a Mac, Ctrl+K elsewhere, opens the popover with that box focused, from anywhere on the page; Escape closes it. With nothing open and nothing being typed, Escape clears every filter, the same as Clear all. Inside a single list filter the same keys drive its own value list.

## 6. Layout

- The app sits inside a rounded panel with a 24 px margin on a darker mat, in all three themes: Nocturne (default), Midnight (green accents, monospace numerals), Light. The theme is chosen from the menu: a `Theme` row naming the current theme, with a chevron, opens beside it, on hover or on a tap, a list of the three, each with a round swatch of its background and the current one in the accent colour with a check; choosing one closes the list. The Bagholder wordmark is identical in every theme. Tag chips, the selected grade and tag suggestions take the accent colour, except in Midnight, where the accent is the gain green: there they are neutral grey, so a tag or grade never reads as a gain or a loss.
- No table may extend past its card or clip a cell at a window 1340 px wide or wider. Below that a table may scroll sideways inside its card, never the page.
- Table headers are uppercase, one line, level with each other regardless of alignment, and a centred header sits exactly over the centre of its values.
- Scrollbars appear only while scrolling and only inside tables.
- Colours come from theme tokens only.

## 7. Verification before a web-page commit

1. Every displayed figure is traced to the model field this file names for it, and the meaning matches, not just the field's existence.
2. The page is rendered against a copy of real data at 1200, 1340, 1440 and 1680 px. On every page, including a trade detail, no table overflows its container and no cell content is clipped at 1340 px and above.
3. Header boxes are measured to be at one height, and centred headers at zero offset from their column's centre.
4. Any lookup between tables uses ids, and is exercised with a synthetic duplicate symbol in a second account.
5. `python3 -m unittest discover tests` passes.
6. If any step fails, nothing is committed and the finding is reported first.

For the phone apps the equivalent is in `CLAUDE.md` ("How changes land", step 6) and `MOBILE.md`: both platforms in the same PR, every screen captured on both from the same seeded rows and compared.

## 8. The phone

The iOS and Android apps show the same figures as the web page, computed on the device by their own model implementations; §2 and §3 apply unchanged. A phone screen is a layout of those figures, not a new definition of them, and both apps lay them out the same way. Where the phone departs from §4 to §6 it is listed here; anything not listed is as on the web.

**Shell.** A header with the mark, the wordmark, the version, the sync status, a funnel button for the filters and a three-line button for the menu; four tabs along the bottom (Dashboard, Trades, Portfolio, Cashflow), each with its symbol over its label and a 2 pt accent line over the current one. A trade or holding detail sits over its tab with the tab bar still below it and a round back button. The menu is a sheet: Connect Wealthsimple or Sync now and Disconnect, then the activity count and the version. The filters are a sheet whose search field takes focus as it opens.

**Cards.** 12 pt above and below the content, 16 pt at the sides, a 24 pt header row with a 15 pt semibold title at its top; a control at the right of the header (the index toggle, a sort menu, a figure) sits in that row. Nothing under a title: no captions, subtitles or helper lines, no "All accounts", no "Vs S&P 500" (the toggle itself reads `Vs S&P 500`), no "CAD", no "Outperformed … in N of M years", no "Dividend" beside a history row.

**Tiles.** Two per page in a row that swipes sideways, with the indicator below: 4 pt dots at 24 % ink, a 14 × 4 accent pill for the current page. Dashboard: Realized P&L, Win rate; Profit factor, Expectancy; Max drawdown, Avg annualized. Portfolio: Market value, Net asset value; Cost basis, Margin used; Available margin, Unrealized P&L. Cashflow: the year to date, Yield on cost; All time, then the past years, newest first.

**Charts.** No value axis. The card's figure sits at its top right: Equity shows the latest point, P&L the sum in scope, Distributions the projected month. The Equity line runs edge to edge, scaled from its low to its high, 160 pt tall, four date labels below. A long press reads the point under the finger from the first touch: the figure at the top right becomes that day's or month's, the date or month appears at the bottom under the finger, the rest of the chart dims (the equity line and its fill keep their colour up to the finger, the marker is a ring), and the page and any pager hold still until release. Bars fill their month's slot 4 pt apart on the web page's scale (§4); a tap on a P&L bar opens the month.

**Dashboard.** Tiles; Equity; then one swiping row of three equal cards, Annual returns (the years scrolling inside the card, three visible, no footer), P&L (the monthly bars, titled `P&L`) and Grade vs P&L; By symbol, whose header is a sort menu (P&L, Trades, Win rate, Avg hold; the current column again flips the order); Review queue.

**Portfolio.** Tiles; Allocation (the donut, one slice each up to ten holdings and otherwise the ten largest and `Other (N)`, with the symbols and their shares beside it); Holdings, each row the symbol (`SHORT` on a short) with `account · Book · Market` under it on the left, the unrealized P&L over its percentage on the right, then `Today` with the day's change and percent, or `—` without a quote; sorted by unrealized P&L. A tap opens the holding on the screen a trade opens, titled `Holding`: the chart with the fills, Open, Close (blank), Entry, Exit, Qty, Hold, Account, the executions and the journal.

**Cashflow.** Tiles; Distributions (the monthly bars in the accent colour); Allocation with its Market/Projected toggle; Positions, each row the symbol with `shares · avg · dist × freq` under it on the left, the month's payout over the yield on cost on the right, then Ex-Div and Pay Day; History, each row the symbol, `date · qty × per`, the amount and its currency, without the payment kind.

**Connecting.** Connect opens Wealthsimple's sign-in page in the app's own web view, kept loaded ahead of the tap, and captures the session from its cookies once signed in; sign in with email, password and the two-factor code. A passkey does not work inside an app's web view on either platform: iOS refuses the request unless the app is a browser or the site lists the app, and Android's web view hides the button; that is the platforms' rule, not a fault to fix.

**Verification.** Both platforms in the same PR; every screen and state captured on the iOS simulator and the Android emulator from the same seeded rows and compared side by side; speed judged on a phone launched from the home screen.
