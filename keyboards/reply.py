from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎯 Ближайшие игры"), KeyboardButton(text="📝 Регистрация")],
            [KeyboardButton(text="📸 Фотографии с игр"), KeyboardButton(text="🗂 Мои регистрации")],
            [KeyboardButton(text="📬 Получать анонсы"), KeyboardButton(text="❓ Задать вопрос")],
        ],
        resize_keyboard=True,
    )


def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Создать игру"), KeyboardButton(text="📋 Список игр")],
            [KeyboardButton(text="📨 Рассылка"), KeyboardButton(text="📥 Заявки")],
            [KeyboardButton(text="📊 Экспорт в Excel"), KeyboardButton(text="👥 Подписчики")],
            [KeyboardButton(text="❌ Отменить игру"), KeyboardButton(text="📬 История рассылок")],
            [KeyboardButton(text="🗓 Прошедшие игры"), KeyboardButton(text="📥 База подписчиков")],
            [KeyboardButton(text="🎲 Рандомбой"), KeyboardButton(text="⚡️ Блиц-квиз")],
            [KeyboardButton(text="🎟 Проходка"), KeyboardButton(text="📸 Фото с игр")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def phone_request_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поделиться номером", request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def broadcast_type_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Анонс активной игры", callback_data="broadcast_event")],
            [InlineKeyboardButton(text="⏰ Напоминание за день до игры", callback_data="broadcast_reminder")],
            [InlineKeyboardButton(text="📨 Напоминание в день игры", callback_data="broadcast_dayof")],
            [InlineKeyboardButton(text="✍️ Свой пост", callback_data="broadcast_custom")],
        ]
    )


def events_list_kb(events, prefix="broadcast_event"):
    buttons = []
    for event in events:
        buttons.append([InlineKeyboardButton(
            text=f"📅 {event['title']} ({event['event_date']})",
            callback_data=f"{prefix}_{event['id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
