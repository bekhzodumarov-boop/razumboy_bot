from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def upcoming_event_kb(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Зарегистрироваться", callback_data=f"register_event_{event_id}")],
        ]
    )


def confirm_registration_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_registration")],
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
