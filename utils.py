"""
utils.py — Вспомогательные функции

read_template(name) — читает текст из templates/{name}.txt при каждом вызове.

sync_templates_to_db(db) — вызывается при старте бота.
  Читает шаблоны из файлов и записывает в базу данных.
  Это позволяет редактировать тексты в Obsidian:
    1. Изменить файл в Obsidian
    2. git commit + git push
    3. Railway деплоит (~2 мин)
    4. Бот стартует → читает файл → обновляет DB
    5. Следующая рассылка уходит с новым текстом ✅
"""
import logging
import os

logger = logging.getLogger(__name__)


def read_template(name: str, fallback: str = "") -> str:
    """
    Читает шаблон из папки templates/{name}.txt.
    Если файл не найден — возвращает fallback.
    """
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    path = os.path.join(templates_dir, f"{name}.txt")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return fallback


def sync_templates_to_db(db) -> None:
    """
    Синхронизирует шаблоны из файлов в базу данных при старте бота.

    Обновляет только текстовые поля — остальные настройки
    (время, картинка, количество победителей и т.д.) не трогаются.

    Файлы → DB:
      giveaway_announce.txt  → giveaway_settings.announce_text
      giveaway_congrats.txt  → giveaway_settings.congrats_text
    """
    settings = db.get_giveaway_settings()
    if not settings:
        # Розыгрыш ещё не настроен — пропускаем
        logger.info("sync_templates_to_db: giveaway_settings не найден, пропускаем")
        return

    synced = []

    announce = read_template("giveaway_announce")
    if announce and announce != (settings["announce_text"] or ""):
        db.update_giveaway_field("announce_text", announce)
        synced.append("giveaway_announce")

    congrats = read_template("giveaway_congrats")
    if congrats and congrats != (settings["congrats_text"] or ""):
        db.update_giveaway_field("congrats_text", congrats)
        synced.append("giveaway_congrats")

    if synced:
        logger.info(f"sync_templates_to_db: обновлено из файлов: {', '.join(synced)}")
    else:
        logger.info("sync_templates_to_db: изменений нет, DB актуальна")
