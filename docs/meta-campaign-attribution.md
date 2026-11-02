# Meta campaign attribution

Status: implementation tested locally; not deployed by this change.

Use a separate Telegram destination per publisher platform and Meta campaign:

```
https://t.me/Razumboy_Bot?start=event_GAME_ID_src_instagram_cmp_META_CAMPAIGN_ID
https://t.me/Razumboy_Bot?start=event_GAME_ID_src_facebook_cmp_META_CAMPAIGN_ID
```

Replace GAME_ID with the bot's actual game ID (not the yearly game number), and
META_CAMPAIGN_ID with Meta's numeric campaign ID. Do not paste the literal example
placeholders into an ad. `analytics.build_event_link` validates both and enforces
Telegram's 64-character start payload limit. These links distinguish campaigns,
not individual ads/ad sets. Separate platform destinations must be configured in
the relevant Meta ads; the bot does not infer the platform from the Telegram app.

Legacy `event_ID` and `event_ID_src_instagram` links continue working. Unknown
legacy source labels remain `unknown`. Only known source enums and numeric
campaign IDs (1–20 digits, no leading zero) are retained, never arbitrary payloads
or campaign names. Historical untagged links cannot acquire campaign attribution
retroactively. Old unknown Facebook records are not relabeled.

## Behavior

- Store platform and campaign on bot start and successful game-card delivery.
- Freeze both on registration start, carry them through profile onboarding,
  editing, continuation and restarting a form for the same game.
- A later /start does not rewrite an already-started registration's attribution.
- Another game does not inherit that game's campaign. A fresh untagged /start
  clears the pending campaign tag. Registration through the general menu retains
  its existing `menu` attribution behavior.
- `/report ID` (24 hours) and `/report ID all` list starts and completions per
  platform/campaign. Untagged platform traffic is explicitly shown separately.
- Offline report filtering: `python analytics.py JOURNAL --event-id ID
  --source facebook --campaign-id META_CAMPAIGN_ID`.
- Read-only bridge exports campaign aggregates and matched booking campaign ID.
  Team matching still requires the exact account/game and a unique completed
  attempt within five minutes of booking creation. No personal IDs are exported.
  Dashboard visual campaign breakdown is outside this bot change.

These are link-use labels, not proof of paid acquisition: forwarded links retain
their tags. Starts are attempts, not unique paid players; clicks in Meta are not
Telegram bot starts. Missing campaign tags remain unknown, not zero conversions.

## Release

Analytics startup adds nullable `campaign_id` to the separate journal in an
idempotent transaction. Existing records remain NULL; the business database is
unchanged. Reports can read older journals without running migrations. Roll back
code without restoring an older database over new registrations.

Before production release: take the normal SQLite backups, deploy to the test
bot, open both platform links, complete a test registration and check the report.
Only then deploy the production bot with its existing volume/scheduler settings.
