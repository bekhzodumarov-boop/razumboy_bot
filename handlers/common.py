import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton as KB
from aiogram.fsm.context import FSMContext
from keyboards.reply import main_menu
from states import AskQuestionState, SubscribeState
from keyboards.inline import upcoming_event_kb

router = Router()

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


# ── /cancel — выход из любого FSM состояния ──────────────────
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, admin_ids: list[int]):
    current = await state.get_state()
    await state.clear()
    _is_admin = message.from_user.id in admin_ids
    if current:
        await message.answer("❌ Действие отменено. Возвращаемся в главное меню.", reply_markup=main_menu(_is_admin))
    else:
        await message.answer("Нечего отменять. Вы в главном меню.", reply_markup=main_menu(_is_admin))


# ── Пункт 11, 12: /start — подписка + список игр ─────────────
@router.message(Command("start"))
async def cmd_start(message: Message, db, admin_ids: list[int]):
    user = message.from_user
    db.upsert_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name,
        language_code=user.language_code,
        is_admin=user.id in admin_ids,
    )
    db.set_subscription(user.id, True)
    _is_admin = user.id in admin_ids

    # Deep link: /start event_42 — показать конкретную игру
    parts = message.text.split() if message.text else []
    if len(parts) > 1 and parts[1].startswith("event_"):
        try:
            event_id = int(parts[1].split("_")[1])
            event = db.get_event_by_id(event_id)
            if event:
                await message.answer(
                    "Добро пожаловать в бот Разумбой! 🧠",
                    reply_markup=main_menu(_is_admin),
                )
                text = format_event(event)
                if event["photo_file_id"]:
                    if len(text) <= 1024:
                        await message.answer_photo(
                            photo=event["photo_file_id"],
                            caption=text,
                            reply_markup=upcoming_event_kb(event["id"]),
                        )
                    else:
                        await message.answer_photo(photo=event["photo_file_id"])
                        await message.answer(text, reply_markup=upcoming_event_kb(event["id"]))
                else:
                    await message.answer(text, reply_markup=upcoming_event_kb(event["id"]))
                await _remind_profile_if_missing(message, db)
                return
        except Exception:
            pass  # некорректный deep link — продолжаем обычный /start

    await message.answer(
        "Добро пожаловать в бот Разумбой! 🧠\nВыберите действие в меню ниже.",
        reply_markup=main_menu(_is_admin),
    )

    events = db.get_open_events()
    if events:
        await _show_events_list(message, events)

    await _remind_profile_if_missing(message, db)


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
            await callback.message.answer_photo(photo=event["photo_file_id"])
            await callback.message.answer(text, reply_markup=upcoming_event_kb(event["id"]))
    else:
        await callback.message.answer(text, reply_markup=upcoming_event_kb(event["id"]))
    await callback.answer()


# ── Пункт 8: Фотографии с игр — список альбомов ──────────────
@router.message(F.text == "📸 Фотографии с игр")
async def photos(message: Message, db):
    albums = db.get_photo_albums()
    if not albums:
        await message.answer("📸 Фотографий пока нет. Скоро добавим! 🎉")
        return
    buttons = [[InlineKeyboardButton(text=f"📸 {a['title']}", url=a["url"])] for a in albums]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("📸 <b>Фотографии с наших игр:</b>\nВыберите игру:", reply_markup=kb)


# ── Пункт 9: Задать вопрос — FSM ─────────────────────────────
@router.message(F.text == "❓ Задать вопрос")
async def ask_question(message: Message, state: FSMContext):
    await state.set_state(AskQuestionState.waiting_question)
    await message.answer("Напишите ваш вопрос — организаторы увидят его и ответят. ✍️")


@router.message(AskQuestionState.waiting_question)
async def receive_question(message: Message, state: FSMContext, bot, admin_ids: list[int]):
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовый вопрос. ✍️")
        return
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
        reply_markup=main_menu(message.from_user.id in admin_ids)
    )


@router.message(F.text == "📤 Поделиться ботом")
async def share_bot(message: Message):
    share_url = (
        "https://t.me/share/url"
        "?url=https%3A%2F%2Ft.me%2FRazumboy_Bot"
        "&text=%F0%9F%A7%A0+%D0%A0%D0%B0%D0%B7%D1%83%D0%BC%D0%B1%D0%BE%D0%B9+%E2%80%94+"
        "%D0%BA%D0%B2%D0%B8%D0%B7+%D0%B2+%D0%A2%D0%B0%D1%88%D0%BA%D0%B5%D0%BD%D1%82%D0%B5%21+"
        "%D0%A0%D0%B5%D0%B3%D0%B8%D1%81%D1%82%D1%80%D0%B8%D1%80%D1%83%D0%B9%D1%81%D1%8F+%D0%BD%D0%B0+"
        "%D0%B8%D0%B3%D1%80%D1%83+%D0%B8+%D1%83%D1%87%D0%B0%D1%81%D1%82%D0%B2%D1%83%D0%B9+%D0%B2+"
        "%D0%B5%D0%B6%D0%B5%D0%B4%D0%BD%D0%B5%D0%B2%D0%BD%D0%BE%D0%BC+%D1%80%D0%BE%D0%B7%D1%8B%D0%B3%D1%80%D1%8B%D1%88%D0%B5%21"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📤 Поделиться с другом", url=share_url)
    ]])
    await message.answer(
        "Расскажи друзьям о Разумбое! 🧠\n\n"
        "Нажми кнопку ниже — и поделись ботом одним тапом 👇",
        reply_markup=kb
    )


@router.message(F.text == "🏠 Главное меню")
async def back_to_main(message: Message, db, admin_ids: list[int]):
    await message.answer("Главное меню:", reply_markup=main_menu(message.from_user.id in admin_ids))
    await _remind_profile_if_missing(message, db)


async def _remind_profile_if_missing(message: Message, db):
    """Напоминает заполнить анкету, если профиль ещё не заполнен."""
    profile = db.get_subscriber_profile(message.from_user.id)
    if not profile:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📝 Заполнить профиль", callback_data="fill_profile")
        ]])
        await message.answer(
            "👋 Кстати, вы ещё не заполнили профиль.\n"
            "Это займёт меньше минуты и поможет нам лучше вас знать! 😊",
            reply_markup=kb
        )


@router.callback_query(F.data == "fill_profile")
async def fill_profile_callback(callback: CallbackQuery, state: FSMContext, db):
    profile = db.get_subscriber_profile(callback.from_user.id)
    if profile:
        await callback.answer("Профиль уже заполнен ✅", show_alert=True)
        return
    await state.set_state(SubscribeState.first_name)
    await callback.message.answer("Отлично! Давайте познакомимся 😊\n\nВведите ваше <b>имя</b>:")
    await callback.answer()


# ── Подписка с анкетой ────────────────────────────────────────


@router.message(F.text == "📬 Получать анонсы")
async def subscribe_start(message: Message, state: FSMContext, db):
    db.set_subscription(message.from_user.id, True)
    profile = db.get_subscriber_profile(message.from_user.id)
    if profile:
        await message.answer("✅ Вы уже подписаны на анонсы Разумбоя! 🧠")
        return
    await state.set_state(SubscribeState.first_name)
    await message.answer("Отлично! Давайте познакомимся 😊\n\nВведите ваше <b>имя</b>:")


@router.message(SubscribeState.first_name)
async def subscribe_first_name(message: Message, state: FSMContext):
    await state.update_data(first_name=message.text.strip())
    await state.set_state(SubscribeState.phone)
    await message.answer(
        "Введите ваш <b>номер телефона</b>:\n"
        "Пример: <b>+998901234567</b>"
    )


@router.message(SubscribeState.phone)
async def subscribe_phone(message: Message, state: FSMContext, db, admin_ids: list[int]):
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
        last_name=None,
        gender=None,
        age=None,
        phone=phone,
    )
    await state.clear()
    await message.answer(
        "✅ <b>Готово! Добро пожаловать в клуб Разумбой!</b>\n\n"
        "Вы будете получать анонсы игр и участвовать в розыгрышах! 🧠🎉",
        reply_markup=main_menu(message.from_user.id in admin_ids)
    )
