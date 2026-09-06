# Bagholder

A local-first trading journal for Wealthsimple users. Runs on your computer, auto-syncs trades from Wealthsimple. Activity stays on your machine.

Provides a dashboard with total realized P&L, win rate/profit factor, expectancy, biggest winners/losers, annualized performance vs S&P500, equity curve, monthly P&L with some basic sorting/filtering.

Use at your own risk. The app will have you log into the actual Wealthsimple website in order to sync. I am not responsible for your use or misuse of the app or any consequences thereof.

## Run

This installs timezone data Windows does not ship (needed for America/Edmonton).

```
python -m pip install -r requirements.txt
```

```
python3 bagholder.py
```

The webapp opens on `http://127.0.0.1:8765`.

## v2 preview

The redesigned interface is served at `http://127.0.0.1:8765/v2` while it is being tested. It reads one JSON document, `GET /api/model`, computed in Python (`model.py`) from the same SQLite store, so every tile, table and chart comes from a single list of trades. The classic page stays at `/` untouched.

What the model does:

- Matches fills FIFO per account, symbol and currency, including Wealthsimple's option rows (multileg fills with no quantity, expiries, assignments, same-day rolls) and crypto (buys, sells, transfers, staking rewards as zero-cost lots).
- Defines a trade as a round trip: the position opens from flat and closes back to flat. Partial exits are legs of the same trade, and a round trip that is still open is shown with its realized legs so far.
- Keeps per-trade numbers in the trade's own currency and converts to CAD on the fill dates wherever trades are added together (KPIs, monthly P&L, by-symbol, grades, cashflow tiles).
- Computes yearly time-weighted returns from the NAV history net of deposits, compared against the S&P 500.

Market data the model needs but Wealthsimple does not provide is stored in the same database and refreshed incrementally on start and after each sync: USD/CAD daily rates from the Bank of Canada Valet API and S&P 500 closes from FRED. The Positions tab has no live quotes; its price column is the last fill in your own history and is labelled as such.

Journal entries (grade, tags, thesis) made in v2 are saved through `POST /api/journal`, keyed by the round-trip id so they survive later exits.

Run the tests with:

```
python3 -m unittest test_store test_model
```

## Data

Login session and journal data are stored in `~/.bagholder/`. Activities, accounts, balances, equity history, FX rates, benchmark prices and the v2 journal live in `~/.bagholder/bagholder.db`.

![App demo](screenshot.png)
![Executions Sidebar](screenshot-executions.png)
![Trades](screenshot-tradelist.png)
![Filter Toggle](screenshot-filtertoggle.png)