# Dashboard, attribution and attendance release

## October 26 fixes

Finance authorization is scoped to `af:` callbacks, so subscriber giveaway buttons are never intercepted by admin-only finance checks. Closed giveaways still reject participation.

The admin booking and restaurant lists now use current `team_size`; an older conflicting reminder response is labeled separately. Future size edits update existing positive confirmations in the same transaction, and a new positive confirmation updates the current booking. Declines and manual attendance/payment ledgers stay separate. No historical attendance or payment reconciliation is performed.

Production launcher makes integrity-checked SQLite Backup API copies before opening the bot and serves their ZIP only through a separate `RELEASE_BACKUP_TOKEN` at `/ops/release-backup`. The dashboard's `BOT_BRIDGE_TOKEN` cannot fetch backups. Backups must be downloaded and SHA256 checked outside Railway during release verification; do not publish or commit them. Staging supports `RELEASE_SMOKE_TEST=1` to create only a fresh synthetic game and check the complete payment/save/export path, including duplicate confirmation.

Based on production e276b59f, preserving its count-only payment flow.

## Features

- `/report ID all`: all available funnel history, current bookings; `/report` keeps the daily window.
- `python dashboard/run_bridge.py`: one bot subprocess and an authenticated read-only HTTP snapshot in the same container and volume. `/health` has no business data; `/snapshot` requires a 32+ character bearer secret. All SQL export operations use mode=ro and query_only. Cache: 30 seconds. No contacts, private Telegram IDs, captain names, comments, audit actors or raw attempt rows leave the bridge.
- Snapshot contains bookings, manually entered attendance, all payment methods, expenses, distributions and source aggregates. Unknown attendance and missing analytics remain null. Distributions never reduce the operating result; they reduce the remaining balance.
- Team source labels require the same Telegram account, game and exactly one completion within five minutes of booking creation. No match means unknown, not organic or zero. A link label is not proof of ad acquisition.
- Attendance game page → **Внести список оплат** accepts `Отчаянные 5 - 280П+70Н` with multiple teams. Count after name is actual attendance, amounts are thousands of UZS. У=Uzum, П=Payme, К=Click, Н=cash, `переводом`=card. Preview shows full matched team names and all methods. Missing methods become zero for listed teams only. One confirmation saves the whole list atomically; revisions and price are checked again, stale or duplicate confirmation cannot add receipts twice.
- Unlabeled amounts, non-divisible prices/discount ambiguity, duplicate or ambiguous names and payments exceeding attendance block the complete list. No fuzzy name guessing. Supported short names are explicitly listed in finance_bulk.py; exact names always work when unique.

## Verification

127 offline Python tests pass, including actual aiogram routing, cancellation, invalid text revoking an old preview, atomic rollback, source matching and read-only export. No real Telegram messages or production payment writes were used for testing.

## Release state and settings

Released 26 October 2026. Production is pinned to `323f1f99dc483ede7f05199b2f516697f7940a4e` on `codex/complete-intelligence`.

- Staging deployment `c02bae64-a833-4cc6-a755-fe6e4348fc17`: SUCCESS. Synthetic ledger/export smoke test: 6 players / 420000 UZS, repeated confirmation idempotent.
- Production deployment `872ce9c5-38e8-45b6-8d84-3dbbdf6ea5ab`: SUCCESS. Polling and all seven existing scheduler jobs started, no startup errors.
- Main database and analytics journal backed up before bot startup, both downloaded outside Railway and SHA256/integrity/restore checked.
- Live snapshot: 51 games, 370 confirmed registration records. Volosik booking for game 51 contains 11 players. Registration counts match release backup; historical payment income unchanged. No historical attendance/payment values were entered or reconciled.
- Private dashboard deployed from `4fabb70b576fc7c4394fc1ced209f6cc993bfe91`, environment revision 2. Server bridge check returned connected; actual production payload passed dashboard validation. Eleven legacy individual booking groups with empty team names are displayed as guest groups, with no database edits.
- Dashboard build and 17 tests pass. No live customer registration, payment or giveaway draw was created for testing. Browser visual QA and a real subscriber's manual click were not performed.

The first staging build failed at BUILD_IMAGE without useful logs; the fresh build succeeded. Worker HTTP reads use redirect=manual and reject redirects explicitly, compatible with the hosted runtime. Future documentation commits do not change the pinned production code.

Staging keeps its separate DB, @Razumboy_Test_Bot and disabled scheduler. Start bridge with DASHBOARD_BOT_ENTRY=finance_preview.py, PORT=8080 and its own DASHBOARD_BRIDGE_TOKEN. Production entry defaults to app.py. Do not copy preview data or credentials into production.

Before production: fresh external SQLite backups, run staging end-to-end, preserve original volume and single worker, inspect all staged changes. Configure the private Site BOT_BRIDGE_URL and BOT_BRIDGE_TOKEN to the production bridge over HTTPS; keep the token only in runtime secrets. Never deploy the old PR9 base over current code.

Historical missing source labels cannot be reconstructed. Reported attendance and receipts for prior games must be checked by the organizer before entry. Ads are read-only; no budgets, creatives or links are changed by this release.
