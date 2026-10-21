"""Privacy-safe Telegram admin digest for registration analytics."""
import asyncio
import html
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from analytics_report import build_report

log = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Tashkent")


def _events(db_path, as_of, event_id=None):
    if event_id is not None and (type(event_id) is not int or not 0 < event_id < 2**63):
        raise ValueError("Invalid event ID")
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=0.2)) as conn:
        conn.row_factory = sqlite3.Row
        # One statement provides a consistent snapshot of events and business counts.
        where = "e.id=?" if event_id is not None else "e.event_date >= ? AND e.status='open'"
        rows = conn.execute(
            "SELECT e.id,e.title,e.event_date,e.event_time,e.max_teams,"
            "COUNT(CASE WHEN r.status='confirmed' THEN 1 END) AS teams,"
            "COALESCE(SUM(CASE WHEN r.status='confirmed' THEN r.team_size ELSE 0 END),0) AS players,"
            "COUNT(CASE WHEN r.status='cancelled' THEN 1 END) AS cancelled "
            "FROM events e LEFT JOIN registrations r ON r.event_id=e.id "
            f"WHERE {where} GROUP BY e.id ORDER BY e.event_date,e.event_time,e.id",
            (event_id if event_id is not None else as_of.date().isoformat(),)
        ).fetchall()
    return [dict(r) for r in rows]


def _field(value, limit=200):
    # Keep each HTML line bounded; dynamic fields must never introduce markup/newlines.
    return html.escape(' '.join(str(value or '').splitlines())[:limit])


def split_digest(text):
    """Split on complete lines (all markup is balanced within a line)."""
    chunks, lines, size = [], [], 0
    for line in text.splitlines():
        length = len(line.encode('utf-16-le')) // 2
        if length > 3900:
            raise ValueError("Digest line too long")
        if lines and size + length + 1 > 3900:
            chunks.append('\n'.join(lines))
            lines, size = [], 0
        lines.append(line)
        size += length + 1
    if lines:
        chunks.append('\n'.join(lines))
    return chunks


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
        f"С {since:%d.%m.%Y %H:%M:%S} до {now:%d.%m.%Y %H:%M:%S} (Ташкент, конец не включён).",
    ]
    events = _events(db_path, now, event_id)
    if not events:
        lines.append("Открытых предстоящих игр не найдено." if event_id is None else "Игра не найдена.")
        return "\n".join(lines)
    journal = str(db_path) + ".analytics.sqlite"
    for event in events:
        eid = event["id"]
        confirmed, players, cancelled = event['teams'], event['players'], event['cancelled']
        capacity = event.get("max_teams")
        limit_text = f"/{capacity}" if capacity is not None and capacity > 0 else ""
        lines.extend([
            "",
            f"🎯 <b>#{eid} — {_field(event['title'])}</b>",
            f"📅 {_field(event['event_date'], 30)} {_field(event['event_time'], 30)}",
            f"👥 Заявки: <b>{confirmed}{limit_text} команд</b> · {players} заявленных участников",
            f"Отменённые заявки: {cancelled}",
        ])
        try:
            r = build_report(journal, event_id=eid, date_from=since.isoformat(), date_to=now.isoformat())
            oc = r["outcome_counts"]
            lines.extend([
                f"🔗 Запуски / карточки: {r['bot_starts']} / {r['event_cards_sent']}",
                f"📝 Начали / завершили за 24ч: {r['registrations_started']} / {r['registrations_completed']}",
                f"Исходы попыток с активностью за 24ч: открытые {oc['unfinished']}, отменённые {oc['cancelled']}, заменённые {oc['superseded']}, ошибки {oc['technical_errors']}, дубликаты {oc['duplicates']}, недоступные {oc['unavailable']}",
            ])
            if oc["unfinished"]:
                from collections import Counter
                from analytics import STEPS
                dropoffs = Counter(a.get('expected_step') if a.get('expected_step') in STEPS else 'unknown' for a in r["unfinished"])
                lines.append("Ожидаемый следующий шаг: " + ", ".join(f"{html.escape(str(k))} — {v}" for k, v in sorted(dropoffs.items())))
            by_source = r.get("by_source", {})
            source_parts = [f"{html.escape(label)}: {events.get('registration_started',0)} нач., {events.get('registration_completed',0)} заверш."
                            for label, events in sorted(by_source.items()) if events.get('registration_started',0) or events.get('registration_completed',0)]
            if source_parts:
                lines.append("Метки: " + "; ".join(source_parts))
        except (OSError, sqlite3.Error, ValueError, KeyError):
            log.warning("digest_analytics_read_failed")
            lines.append("⚠️ Аналитика временно недоступна; заявки отображены отдельно.")
    lines.append("\nℹ️ Заявки ≠ пришедшие команды; заявленные игроки ≠ оплаченные билеты. Начала — попытки, не уникальные люди. Метка ссылки ≠ доказанный рекламный источник. Открытые формы ≠ окончательный отказ. Отчёт не является когортной конверсией.")
    lines.append("Подробно по любой игре, включая прошедшие: /report ID")
    return "\n".join(lines)


def digest_enabled():
    return os.getenv("ADMIN_DIGEST_ENABLED", "0").strip() == "1"


async def send_daily_digest(bot, db, admin_ids):
    """Fail per-admin without affecting scheduler or Telegram polling."""
    if not digest_enabled():
        return
    try:
        messages = split_digest(await asyncio.to_thread(format_digest, db.db_path))
    except Exception:
        log.warning("digest_build_failed")
        return
    for admin_id in set(admin_ids):
        try:
            for msg in messages:
                await bot.send_message(admin_id, msg, parse_mode='HTML')
        except Exception:
            log.warning("digest_send_failed")
