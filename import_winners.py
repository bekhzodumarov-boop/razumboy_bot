"""
import_winners.py — Импорт победителей Рандомбой из экспорта Telegram Desktop.

Использование:
    python import_winners.py result.json [путь_к_БД]

Аргументы:
    result.json  — файл экспорта из Telegram Desktop (формат JSON)
    путь_к_БД    — опционально, по умолчанию /data/razumboy.db
                   для локального теста укажи путь к локальной БД

Пример:
    python import_winners.py "C:/Users/.../result.json"
    python import_winners.py result.json ./razumboy_local.db
"""

import json
import re
import sqlite3
import sys
import os
from datetime import datetime


# ── Ключевые слова для поиска сообщений с результатами ────────
WINNER_KEYWORDS = [
    "Барабанная дробь",
    "Рандомбой сделал свой выбор",
    "Рандомбой совершенно случайно",
    "выбрал победител",
    "бесплатн",     # "бесплатные проходки получают"
]


def get_text(msg) -> str:
    """Получить полный текст сообщения (text может быть строкой или списком)."""
    t = msg.get("text", "")
    if isinstance(t, str):
        return t
    if isinstance(t, list):
        parts = []
        for item in t:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", ""))
        return "".join(parts)
    return ""


def extract_usernames(msg) -> list[str]:
    """Извлечь @username из текста и из объектов mention/text_link."""
    usernames = set()

    t = msg.get("text", "")
    items = t if isinstance(t, list) else [t]

    for item in items:
        if isinstance(item, str):
            # ищем @username в тексте
            for m in re.finditer(r"@([\w\d_]+)", item):
                usernames.add(m.group(1).lower())
        elif isinstance(item, dict):
            item_type = item.get("type", "")
            item_text = item.get("text", "")
            if item_type in ("mention", "mention_name"):
                # @username уже в тексте объекта
                for m in re.finditer(r"@([\w\d_]+)", item_text):
                    usernames.add(m.group(1).lower())
                # или без @
                if item_text and not item_text.startswith("@"):
                    clean = item_text.strip().lstrip("@")
                    if re.match(r"^[\w\d_]+$", clean):
                        usernames.add(clean.lower())

    return list(usernames)


def parse_date(date_str: str) -> str:
    """Привести дату из формата Telegram к YYYY-MM-DD."""
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return date_str[:10]


def is_winner_message(text: str) -> bool:
    """Проверить, является ли сообщение объявлением победителей."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in WINNER_KEYWORDS)


def import_to_db(db_path: str, winners: list[dict]):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Создаём таблицу если вдруг нет
    conn.execute("""
        CREATE TABLE IF NOT EXISTS giveaway_winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL DEFAULT 0,
            username TEXT,
            full_name TEXT,
            won_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    inserted = 0
    skipped = 0
    for w in winners:
        # Проверяем дубли (одинаковый username + дата)
        existing = conn.execute("""
            SELECT id FROM giveaway_winners
            WHERE username = ? AND date(won_at) = ?
        """, (w["username"], w["won_at"])).fetchone()
        if existing:
            skipped += 1
            continue

        conn.execute("""
            INSERT INTO giveaway_winners (telegram_id, username, full_name, won_at)
            VALUES (0, ?, ?, ?)
        """, (w["username"], w["username"], w["won_at"]))
        inserted += 1

    conn.commit()
    conn.close()
    return inserted, skipped


def main():
    if len(sys.argv) < 2:
        print("Использование: python import_winners.py result.json [путь_к_БД]")
        sys.exit(1)

    json_path = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else "/data/razumboy.db"

    if not os.path.exists(json_path):
        print(f"❌ Файл не найден: {json_path}")
        sys.exit(1)

    if not os.path.exists(db_path):
        print(f"⚠️  БД не найдена по пути: {db_path}")
        print("   Укажите путь к БД вторым аргументом.")
        sys.exit(1)

    print(f"📂 Читаю: {json_path}")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    print(f"📨 Всего сообщений в экспорте: {len(messages)}")

    found_winners: list[dict] = []

    for msg in messages:
        if msg.get("type") != "message":
            continue
        text = get_text(msg)
        if not is_winner_message(text):
            continue

        date_str = parse_date(msg.get("date", ""))
        usernames = extract_usernames(msg)

        # Исключаем служебные/бот-аккаунты
        usernames = [u for u in usernames if u not in ("razumboy", "razumboy_bot", "voyrazumboy")]

        if not usernames:
            print(f"⚠️  [{date_str}] Найдено сообщение, но без @username:\n   {text[:120]}")
            continue

        for username in usernames:
            found_winners.append({"username": username, "won_at": date_str})
            print(f"✅ [{date_str}] Победитель: @{username}")

    if not found_winners:
        print("\n❌ Не найдено ни одного сообщения с победителями.")
        print("   Проверьте, что экспортируете нужный канал и правильный период.")
        sys.exit(0)

    print(f"\n🏆 Найдено победителей: {len(found_winners)}")
    print(f"💾 Записываю в БД: {db_path}")

    inserted, skipped = import_to_db(db_path, found_winners)
    print(f"\n✅ Готово! Добавлено: {inserted}, пропущено дублей: {skipped}")


if __name__ == "__main__":
    main()
