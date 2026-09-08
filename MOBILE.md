# Mobile

The decision, made 2026-09-08: Bagholder stays local-first on every platform. Nothing leaves the user's device, so there is no server for the apps to lean on, and each app carries the whole model. The native apps are plain native: SwiftUI on iOS, Jetpack Compose on Android, in `ios/` and `android/` of this repository. Each has its own implementation of the model, and the three implementations are kept in agreement by `fixtures/cases`, run through every implementation's tests, so a rule changed in one and not the others fails a PR before it lands.

## What exists

Branch `ios`, PR #63, 2026-09-08:

- **The model, three times.** `model.py` is the reference. `ios/Bagholder/Model.swift` + `ModelView.swift` and `android/model` (Kotlin) are ports of it function for function: normalization, assignment shares, FIFO with option rolls, assumed expiries, FX, round trips, positions, cashflow, KPIs, filters, the equity series and yearly returns against an index, annualized return, drawdown, the dashboard cards, the journal, the Cashflow page. `fixtures/cases` (23 cases from `fixtures/make_fixtures.py`) run through all three (`test_fixtures.py`, `ios/BagholderTests/ModelCasesTests.swift`, `android/model/src/test/.../ModelCasesTest.kt`) and compare the whole view.
- **The iOS app** (`ios/`, SwiftUI, Xcode 26, iPhone 17 simulator): `App.swift`, `Screens.swift` (Dashboard, Trades and the trade detail, Positions and the position detail, Cashflow, the filter sheet, the menu), `Theme.swift` (the page's Nocturne and Light tokens, the spec's formatting), `Charts.swift`, `AppState.swift` (`Book`: the keychain session, the last pull, the journal, the filter set, the pull, the market loop), `Market.swift` (quotes from TMX Money, Cboe Canada, Coinbase and Cboe's delayed option marks; the declared distribution records; the S&P/TSX and TSX 60 closes; daily bars from the TMX and Yahoo chain, weekly and monthly aggregated), `WSPull.swift` (the Wealthsimple pull from the spike, NAV history included).
- **The Android app** (`android/`, Jetpack Compose, compileSdk 34): `MainActivity.kt` (the same screens), `Theme.kt`, `Charts.kt`, `Journal.kt` (`Book`), `Store.kt`, `Market.kt`, `WSPull.kt` (with NAV history and the S&P from FRED), `Queries.kt` (generated from the Swift file). Build: `cd android && ./gradlew :app:assembleDebug` (JDK 17+, `ANDROID_HOME`).
- **Verified** headless: the iOS simulator (`xcrun simctl`, the app container seeded from the fixture cases, `simctl io screenshot`) and the Android emulator (`emulator -avd Medium_Phone_API_35 -no-window`, `adb shell run-as com.bagholder.app` to seed `files/bagholder/`). Every figure on every screen matched the Python model on the same rows, on both platforms, and real bars came through for LUNR. Neither app has run a real Wealthsimple pull yet.

Not there yet: intraday timeframes (1H, 4H) on the trade chart, the Midnight theme, hover details on the charts, Wealthsimple's balance beside a position's quantity (the phone pull does not fetch balances), the equity curve's account switch beyond the account filter.

## The plan

1. **iOS.** Done: the model, the four pages, the details, filters, menu, market data. Next, once the user has tested a real pull: intraday bars, then whatever the test turns up. The old list, for reference: Positions, Cashflow with its tiles and Allocation donut, the trade chart, the filter search. Build and run in the Simulator each round (the Simulator can be driven from Claude Code). One rule: a Swift model change comes with the case that proves it, on both sides.
2. **Android.** Done: the same as iOS. Next: a real pull to confirm the login capture and the sync end to end, then intraday bars alongside iOS. Gradle builds an APK for direct install; the AAB for the Play Store is the same project with one flag.
3. **The Wealthsimple login on a phone** has no Chrome to capture from. Each app does it in its own web view and captures the session cookies from there; the desktop's `_cdp_cookies_from_target` in `bagholder.py` shows which cookies and which fields.
4. **Add cases as rules are touched.** Every model change on any platform comes with a case in `fixtures/cases` if none covers it. The cases are the contract; `SPEC.md` is the meaning.

## Rules that carry over

Everything in `CLAUDE.md` and `SPEC.md`: only what was asked, per-instrument figures in the instrument's currency, aggregates in CAD unlabelled, payout frequency from the fund's record, raw rows never rewritten, nothing synthetic on a chart. A phone screen is a layout of the same figures, not a new definition of them.
