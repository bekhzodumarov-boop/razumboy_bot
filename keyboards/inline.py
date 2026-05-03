from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def upcoming_event_kb(event_id: int, bot_username: str = "Razumboy_Bot"):
    share_url = (
        f"https://t.me/share/url"
        f"?url=https://t.me/{bot_username}?start%3Devent_{event_id}"
        f"&text=%F0%9F%A7%A0+%D0%A1%D0%BC%D0%BE%D1%82%D1%80%D0%B8+%D0%B0%D0%BD%D0%BE%D0%BD%D1%81+%D0%B8%D0%B3%D1%80%D1%8B+%D0%A0%D0%B0%D0%B7%D1%83%D0%BC%D0%B1%D0%BE%D0%B9%21"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Зарегистрироваться", callback_data=f"register_event_{event_id}"),
                InlineKeyboardButton(text="📤 Поделиться", url=share_url),
            ],
        ]
    )


def confirm_registration_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_registration")],
            [InlineKeyboardButton(text="✏️ Изменить данные", callback_data="edit_registration")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_registration")],
        ]
    )


def events_choose_kb(events, prefix="choose_event"):
    """Кнопки выбора игры с датой и названием"""
    from handlers.common import format_date_short
    buttons = []
    for event in events:
        date_short = format_date_short(event["event_date"])
        buttons.append([InlineKeyboardButton(
            text=f"📅 {date_short} — {event['title']}",
            callback_data=f"{prefix}_{event['id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
