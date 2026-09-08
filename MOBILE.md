# Mobile

The decision, made 2026-09-08: Bagholder stays local-first on every platform. Nothing leaves the user's device, so there is no server for the apps to lean on, and each app carries the whole model. The native apps are plain native: SwiftUI on iOS, Jetpack Compose on Android, in `ios/` and `android/` of this repository. Each has its own implementation of the model, and the three implementations are kept in agreement by `fixtures/cases`, run through every implementation's tests, so a rule changed in one and not the others fails a PR before it lands.

## What exists

- `ios-m1-shell` (PR #15, draft, issue #14): a working SwiftUI app as of 2026-09-01. Connect, a live Wealthsimple pull, Home tiles, Closed trades with executions, S&P figures. It carries its own Swift copy of the model (FIFO matching, close grouping, win rate) written against the model of that date. It is 221 commits behind master and touches `bagholder.py`, `ledger.html`, `store.py`, `test_store.py` as well as `ios/`.
- `fixtures/cases` and `test_fixtures.py`: the shared cases, four to start, generated from the Python model by `fixtures/make_fixtures.py`.

## The plan

1. **iOS first.** Rebase `ios-m1-shell` onto master, keeping the SwiftUI screens and dropping the branch's changes outside `ios/` unless they still apply. Add a Swift test that reads `fixtures/cases` and runs each through the Swift model. Bring the Swift model to the cases: options, covered calls and expiries, the Cashflow figures, Ex-Div and Pay Day. Then the screens the web app has gained since September 1: Positions, Cashflow with its tiles and Allocation donut, the trade chart, the filter search. Build and run in the Simulator each round (the Simulator can be driven from Claude Code).
2. **Android after iOS**, in `android/`, Kotlin with Jetpack Compose, the same way: its own model, the same fixture test first, then the screens. Gradle builds an APK for direct install; the AAB for the Play Store is the same project with one flag.
3. **The Wealthsimple login on a phone** has no Chrome to capture from. Each app does it in its own web view and captures the session cookies from there; the desktop's `_cdp_cookies_from_target` in `bagholder.py` shows which cookies and which fields.
4. **Add cases as rules are touched.** Every model change on any platform comes with a case in `fixtures/cases` if none covers it. The cases are the contract; `SPEC.md` is the meaning.

## Rules that carry over

Everything in `CLAUDE.md` and `SPEC.md`: only what was asked, per-instrument figures in the instrument's currency, aggregates in CAD unlabelled, payout frequency from the fund's record, raw rows never rewritten, nothing synthetic on a chart. A phone screen is a layout of the same figures, not a new definition of them.
