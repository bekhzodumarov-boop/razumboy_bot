"""Privacy-safe Telegram admin digest for registration analytics."""
import html
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from analytics_report import build_report

log = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Tashkent")


def _counts(db_path, event_id):
    uri = "file:" + db_path + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*), COALESCE(SUM(team_size),0) "
            "FROM registrations WHERE event_id=? GROUP BY status", (event_id,)
        ).fetchall()
    return {status: (n, players) for status, n, players in rows}


def _events(db_path, as_of, event_id=None):
    uri = "file:" + db_path + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
        conn.row_factory = sqlite3.Row
        if event_id:
            rows = conn.execute(
                "SELECT id,title,event_date,event_time,max_teams,status FROM events WHERE id=?",
                (event_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,title,event_date,event_time,max_teams,status FROM events "
                "WHERE event_date >= ? AND status='open' ORDER BY event_date,event_time LIMIT 5",
                (as_of.date().isoformat(),)
            ).fetchall()
    return [dict(r) for r in rows]


def format_digest(db_path, *, event_id=None, now=None):
    """Read-only, aggregated output. No names, phones, IDs or raw analytics rows."""
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(TZ)
    since = now - timedelta(hours=24)
    lines = [
        "📊 <b>RAZUMBOY — отчёт по регистрациям</b>",
        f"🕒 {now:%d.%m.%Y %H:%M} (Ташкент)",
        "Окно аналитики: последние 24 часа; заявки — на текущий момент.",
    ]
    events = _events(db_path, now, event_id)
    if not events:
        lines.append("Открытых предстоящих игр не найдено." if event_id is None else "Игра не найдена.")
        return "\n".join(lines)
    journal = db_path + ".analytics.sqlite"
    for event in events:
        eid = event["id"]
        statuses = _counts(db_path, eid)
        confirmed, players = statuses.get("confirmed", (0, 0))
        cancelled, _ = statuses.get("cancelled", (0, 0))
        capacity = event.get("max_teams")
        limit_text = f"/{capacity}" if capacity is not None and capacity > 0 else ""
        lines.extend([
            "",
            f"🎯 <b>#{eid} — {html.escape(event['title'])}</b>",
            f"📅 {event['event_date']} {event['event_time']}",
            f"👥 Заявки: <b>{confirmed}{limit_text} команд</b> · {players} заявленных участников",
            f"Отменённые заявки: {cancelled}",
        ])
        try:
            r = build_report(journal, event_id=eid, date_from=since.isoformat(), date_to=now.isoformat())
            oc = r["outcome_counts"]
            lines.extend([
                f"🔗 Запуски / карточки: {r['bot_starts']} / {r['event_cards_sent']}",
                f"📝 Начали / завершили за 24ч: {r['registrations_started']} / {r['registrations_completed']}",
                f"Формы: открытые {oc['unfinished']}, отменённые {oc['cancelled']}, заменённые {oc['superseded']}, ошибки {oc['technical_errors']}",
            ])
            if oc["unfinished"]:
                from collections import Counter
                dropoffs = Counter(a.get("expected_step") or "unknown" for a in r["unfinished"])
                lines.append("Ожидаемый следующий шаг: " + ", ".join(f"{html.escape(str(k))} — {v}" for k, v in sorted(dropoffs.items())))
            by_source = r.get("by_source", {})
            source_parts = [f"{html.escape(label)}: {events.get('registration_started',0)} нач., {events.get('registration_completed',0)} заверш."
                            for label, events in sorted(by_source.items()) if events.get('registration_started',0) or events.get('registration_completed',0)]
            if source_parts:
                lines.append("Метки: " + "; ".join(source_parts))
        except (OSError, sqlite3.Error, ValueError, KeyError):
            log.warning("digest_analytics_read_failed")
            lines.append("⚠️ Аналитика временно недоступна; заявки отображены отдельно.")
    lines.append("\nℹ️ Заявки ≠ оплаты/пришедшие. Метка ссылки ≠ доказанный рекламный источник. Открытые формы ≠ окончательный отказ. Отчёт не является когортной конверсией.")
    return "\n".join(lines)


def digest_enabled():
    return os.getenv("ADMIN_DIGEST_ENABLED", "0").strip() == "1"


async def send_daily_digest(bot, db, admin_ids):
    """Fail per-admin without affecting scheduler or Telegram polling."""
    if not digest_enabled():
        return
    try:
        msg = format_digest(db.db_path)
    except Exception:
        log.warning("digest_build_failed")
        return
    for admin_id in set(admin_ids):
        try:
            await bot.send_message(admin_id, msg)
        except Exception:
            log.warning("digest_send_failed")
