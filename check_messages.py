import json, re
from datetime import datetime

WINNER_KEYWORDS = [
    "Барабанная дробь", "Рандомбой сделал свой выбор",
    "Рандомбой совершенно случайно", "бесплатные проходки",
    "выбрал победител", "получают @", "получает @",
]

def get_text(msg):
    t = msg.get("text", "")
    if isinstance(t, str): return t
    return "".join(i if isinstance(i, str) else i.get("text", "") for i in t)

with open(r"C:\Users\bekhzod.umarov\Downloads\Telegram Desktop\ChatExport_2026-05-14\result.json", encoding="utf-8") as f:
    data = json.load(f)

out = []
for msg in data["messages"]:
    if msg.get("type") != "message": continue
    text = get_text(msg)
    if not any(kw.lower() in text.lower() for kw in WINNER_KEYWORDS): continue
    date = datetime.fromisoformat(msg["date"]).strftime("%Y-%m-%d")
    mentions = re.findall(r"@[\w\d_]+", text)
    out.append(f"[{date}] mentions={mentions}\n{text[:200]}\n{'---'*20}\n")

with open("matched_messages.txt", "w", encoding="utf-8") as f:
    f.write(f"Всего совпадений: {len(out)}\n\n")
    f.writelines(out)

print(f"Done. {len(out)} messages written to matched_messages.txt")
