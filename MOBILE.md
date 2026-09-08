# Mobile

The decision, made 2026-09-08: Bagholder stays local-first on every platform. Nothing leaves the user's device, so there is no server for the apps to lean on, and each app carries the whole model. The native apps are plain native: SwiftUI on iOS, Jetpack Compose on Android, in `ios/` and `android/` of this repository. Each has its own implementation of the model, and the three implementations are kept in agreement by `fixtures/cases`, run through every implementation's tests, so a rule changed in one and not the others fails a PR before it lands.

## What exists

- Branch `ios`: the `ios/` folder of `ios-m1-shell` (PR #15, the working SwiftUI app as of 2026-09-01: Connect, a live Wealthsimple pull, Home tiles, Closed trades with executions) placed on today's master. The branch's changes outside `ios/` were web-side and are superseded, so they were dropped. It builds on Xcode 26 for the iPhone 17 simulator.
- `ios/BagholderTests/ModelCasesTests.swift`: the Swift side of the shared cases. It reads `fixtures/cases`, runs each through `WSPull.matchFifo` and `WSPull.computeMetrics`, and compares. On 2026-09-08 the Swift model agreed with the Python on every trade field of all four cases (symbol, side, dates, quantity, entry, exit, P&L with the option multiplier, hold days) and on the trade counts. Run it with `cd ios && xcodebuild test -project Bagholder.xcodeproj -scheme Bagholder -destination 'platform=iOS Simulator,name=iPhone 17' -only-testing:SpikeLoopback/ModelCasesTests` (the test target is named `SpikeLoopback`).
- `fixtures/cases` and `test_fixtures.py`: the shared cases, four to start, generated from the Python model by `fixtures/make_fixtures.py`. The Swift model keeps open lots where the Python keeps one position per symbol and account; the Swift test compares open symbols for now. Cashflow figures, Ex-Div and Pay Day have no Swift implementation yet, so the cashflow case checks its trades only on the Swift side.

## The plan

1. **iOS first.** Done so far: branch `ios` with the app on master and the Swift fixture test passing on the trade fields. Next: add cases for the rules the Swift model has not met yet (covered-call rolls, expiries and assignment, crypto with staking rewards, the Cashflow figures, Ex-Div and Pay Day), implement them in Swift until the cases pass, then the screens the web app has gained since 1 September: Positions, Cashflow with its tiles and Allocation donut, the trade chart, the filter search. Build and run in the Simulator each round (the Simulator can be driven from Claude Code). One rule: a Swift model change comes with the case that proves it, on both sides.
2. **Android after iOS**, in `android/`, Kotlin with Jetpack Compose, the same way: its own model, the same fixture test first, then the screens. Gradle builds an APK for direct install; the AAB for the Play Store is the same project with one flag.
3. **The Wealthsimple login on a phone** has no Chrome to capture from. Each app does it in its own web view and captures the session cookies from there; the desktop's `_cdp_cookies_from_target` in `bagholder.py` shows which cookies and which fields.
4. **Add cases as rules are touched.** Every model change on any platform comes with a case in `fixtures/cases` if none covers it. The cases are the contract; `SPEC.md` is the meaning.

## Rules that carry over

Everything in `CLAUDE.md` and `SPEC.md`: only what was asked, per-instrument figures in the instrument's currency, aggregates in CAD unlabelled, payout frequency from the fund's record, raw rows never rewritten, nothing synthetic on a chart. A phone screen is a layout of the same figures, not a new definition of them.
