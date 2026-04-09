import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from keyboards.reply import main_menu
from keyboards.inline import upcoming_event_kb
from states import AskQuestionState

router = Router()

# Фотографии с игр — статический список (пункт 8)
PHOTO_ALBUMS = [
    {"title": "29 марта, Razumbooo", "url": "https://t.me/razumboyphotos/12138"},
    {"title": "22 марта, Razumbooo", "url": "https://t.me/razumboyphotos/12079"},
    {"title": "15 марта, Razumbooo", "url": "https://t.me/razumboyphotos/12043"},
    {"title": "8 марта, Razumbooo",  "url": "https://t.me/razumboyphotos/11986"},
]

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
}

DAYS_RU = {
    0: "понедельник", 1: "вторник", 2: "среда",
    3: "четверг", 4: "пятница", 5: "суббота", 6: "воскресенье"
}


def format_date_ru(date_str: str) -> str:
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_RU[dt.month]} {dt.year} г., {DAYS_RU[dt.weekday()]}"
    except Exception:
        return date_str


def format_date_short(date_str: str) -> str:
    """Короткий формат: 29 марта (пятница)"""
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_RU[dt.month]} ({DAYS_RU[dt.weekday()]})"
    except Exception:
        return date_str


def format_event(event) -> str:
    date_ru = format_date_ru(event["event_date"])
    location_line = f"🏡: {event['location']}"
    if event["location_url"]:
        location_line += f"\n📍 Локация: {event['location_url']}"

    return (
        f"<b>{event['title']}</b>\n\n"
        f"{event['description'] or ''}\n\n"
        f"✍️ Спешите зарегистрироваться, количество мест ограничено!\n\n"
        f"📆: {date_ru}\n\n"
        f"⌚️: {event['event_time']}\n\n"
        f"{location_line}\n\n"
        f"🤑: {event['price_text'] or 'уточняется'}\n\n"
        f"🧐 Напоминаем, что игра командная, от 6 до 12 человек в каждой "
        f"(Если у вас нет команды, не переживайте, мы вам её подберём).\n\n"
        f"👨‍💻 Вход строго по регистрации!\n\n"
        f"✍️ Для регистрации напишите в телеграм-бот @Razumboy_Bot название своей команды и количество игроков.\n\n"
        f"☕️ Приходите и приводите своих друзей!\n\n"
        f"💃 До скорой встречи!\n\n"
        f"🌐 www.razumboy.uz\n"
        f"☎️ +998998355500\n\n"
        f"🕊 <a href='https://t.me/VoyRazumboy'>Telegram</a> | "
        f"📱 <a href='https://www.instagram.com/voyrazumboy/'>Instagram</a>\n"
        f"📺 <a href='https://www.youtube.com/@VoyRazumboy'>YouTube</a> | "
        f"📱 <a href='https://www.facebook.com/razumboy.tashkent'>Facebook</a>"
    )


# ── Пункт 10: Приветствие до /start ──────────────────────────
# Обрабатываем любое первое сообщение от незнакомого пользователя

# ── Пункт 11, 12: /start — подписка + список игр ─────────────
@router.message(F.text == "/start")
async def cmd_start(message: Message, db, admin_ids: list[int]):
    user = message.from_user
    db.upsert_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name,
        language_code=user.language_code,
        is_admin=user.id in admin_ids,
    )
    # Пункт 12: сразу подписываем
    db.set_subscription(user.id, True)

    await message.answer(
        "Добро пожаловать в бот Разумбой! 🧠\nВыберите действие в меню ниже.",
        reply_markup=main_menu(),
    )

    # Пункт 11: сразу показываем список активных игр
    events = db.get_open_events()
    if events:
        await _show_events_list(message, events)


# ── Пункт 4: Ближайшие игры — список кнопок ──────────────────
@router.message(F.text == "🎯 Ближайшие игры")
async def show_upcoming_events(message: Message, db):
    events = db.get_open_events()
    if not events:
        await message.answer("Пока нет открытых игр. Скоро добавим новый анонс! 🔔")
        return
    await _show_events_list(message, events)


async def _show_events_list(message: Message, events: list):
    """Показать список игр кнопками"""
    buttons = []
    for event in events:
        date_short = format_date_short(event["event_date"])
        buttons.append([InlineKeyboardButton(
            text=f"📅 {date_short} — {event['title']}",
            callback_data=f"show_event_{event['id']}"
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("🎯 <b>Ближайшие игры:</b>\nВыберите игру для подробной информации:", reply_markup=kb)


@router.callback_query(F.data.startswith("show_event_"))
async def show_event_detail(callback: CallbackQuery, db):
    event_id = int(callback.data.split("_")[-1])
    event = db.get_event_by_id(event_id)
    if not event:
        await callback.answer("Игра не найдена.")
        return
    text = format_event(event)
    if event["photo_file_id"]:
        if len(text) <= 1024:
            await callback.message.answer_photo(
                photo=event["photo_file_id"],
                caption=text,
                reply_markup=upcoming_event_kb(event["id"])
            )
        else:
            await callback.message.answer_photo(
                photo=event["photo_file_id"],
                reply_markup=upcoming_event_kb(event["id"])
            )
            await callback.message.answer(text, reply_markup=upcoming_event_kb(event["id"]))
    else:
        await callback.message.answer(text, reply_markup=upcoming_event_kb(event["id"]))
    await callback.answer()


# ── Пункт 8: Фотографии с игр — список альбомов ──────────────
@router.message(F.text == "📸 Фотографии с игр")
async def photos(message: Message):
    buttons = []
    for album in PHOTO_ALBUMS:
        buttons.append([InlineKeyboardButton(text=f"📸 {album['title']}", url=album["url"])])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("📸 <b>Фотографии с наших игр:</b>\nВыберите игру:", reply_markup=kb)


# ── Пункт 9: Задать вопрос — FSM ─────────────────────────────
@router.message(F.text == "❓ Задать вопрос")
async def ask_question(message: Message, state: FSMContext):
    await state.set_state(AskQuestionState.waiting_question)
    await message.answer("Напишите ваш вопрос — организаторы увидят его и ответят. ✍️")


@router.message(AskQuestionState.waiting_question)
async def receive_question(message: Message, state: FSMContext, bot, admin_ids: list[int]):
    question = message.text.strip()
    # Пересылаем вопрос админам
    admin_text = (
        f"❓ <b>Вопрос от пользователя</b>\n\n"
        f"{question}\n\n"
        f"User: @{message.from_user.username or 'без username'} ({message.from_user.id})"
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception:
            pass

    await state.clear()
    await message.answer(
        "✅ Мы получили ваш вопрос и ответим в ближайшее время!",
        reply_markup=main_menu()
    )


@router.message(F.text == "🏠 Главное меню")
async def back_to_main(message: Message):
    await message.answer("Главное меню:", reply_markup=main_menu())


# ── Подписка с анкетой ────────────────────────────────────────
from states import AskQuestionState, SubscribeState
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton as KB


@router.message(F.text == "📬 Подписаться")
async def subscribe_start(message: Message, state: FSMContext, db):
    db.set_subscription(message.from_user.id, True)
    await state.set_state(SubscribeState.first_name)
    await message.answer("Отлично! Давайте познакомимся 😊\n\nВведите ваше <b>имя</b>:")


@router.message(SubscribeState.first_name)
async def subscribe_first_name(message: Message, state: FSMContext):
    await state.update_data(first_name=message.text.strip())
    await state.set_state(SubscribeState.last_name)
    await message.answer("Введите вашу <b>фамилию</b>:")


@router.message(SubscribeState.last_name)
async def subscribe_last_name(message: Message, state: FSMContext):
    await state.update_data(last_name=message.text.strip())
    await state.set_state(SubscribeState.gender)
    gender_kb = ReplyKeyboardMarkup(
        keyboard=[[KB(text="👨 Мужской"), KB(text="👩 Женский")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("Укажите ваш <b>пол</b>:", reply_markup=gender_kb)


@router.message(SubscribeState.gender)
async def subscribe_gender(message: Message, state: FSMContext):
    await state.update_data(gender=message.text.strip())
    await state.set_state(SubscribeState.age)
    await message.answer("Сколько вам <b>лет</b>?")


@router.message(SubscribeState.age)
async def subscribe_age(message: Message, state: FSMContext):
    await state.update_data(age=message.text.strip())
    await state.set_state(SubscribeState.phone)
    await message.answer(
        "Введите ваш <b>номер телефона</b> в формате +998_________:\n"
        "Пример: <b>+998901234567</b>"
    )


@router.message(SubscribeState.phone)
async def subscribe_phone(message: Message, state: FSMContext, db):
    import re
    phone = message.text.strip().replace(" ", "").replace("-", "")
    if not re.match(r"^\+998\d{9}$", phone):
        await message.answer(
            "❌ Неверный формат. Введите номер в формате <b>+998XXXXXXXXX</b>:"
        )
        return
    data = await state.get_data()
    db.save_subscriber_profile(
        telegram_id=message.from_user.id,
        first_name=data["first_name"],
        last_name=data["last_name"],
        gender=data["gender"],
        age=data["age"],
        phone=phone,
    )
    await state.clear()
    await message.answer(
        "✅ <b>Спасибо за регистрацию в нашем боте!</b>\n\n"
        "Вы будете получать анонсы и новости Разумбоя! 🧠",
        reply_markup=main_menu()
    )
