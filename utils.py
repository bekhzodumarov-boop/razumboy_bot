"""
utils.py — Вспомогательные функции

read_template(name) — читает текст из templates/{name}.txt при каждом вызове.
Благодаря этому редактирование файлов в Obsidian сразу отражается
в следующей рассылке (после коммита и деплоя на Railway).
"""
import os


def read_template(name: str, fallback: str = "") -> str:
    """
    Читает шаблон из папки templates/{name}.txt.

    Если файл не найден — возвращает fallback.
    Файл читается КАЖДЫЙ РАЗ при вызове, поэтому изменения подхватываются
    без перезапуска бота (актуально при hot-reload или bind-mount).
    """
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    path = os.path.join(templates_dir, f"{name}.txt")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return fallback
