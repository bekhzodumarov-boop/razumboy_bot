# Dashboard, attribution and attendance release

Based on production e276b59f, preserving its count-only payment flow.

## Features

- `/report ID all`: all available funnel history, current bookings; `/report` keeps the daily window.
- `python dashboard/run_bridge.py`: one bot subprocess and an authenticated read-only HTTP snapshot in the same container and volume. `/health` has no business data; `/snapshot` requires a 32+ character bearer secret. All SQL export operations use mode=ro and query_only. Cache: 30 seconds. No contacts, private Telegram IDs, captain names, comments, audit actors or raw attempt rows leave the bridge.
- Snapshot contains bookings, manually entered attendance, all payment methods, expenses, distributions and source aggregates. Unknown attendance and missing analytics remain null. Distributions never reduce the operating result; they reduce the remaining balance.
- Team source labels require the same Telegram account, game and exactly one completion within five minutes of booking creation. No match means unknown, not organic or zero. A link label is not proof of ad acquisition.
- Attendance game page → **Внести список оплат** accepts `Отчаянные 5 - 280П+70Н` with multiple teams. Count after name is actual attendance, amounts are thousands of UZS. У=Uzum, П=Payme, К=Click, Н=cash, `переводом`=card. Preview shows full matched team names and all methods. Missing methods become zero for listed teams only. One confirmation saves the whole list atomically; revisions and price are checked again, stale or duplicate confirmation cannot add receipts twice.
- Unlabeled amounts, non-divisible prices/discount ambiguity, duplicate or ambiguous names and payments exceeding attendance block the complete list. No fuzzy name guessing. Supported short names are explicitly listed in finance_bulk.py; exact names always work when unique.

## Verification

122 offline Python tests pass, including actual aiogram routing, cancellation, invalid text revoking an old preview, atomic rollback, source matching and read-only export. No real Telegram messages or production payment writes were used for testing.

## Release state and settings

Source branch: codex/complete-intelligence. Test Railway changes are staged, not deployed: its deployment confirmation was declined. Existing production remains pinned to e276b59f.

Staging keeps its separate DB, @Razumboy_Test_Bot and disabled scheduler. Start bridge with DASHBOARD_BOT_ENTRY=finance_preview.py, PORT=8080 and its own DASHBOARD_BRIDGE_TOKEN. Production entry defaults to app.py. Do not copy preview data or credentials into production.

Before production: fresh external SQLite backups, run staging end-to-end, preserve original volume and single worker, inspect all staged changes. Configure the private Site BOT_BRIDGE_URL and BOT_BRIDGE_TOKEN to the production bridge over HTTPS; keep the token only in runtime secrets. Never deploy the old PR9 base over current code.

Historical missing source labels cannot be reconstructed. Reported attendance and receipts for prior games must be checked by the organizer before entry. Ads are read-only; no budgets, creatives or links are changed by this release.
