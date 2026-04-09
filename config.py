import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    bot_token: str
    admin_ids: list[int]
    db_path: str


def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()
    db_path = os.getenv("DB_PATH", "razumboy.db").strip()

    if not bot_token:
        raise ValueError("BOT_TOKEN is not set")

    admin_ids = []
    if admin_ids_raw:
        admin_ids = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip()]

    return Config(
        bot_token=bot_token,
        admin_ids=admin_ids,
        db_path=db_path,
    )
