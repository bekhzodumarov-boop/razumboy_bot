# Read-only production bridge

Base: cbac6ffa7cb9e98341003dfecd47c6afaa0d554b, the production deployment verified 22 October 2026. This branch adds dashboard files only and does not include later main-branch bot changes.

Proposed production start command: `python dashboard/run_bridge.py`.

It starts the original unchanged app.py exactly once, plus a read-only HTTP bridge in the same container and volume. `/snapshot` requires a generated bearer token; `/health` exposes only process health. Export omits phone, captain, user and Telegram identifiers. Confirmed registrations remain attendance-unknown. No schemas or data are modified.

Required runtime: existing DB_PATH; new DASHBOARD_BRIDGE_TOKEN; DASHBOARD_ANALYTICS_PATH=/data/razumboy.db.analytics.sqlite; Railway PORT and HTTPS domain. Secret values are stored only in runtime secrets and must match the private dashboard server.

The Railway patch is prepared, not deployed. Deploying a volume-backed service briefly interrupts polling. Obtain explicit approval before committing staged changes. Rollback: restore previous source commit and start command; never restore an old database over new registrations.

Verification before release: Python read-only/privacy tests and HTTP authorization tests. After release: terminal SUCCESS, authenticated snapshot, no anonymous access, bot polling, and dashboard live read. Failures must not be described as a successful integration.
