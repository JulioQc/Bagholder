# Bagholder specification

This file is the authority on what the app shows and how each figure is computed. Any change to the page, whether it comes from a design handoff or from code, is checked against this file before it is committed. If a change needs a definition here to be different, this file changes first and the reason is recorded in the commit.

The model lives in `model.py` and is served as JSON by `GET /api/model`. The page, `ledger.html`, only renders that JSON. It performs no matching, no aggregation and no currency conversion of its own. The one exception is dividing an annual figure by twelve to show it per month.

## 1. Principles

- **Accuracy over convenience.** A number on the page is either exactly what this file defines or it is not shown. A blank is rendered as an em dash.
- **Nothing is assumed about payout frequency.** Frequency is read from the fund's declared ex-dates, or failing that from the dates of the payments actually received. It is re-read every time the model is built, so a schedule change shows after two payments at the new cadence. Monthly is assumed only when a fund has paid exactly once.
- **Currency.** Every figure that belongs to one trade, position, fill or distribution is in that instrument's own currency, with no prefix and no conversion. Every figure that adds trades or distributions together is in CAD, converted on the date of each fill or payment with the Bank of Canada rate. A currency code is shown in an FX column, never as a prefix on the amount.
- **Raw data is never rewritten.** Wealthsimple activity rows are stored once and left as received. Everything derived is recomputed from them.
- **Nothing is added that was not asked for.** No captions, tooltips, notes or helper text beyond what this file lists.

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
| Price | Live quote from TMX Money for shares and ETFs, refreshed every 15 minutes while the app runs; otherwise the last fill price in the history. The panel says which |
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
- **Yearly return.** Daily returns net of deposits and withdrawals, chain-linked over the calendar year. A year in which the account never exceeded 1 % of its all-time peak is ignored as pre-history.
- **S&P 500.** FRED daily close, same calendar span, Stooq as fallback.
- **Avg annualized.** Yearly returns compounded and annualized over the days they cover; years shorter than 30 days are skipped.
- **Max drawdown.** Largest peak-to-trough fall of the flow-adjusted equity index, so money moved in or out is neither a gain nor a loss. Reported as a percentage, the CAD equivalent at the peak, and the trough date.

### Market data

| Source | Data | Refresh |
|---|---|---|
| Bank of Canada Valet | USD/CAD daily | On sync and at start |
| FRED (Stooq fallback) | S&P 500 daily close | On sync and at start |
| TMX Money | Quotes for held shares and ETFs; declared distributions for dividend payers | Quotes every 15 minutes; distributions when stale |
| Wealthsimple | Activities, balances, accounts, NAV history | Full sync once, then incremental, automatically on weekdays after 2 PM Mountain while running; the session is refreshed without a new sign-in |

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

All pages share the header (brand, sync status, filter, menu), the tab row and the current filter set.

### Dashboard

Six KPI tiles in one row, all in CAD over the trades in scope:

| Tile | Value | Subtitle |
|---|---|---|
| Realized P&L | Sum of P&L (CAD) | Trade count and `CAD` |
| Win rate | Winning trades ÷ all trades | Wins, losses and breakevens |
| Profit factor | Gross wins ÷ gross losses; `∞` with no losses | Gross W and L |
| Expectancy | Realized P&L ÷ trade count | Average win and average loss |
| Max drawdown | Drawdown percentage | CAD fall and trough month |
| Avg annualized | Annualized return | Number of years used |

Cards:

- **Equity curve.** The equity series in scope with a `$` axis and six date labels; hover shows the value and day.
- **Annualized returns.** Title `Annualized returns`, subtitle `Vs S&P 500`. Up to four most recent years, newest first, each with the account's return and the index's return and two equal-height bars. Footer: `Outperformed S&P 500 in N of M years.`
- **Monthly P&L.** One bar per calendar month of close date, CAD, six axis labels; hover shows the month and trade count; click opens the trade or filters to that month.
- **Grade vs P&L.** Four bars, A B C F, CAD sum per grade with the count under each.
- **By symbol.** Symbol, P&L (CAD), Trades, Win rate, Avg hold, grouped by underlying, sorted by P&L; click opens or filters.
- **Review queue.** Closed trades missing a grade or a thesis, newest first.

### Trades

Table columns in this order: Open · Close · Symbol · Exchange · Qty · Entry · Exit · FX · P&L · P&L % · Hold · Grade · Tags. Every column sorts. FX is centred; numbers are right-aligned. Column widths are fixed proportions of the table so they do not shift with content; the table scrolls sideways only when its card is narrower than 1150 px. Long symbols truncate with an ellipsis and show in full on hover. Newest close first by default.

Trade detail: symbol, name and exchange; P&L and P&L % in the trade's currency; a price path through the fills with buy and sell markers; facts Open, Close, Entry, Exit, Qty, Hold, Account; an executions table with When · Side · Qty · FX · Price · Amount where Side says what the fill did in this trade (`BUY TO OPEN`, `SELL TO CLOSE`, …); and the journal with thesis, grade and tags. The browser Back button returns to the list at the same scroll position.

### Positions

Table columns: Symbol · Qty · Avg cost · Price · FX · Book · Market · P&L · Hold · Allocation, sorted by allocation. P&L reads `+$20.05 (+3.45%)`. Selecting a row opens the panel: name and exchange, unrealized P&L and percentage, Qty (with Wealthsimple's balance if it differs), Hold, Avg cost, Price, Book value, Market value, FX, Allocation, the lots with Date · Qty · Price · Amount, and the running note.

### Cashflow

Five tiles in the style of the dashboard tiles, CAD, dividends in scope:

| Tile | Value | Subtitle |
|---|---|---|
| Two years ago, last year | Sum received that year | Average per paying month |
| YTD | Sum received this year | Average per paying month |
| All time | Sum received | Average per paying month |
| Yield on cost | Annual income of all rated holdings ÷ their book cost | Received in the last twelve months, on the book cost |

**Monthly distributions.** One bar per month from the first payment to the last, CAD, six axis labels, hover shows month and amount.

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
| Projected | Expected monthly income: annual income ÷ 12 |
| Yield on cost | Per-unit amount × payments per year ÷ average cost |
| Current yield | Per-unit amount × payments per year ÷ current price |

Avg and Market belong to the row's own position, matched by position id, never by symbol.

**Distribution history.** Date · Symbol · Type · Account · Qty · Distribution · Amount, newest first, amounts in native currency.

## 5. Filters

One filter set applies to every page: Date (presets 1D 1W 1M 3M 6M YTD 1Y 5Y, years, or a range), Account, Symbol, Grade, Tag, Side, Kind, Exchange, Result, and ranges on Price, Hold, P&L and Qty. Trades are scoped by close date. Cashflow honours only Date, Account and Symbol and says which other filters it ignored.

## 6. Layout

- The app sits inside a rounded panel with a 24 px margin on a darker mat, in all three themes: Nocturne (default), Midnight (green accents, monospace numerals), Light.
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
