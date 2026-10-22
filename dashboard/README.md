# RAZUMBOY Intelligence MVP

Standalone browser dashboard. It does not import bot configuration, start polling, connect to production or change bot tables. Private test hosting uses Sites owner access, not an embedded password. No analytics trackers, external fonts or paid APIs.

## Included

- Editable period, format and game/team search filters; attendance trend and drilldowns.
- Per-game team rosters; name-based repeat teams (not unique individual players).
- October competitor snapshot, UZQUIZ separately; dataset limitations visible.
- Filtered CSV with formula protection; validated JSON import/export with local browser persistence.
- No fabricated finance, revenue, payments, marketing attribution or AI output.

Seed data: organizer-provided attendance for six games 1–22 October 2026. Both checkmarks and hourglasses mean attended by explicit organizer instruction. 49 team participations and 243 player visits. Two standalone guest records count toward player visits only. The unnamed two-person group on October 18 counts as one team, with a neutral display label rather than a personal handle. 22 October is included on the organizer's instruction. Team name normalization cannot resolve renames or changing rosters.

## Local launch

```bash
python -m http.server 8080 --bind 127.0.0.1 --directory dashboard/web
```

Open http://127.0.0.1:8080. This local server is for local testing only. Do not expose it on a public interface as authentication is provided by the private hosting layer, not this static app.

## Read-only export on the machine with the database

```bash
python dashboard/export_snapshot.py --db /data/razumboy.db --from 2026-10-01 --to 2026-10-31 --out /tmp/razumboy-dashboard-20261022.json
```

Optionally add `--analytics /data/razumboy.db.analytics.sqlite` for aggregate funnel counts per selected game over the journal's complete recorded history. Funnel counts are activity counters, not payments. Game date filters select games, not funnel activity dates. Missing analytics leaves metrics unknown. Export does not select user, phone, captain, comment or attempt-level fields. It uses SQLite URI `mode=ro`, `query_only`, and a consistent transaction. It never creates an absent DB or initializes/migrates its schema. Output must be a new file, never an input DB.

Import replaces the browser dataset. It does not merge with manual attendance, does not upload to a server, and cannot update the bot. Confirmation in bot records is a registration, so `attended: null` until backed by a separate attendance source. Do not export personal data in team names. JSON text fields render via escaping; unsupported keys are dropped.

No live production connection has been configured. To add it later, introduce a separately authenticated API with an explicit attendance/payment ledger. Never mount the production volume writable for the dashboard.

## Checks

```bash
node --test dashboard/test_model.mjs
python -m unittest discover -s dashboard -p 'test_*.py'
```

The Data section contains an end-user verification checklist. Known gaps: no live refresh, login/roles beyond private hosting owner access, financial ledger, CSV/XLSX import, team ID matching or automated AI recommendations. Competitor date calendars are incomplete and not synthesized.
