"""
parse_winners.py — парсит экспорт Telegram Desktop и генерирует SQL для вставки победителей.
Фильтр: только сообщения "Барабанная дробь" (точные результаты розыгрыша).
"""
import json, re, sys, os
from datetime import datetime

SKIP_USERS = {"razumboy", "razumboy_bot", "voyrazumboy"}

def get_text(msg):
    t = msg.get("text", "")
    if isinstance(t, str): return t
    return "".join(i if isinstance(i, str) else i.get("text", "") for i in t)

def extract_usernames(msg):
    found = set()
    t = msg.get("text", "")
    items = t if isinstance(t, list) else [t]
    for item in items:
        if isinstance(item, str):
            for m in re.finditer(r"@([\w\d_]{3,})", item):
                found.add(m.group(1).lower())
        elif isinstance(item, dict) and item.get("type") in ("mention", "mention_name"):
            raw = item.get("text", "").lstrip("@")
            if re.match(r"^[\w\d_]{3,}$", raw):
                found.add(raw.lower())
    return found - SKIP_USERS

def parse_date(s):
    try:
        return datetime.fromisoformat(s).strftime("%Y-%m-%d")
    except Exception:
        return s[:10]

json_path = sys.argv[1] if len(sys.argv) > 1 else "result.json"
with open(json_path, encoding="utf-8") as f:
    data = json.load(f)

winners = []
for msg in data["messages"]:
    if msg.get("type") != "message": continue
    text = get_text(msg)
    # Строгий фильтр — только сообщения с результатом розыгрыша
    if "Барабанная дробь" not in text:
        continue
    date = parse_date(msg.get("date", ""))
    users = extract_usernames(msg)
    for u in users:
        winners.append((u, date))

winners = list(dict.fromkeys(winners))  # дедупликация

# SQL
sql_path = os.path.join(os.path.dirname(json_path), "winners_insert.sql")
with open(sql_path, "w", encoding="utf-8") as f:
    f.write("-- Импорт победителей Рандомбой из истории канала\n\n")
    for username, won_at in winners:
        f.write(
            f"INSERT OR IGNORE INTO giveaway_winners (telegram_id, username, full_name, won_at) "
            f"VALUES (0, '{username}', '{username}', '{won_at} 21:00:00');\n"
        )

# Лог
log_path = os.path.join(os.path.dirname(json_path), "winners_found.txt")
with open(log_path, "w", encoding="utf-8") as f:
    f.write(f"Найдено победителей: {len(winners)}\n\n")
    for username, date in winners:
        f.write(f"[{date}] @{username}\n")

print(f"Done. Found {len(winners)} winners. SQL -> {sql_path}")
