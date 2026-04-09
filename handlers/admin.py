import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from keyboards.reply import admin_menu, broadcast_type_kb, events_list_kb
from states import AdminCreateEventState, AdminBroadcastState, AdminEditEventState, BlitzQuizState

router = Router()

DAYS_RU = {
    0: "понедельник", 1: "вторник", 2: "среду",
    3: "четверг", 4: "пятницу", 5: "субботу", 6: "воскресенье"
}

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
}


def is_admin(user_id: int, admin_ids: list[int]) -> bool:
    return user_id in admin_ids


def format_date_ru(date_str: str) -> str:
    """Преобразует 2026-04-10 → 10 апреля 2026 г., пятницу"""
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        day_name = DAYS_RU[dt.weekday()]
        month_name = MONTHS_RU[dt.month]
        return f"{dt.day} {month_name} {dt.year} г., {day_name}"
    except Exception:
        return date_str


# ── Клавиатуры быстрого выбора ────────────────────────────────

def time_choice_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="18:30"), KeyboardButton(text="19:00")],
            [KeyboardButton(text="19:30"), KeyboardButton(text="20:00")],
            [KeyboardButton(text="✏️ Другое время")],
        ],
        resize_keyboard=True, one_time_keyboard=True
    )


def price_choice_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="70 000 сум с игрока")],
            [KeyboardButton(text="80 000 сум с игрока")],
            [KeyboardButton(text="100 000 сум с игрока")],
            [KeyboardButton(text="✏️ Другая цена")],
        ],
        resize_keyboard=True, one_time_keyboard=True
    )


def location_choice_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="WOW BAR, ул. Матбуотчилар, 17")],
            [KeyboardButton(text="ПОНАЕХАЛИ рестопаб, ул. Матбуотчилар, 17")],
            [KeyboardButton(text="Greenwich Pub, ул. Абдурауф Фитрат, 159")],
            [KeyboardButton(text="✏️ Другое место")],
        ],
        resize_keyboard=True, one_time_keyboard=True
    )


# ── Админ-панель ──────────────────────────────────────────────

@router.message(F.text == "/admin")
async def admin_panel(message: Message, state: FSMContext, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        await message.answer("У вас нет доступа к админ-панели.")
        return
    await state.clear()
    await message.answer("Добро пожаловать в админ-панель Разумбоя.", reply_markup=admin_menu())


# ── Создание игры ─────────────────────────────────────────────

@router.message(F.text == "➕ Создать игру")
async def create_event_start(message: Message, state: FSMContext, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.set_state(AdminCreateEventState.title)
    await message.answer("Введите название игры:")


@router.message(AdminCreateEventState.title)
async def create_event_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AdminCreateEventState.description)
    await message.answer("Введите описание (можно длинное):")


@router.message(AdminCreateEventState.description)
async def create_event_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AdminCreateEventState.event_date)
    await message.answer(
        "Введите дату в формате YYYY-MM-DD\n"
        "Пример: <b>2026-04-10</b>\n\n"
        "Бот автоматически добавит день недели."
    )


@router.message(AdminCreateEventState.event_date)
async def create_event_date(message: Message, state: FSMContext):
    date_str = message.text.strip()
    date_ru = format_date_ru(date_str)
    await state.update_data(event_date=date_str)
    await state.set_state(AdminCreateEventState.event_time)
    await message.answer(
        f"📅 Дата: <b>{date_ru}</b>\n\nВыберите время или введите своё:",
        reply_markup=time_choice_kb()
    )


@router.message(AdminCreateEventState.event_time)
async def create_event_time(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "✏️ Другое время":
        await message.answer("Введите время в формате HH:MM (пример: 18:30):")
        return
    await state.update_data(event_time=text)
    await state.set_state(AdminCreateEventState.location)
    await message.answer("Выберите место проведения или введите своё:", reply_markup=location_choice_kb())


@router.message(AdminCreateEventState.location)
async def create_event_location(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "✏️ Другое место":
        await message.answer("Введите место проведения:")
        return
    await state.update_data(location=text)
    await state.set_state(AdminCreateEventState.location_url)
    await message.answer(
        "Введите ссылку на локацию в Яндекс.Картах.\n"
        "Если ссылки нет — напишите: -\n\n"
        "Пример: https://yandex.uz/maps/-/CPV6eOpR"
    )


@router.message(AdminCreateEventState.location_url)
async def create_event_location_url(message: Message, state: FSMContext):
    text = message.text.strip()
    location_url = None if text == "-" else text
    await state.update_data(location_url=location_url)
    await state.set_state(AdminCreateEventState.price_text)
    await message.answer("Выберите стоимость или введите свою:", reply_markup=price_choice_kb())


@router.message(AdminCreateEventState.price_text)
async def create_event_price(message: Message, state: FSMContext, db):
    text = message.text.strip()
    if text == "✏️ Другая цена":
        await message.answer("Введите стоимость (пример: 70 000 сум с игрока):")
        return
    await state.update_data(price_text=text)
    await state.set_state(AdminCreateEventState.photo)
    await message.answer(
        "Отправьте картинку для анонса.\n"
        "Если картинка не нужна — напишите: -"
    )


@router.message(AdminCreateEventState.photo)
async def create_event_photo(message: Message, state: FSMContext, db):
    photo_file_id = message.photo[-1].file_id if message.photo else None
    data = await state.get_data()
    event_id = db.create_event(
        title=data["title"],
        description=data["description"],
        event_date=data["event_date"],
        event_time=data["event_time"],
        location=data["location"],
        location_url=data.get("location_url"),
        price_text=data["price_text"],
        max_teams=None,
        photo_file_id=photo_file_id,
    )
    date_ru = format_date_ru(data["event_date"])
    await message.answer(
        f"✅ Игра создана!\n\n"
        f"📅 {date_ru}\n"
        f"🕒 {data['event_time']}\n"
        f"📍 {data['location']}\n"
        f"💰 {data['price_text']}",
        reply_markup=admin_menu()
    )
    await state.clear()


# ── Список игр ────────────────────────────────────────────────

@router.message(F.text == "📋 Список игр")
async def list_events(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    events = db.list_events()
    if not events:
        await message.answer("Список игр пуст.")
        return
    await message.answer("<b>Список игр:</b>\nНажмите на игру для редактирования:")
    for event in events:
        date_ru = format_date_ru(event["event_date"])
        text = (
            f"<b>{event['title']}</b>\n"
            f"📅 {date_ru}, {event['event_time']}\n"
            f"📍 {event['location']}\n"
            f"Статус: {event['status']}"
        )
        edit_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_event_{event['id']}")]
        ])
        await message.answer(text, reply_markup=edit_kb)


@router.callback_query(F.data.startswith("edit_event_"))
async def edit_event_choose_field(callback: CallbackQuery, state: FSMContext, db):
    event_id = int(callback.data.split("_")[-1])
    event = db.get_event_by_id(event_id)
    if not event:
        await callback.answer("Игра не найдена.")
        return
    await state.update_data(edit_event_id=event_id)
    await state.set_state(AdminEditEventState.choose_field)

    fields_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Название", callback_data="edit_field_title")],
        [InlineKeyboardButton(text="📄 Описание", callback_data="edit_field_description")],
        [InlineKeyboardButton(text="📅 Дата", callback_data="edit_field_event_date")],
        [InlineKeyboardButton(text="⏰ Время", callback_data="edit_field_event_time")],
        [InlineKeyboardButton(text="📍 Место", callback_data="edit_field_location")],
        [InlineKeyboardButton(text="🔗 Ссылка на карту", callback_data="edit_field_location_url")],
        [InlineKeyboardButton(text="💰 Цена", callback_data="edit_field_price_text")],
    ])
    await callback.message.answer(
        f"Редактирование игры <b>{event['title']}</b>\nЧто хотите изменить?",
        reply_markup=fields_kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field_"), AdminEditEventState.choose_field)
async def edit_event_enter_value(callback: CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_field_", "")
    field_names = {
        "title": "название",
        "description": "описание",
        "event_date": "дату (формат YYYY-MM-DD, пример: 2026-05-10)",
        "event_time": "время (формат HH:MM, пример: 19:00)",
        "location": "место проведения",
        "location_url": "ссылку на карту (или - если убрать)",
        "price_text": "стоимость",
    }
    await state.update_data(edit_field=field)
    await state.set_state(AdminEditEventState.enter_value)
    await callback.message.answer(f"Введите новое {field_names.get(field, field)}:")
    await callback.answer()


@router.message(AdminEditEventState.enter_value)
async def edit_event_save(message: Message, state: FSMContext, db):
    data = await state.get_data()
    event_id = data["edit_event_id"]
    field = data["edit_field"]
    value = message.text.strip()
    if field == "location_url" and value == "-":
        value = None
    db.update_event_field(event_id, field, value)
    event = db.get_event_by_id(event_id)
    await state.clear()
    await message.answer(
        f"✅ Поле обновлено!\n\n"
        f"<b>{event['title']}</b>\n"
        f"📅 {format_date_ru(event['event_date'])}, {event['event_time']}\n"
        f"📍 {event['location']}",
        reply_markup=admin_menu()
    )


# ── Заявки ────────────────────────────────────────────────────

@router.message(F.text == "📥 Заявки")
async def registrations_prompt(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    events = db.get_open_events()
    if not events:
        await message.answer("Нет активных игр.")
        return
    buttons = []
    for event in events:
        date_ru = format_date_ru(event["event_date"])
        buttons.append([InlineKeyboardButton(
            text=f"📅 {event['title']} ({date_ru[:event['event_date'].rfind('.') if '.' in event['event_date'] else len(date_ru)]})",
            callback_data=f"view_regs_{event['id']}"
        )])
    # Упрощённый вариант кнопок
    buttons2 = []
    for event in events:
        buttons2.append([InlineKeyboardButton(
            text=f"📋 {event['title']} — {event['event_date']}",
            callback_data=f"view_regs_{event['id']}"
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons2)
    await message.answer("Выберите игру для просмотра заявок:", reply_markup=kb)


@router.callback_query(F.data.startswith("view_regs_"))
async def view_registrations(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    event_id = int(callback.data.split("_")[-1])
    event = db.get_event_by_id(event_id)
    if not event:
        await callback.message.answer("Игра не найдена.")
        await callback.answer()
        return
    registrations = db.get_registrations_for_event(event_id)
    date_ru = format_date_ru(event["event_date"])
    if not registrations:
        await callback.message.answer(f"Заявок на «{event['title']}» ({date_ru}) пока нет.")
        await callback.answer()
        return
    lines = [f"<b>Заявки на {event['title']}</b>\n📅 {date_ru}:\n"]
    for i, r in enumerate(registrations, 1):
        lines.append(
            f"{i}. <b>{r['team_name']}</b>\n"
            f"   Игроков: {r['team_size']} | Капитан: {r['captain_name']}\n"
            f"   Телефон: {r['phone']}\n"
            f"   Комментарий: {r['comment'] or 'нет'}\n"
        )
    await callback.message.answer("\n".join(lines))
    await callback.answer()


# ── Экспорт в Excel ───────────────────────────────────────────

@router.message(F.text == "📊 Экспорт в Excel")
async def export_excel(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    event = db.get_upcoming_event()
    if not event:
        await message.answer("Нет открытой игры для экспорта.")
        return
    rows = db.get_registrations_with_confirmations(event["id"])
    if not rows:
        await message.answer("Заявок пока нет.")
        return

    lines = ["№,Название команды,Кол-во зарегистрировавшихся,Кол-во подтвердивших,Имена подтвердивших,Капитан,Телефон"]
    for i, r in enumerate(rows, 1):
        confirmed = str(r["confirmed_count"]) if r["confirmed_count"] is not None else ""
        names = (r["player_names"] or "").replace(",", ";")
        lines.append(
            f"{i},"
            f"\"{r['team_name']}\","
            f"{r['team_size']},"
            f"{confirmed},"
            f"\"{names}\","
            f"\"{r['captain_name']}\","
            f"{r['phone']}"
        )

    csv_content = "\n".join(lines).encode("utf-8-sig")
    filename = f"registrations_{event['event_date']}_{event['title'][:20]}.csv".replace(" ", "_")
    await message.answer_document(
        document=BufferedInputFile(csv_content, filename=filename),
        caption=f"📊 Заявки на «{event['title']}» — {len(rows)} команд"
    )


# ── Рассылка ──────────────────────────────────────────────────

@router.message(F.text == "📨 Рассылка")
async def broadcast_menu(message: Message, state: FSMContext, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.set_state(AdminBroadcastState.choose_type)
    await message.answer("Выберите тип рассылки:", reply_markup=broadcast_type_kb())


@router.callback_query(F.data == "broadcast_event")
async def broadcast_choose_event(callback: CallbackQuery, state: FSMContext, db):
    events = db.get_open_events()
    if not events:
        await callback.message.answer("Нет активных игр.")
        await state.clear()
        await callback.answer()
        return
    await state.set_state(AdminBroadcastState.choose_event)
    await callback.message.answer("Выберите игру:", reply_markup=events_list_kb(events, "broadcast_event"))
    await callback.answer()


@router.callback_query(F.data.startswith("broadcast_event_"))
async def broadcast_send_event(callback: CallbackQuery, state: FSMContext, db, bot):
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer()
        return
    event_id = int(parts[-1])
    event = db.get_event_by_id(event_id)
    if not event:
        await callback.message.answer("Игра не найдена.")
        await state.clear()
        await callback.answer()
        return

    from handlers.common import format_event
    text = format_event(event)
    await _do_broadcast(callback.message, db, bot, event, text)
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "broadcast_reminder")
async def broadcast_reminder_choose(callback: CallbackQuery, state: FSMContext, db):
    events = db.get_open_events()
    if not events:
        await callback.message.answer("Нет активных игр.")
        await state.clear()
        await callback.answer()
        return
    await state.set_state(AdminBroadcastState.choose_event)
    await callback.message.answer(
        "Выберите игру для напоминания за день до:",
        reply_markup=events_list_kb(events, "reminder")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("reminder_"))
async def broadcast_send_reminder(callback: CallbackQuery, state: FSMContext, db, bot):
    event_id = int(callback.data.split("_")[-1])
    event = db.get_event_by_id(event_id)
    if not event:
        await callback.message.answer("Игра не найдена.")
        await state.clear()
        await callback.answer()
        return

    try:
        event_dt = datetime.datetime.strptime(event["event_date"], "%Y-%m-%d")
        day_name = DAYS_RU[event_dt.weekday()]
    except Exception:
        day_name = event["event_date"]

    # Пункт 2: добавить локацию со ссылкой если есть
    location_line = f"🏡 {event['location']}"
    if event.get("location_url"):
        location_line += f"\n📍 {event['location_url']}"

    text = (
        f"😎 Добрый день!\n\n"
        f"😄 Напоминаю, что уже завтра (в {day_name}) состоится <b>{event['title']}</b>, "
        f"и у вас есть шанс к нам присоединиться.\n\n"
        f"🤪 Интересные вопросы, безудержное веселье и отличную атмосферу мы вам гарантируем!\n\n"
        f"В этот раз играем тут:\n"
        f"{location_line}\n\n"
        f"📞 Дополнительные заявки на игру принимаются до 16:00 завтрашнего дня.\n\n"
        f"✍️ Для регистрации напишите в телеграм-бот @razumboy количество игроков и название команды.\n\n"
        f"😎 До встречи!\n\n"
        f"🌐 www.razumboy.uz\n"
        f"☎️ +998998355500\n\n"
        f"🕊 <a href='https://t.me/VoyRazumboy'>Telegram</a> | "
        f"📱 <a href='https://www.instagram.com/voyrazumboy/'>Instagram</a> | "
        f"📺 <a href='https://www.youtube.com/@VoyRazumboy'>YouTube</a> | "
        f"📱 <a href='https://www.facebook.com/razumboy.tashkent'>Facebook</a>"
    )
    await _do_broadcast(callback.message, db, bot, event, text)
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "broadcast_dayof")
async def broadcast_dayof_choose(callback: CallbackQuery, state: FSMContext, db):
    events = db.get_open_events()
    if not events:
        await callback.message.answer("Нет активных игр.")
        await state.clear()
        await callback.answer()
        return
    await state.set_state(AdminBroadcastState.choose_event)
    await callback.message.answer(
        "Выберите игру для рассылки участникам в день игры:",
        reply_markup=events_list_kb(events, "dayof")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dayof_"))
async def broadcast_send_dayof(callback: CallbackQuery, state: FSMContext, db, bot):
    event_id = int(callback.data.split("_")[-1])
    event = db.get_event_by_id(event_id)
    if not event:
        await callback.message.answer("Игра не найдена.")
        await state.clear()
        await callback.answer()
        return

    registrations = db.get_registrations_for_event(event_id)
    if not registrations:
        await callback.message.answer("На эту игру нет зарегистрированных.")
        await state.clear()
        await callback.answer()
        return

    sent_count = 0
    for reg in registrations:
        # Пункт 7: добавить локацию со ссылкой если есть
        location_line = f"📍 {event['location']}"
        if event.get("location_url"):
            location_line += f"\n🗺 {event['location_url']}"

        text = (
            f"❤️ Добрый день!\n\n"
            f"😍 Напоминаю, что сегодня вечером состоится игра <b>{event['title']}</b>\n\n"
            f"📞 Вы зарегистрировали <b>{reg['team_size']}</b> игроков.\n\n"
            f"✍️ Прошу опросить вашу команду и подтвердить точное кол-во игроков, кто придет с вашей стороны.\n\n"
            f"👨‍💻 Если кто-либо из зарегистрировавшихся не сможет прийти, дайте знать заранее. "
            f"Этим самым вы дадите возможность прийти тем, кто в резерве.\n\n"
            f"💃 До встречи вечером!\n\n"
            f"PS. Кстати, сегодня играем тут:\n"
            f"{location_line}\n\n"
            f"<i>Нажмите кнопку ниже, чтобы подтвердить участие.</i>"
        )
        try:
            await bot.send_message(
                reg["telegram_id"],
                text,
                reply_markup=_reply_confirm_kb(reg["id"])
            )
            sent_count += 1
        except Exception:
            pass

    await callback.message.answer(f"✅ Рассылка в день игры завершена. Отправлено: {sent_count} участникам.")
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "broadcast_custom")
async def broadcast_custom_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminBroadcastState.custom_text)
    await callback.message.answer("Напишите текст поста для рассылки:")
    await callback.answer()


@router.message(AdminBroadcastState.custom_text)
async def broadcast_custom_text(message: Message, state: FSMContext):
    await state.update_data(custom_text=message.text.strip())
    await state.set_state(AdminBroadcastState.custom_photo)
    await message.answer("Прикрепите картинку или напишите '-' если без картинки:")


@router.message(AdminBroadcastState.custom_photo)
async def broadcast_custom_send(message: Message, state: FSMContext, db, bot):
    data = await state.get_data()
    text = data["custom_text"]
    photo_file_id = message.photo[-1].file_id if message.photo else None

    subscribers = db.get_subscribers()
    sent_count = 0
    for user in subscribers:
        try:
            if photo_file_id:
                await bot.send_photo(user["telegram_id"], photo=photo_file_id, caption=text)
            else:
                await bot.send_message(user["telegram_id"], text)
            sent_count += 1
        except Exception:
            pass

    db.save_broadcast(None, text, sent_count)
    await message.answer(f"✅ Рассылка завершена. Отправлено: {sent_count}", reply_markup=admin_menu())
    await state.clear()


# ── Вспомогательные функции ───────────────────────────────────

async def _do_broadcast(message, db, bot, event, text):
    subscribers = db.get_subscribers()
    sent_count = 0
    errors = []
    for user in subscribers:
        try:
            if event["photo_file_id"]:
                # Telegram ограничивает caption до 1024 символов
                # Если текст длиннее — отправляем фото отдельно, текст отдельно
                if len(text) <= 1024:
                    await bot.send_photo(user["telegram_id"], photo=event["photo_file_id"], caption=text)
                else:
                    await bot.send_photo(user["telegram_id"], photo=event["photo_file_id"])
                    await bot.send_message(user["telegram_id"], text)
            else:
                await bot.send_message(user["telegram_id"], text)
            sent_count += 1
        except Exception as e:
            errors.append(f"{user['telegram_id']}: {e}")
    db.save_broadcast(event["id"], text, sent_count)
    result = f"✅ Рассылка завершена. Отправлено: {sent_count} из {len(subscribers)}"
    if errors:
        result += f"\n\n⚠️ Ошибки ({len(errors)}):\n" + "\n".join(errors[:5])
    await message.answer(result, reply_markup=admin_menu())


def _reply_confirm_kb(registration_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Подтвердить участие",
            callback_data=f"confirm_players_{registration_id}"
        )]
    ])


# ── Подписчики ────────────────────────────────────────────────

@router.message(F.text == "👥 Подписчики")
async def show_subscribers(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()

    count = db.get_subscribers_count()
    subscribers = db.get_all_subscribers()

    if not subscribers:
        await message.answer("Подписчиков пока нет.")
        return

    # Разбиваем на части по 30 человек — чтобы не превышать лимит Telegram
    header = f"👥 <b>Подписчики: {count} чел.</b>\n\n"
    lines = []
    for i, user in enumerate(subscribers, 1):
        if user["username"]:
            link = f'<a href="tg://resolve?domain={user["username"]}">@{user["username"]}</a>'
        else:
            link = f'<a href="tg://user?id={user["telegram_id"]}">{user["full_name"] or "Без имени"}</a>'
        lines.append(f"{i}. {link}")

    # Отправляем по частям если список большой
    chunk_size = 30
    for start in range(0, len(lines), chunk_size):
        chunk = lines[start:start + chunk_size]
        text = (header if start == 0 else "") + "\n".join(chunk)
        await message.answer(text)


# ── Предыдущие рассылки ───────────────────────────────────────

@router.message(F.text == "📬 История рассылок")
async def show_broadcasts(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()

    broadcasts = db.get_broadcasts(limit=10)
    if not broadcasts:
        await message.answer("Рассылок пока не было.")
        return

    lines = [f"📬 <b>Последние рассылки ({len(broadcasts)}):</b>\n"]
    for i, b in enumerate(broadcasts, 1):
        event_name = b["event_title"] or "Свой пост"
        # Обрезаем текст до 100 символов для превью
        preview = b["message_text"][:100].replace("\n", " ")
        if len(b["message_text"]) > 100:
            preview += "..."
        sent_at = b["sent_at"][:16].replace("T", " ")  # убираем секунды
        lines.append(
            f"\n{i}. <b>{event_name}</b>\n"
            f"   📅 {sent_at} | 📨 Отправлено: {b['sent_count']} чел.\n"
            f"   <i>{preview}</i>"
        )

    await message.answer("\n".join(lines))


# ── Отмена игры ───────────────────────────────────────────────

@router.message(F.text == "❌ Отменить игру")
async def cancel_event_start(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    events = db.get_open_events()
    if not events:
        await message.answer("Нет активных игр для отмены.")
        return
    await state.set_state(AdminBroadcastState.choose_event)
    await message.answer(
        "Выберите игру для отмены:",
        reply_markup=events_list_kb(events, "cancel_event")
    )


@router.callback_query(F.data.startswith("cancel_event_"))
async def cancel_event_confirm(callback: CallbackQuery, state: FSMContext, db):
    event_id = int(callback.data.split("_")[-1])
    event = db.get_event_by_id(event_id)
    if not event:
        await callback.message.answer("Игра не найдена.")
        await state.clear()
        await callback.answer()
        return

    date_ru = format_date_ru(event["event_date"])

    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"cancel_confirm_{event_id}"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="cancel_abort"),
        ]
    ])
    await callback.message.answer(
        f"⚠️ Вы уверены, что хотите отменить игру?\n\n"
        f"<b>{event['title']}</b>\n"
        f"📅 {date_ru}, {event['event_time']}\n\n"
        f"Всем зарегистрированным командам будет отправлено уведомление об отмене.",
        reply_markup=confirm_kb
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_abort")
async def cancel_event_abort(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отмена игры прервана.", reply_markup=admin_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_confirm_"))
async def cancel_event_do(callback: CallbackQuery, state: FSMContext, db, bot):
    event_id = int(callback.data.split("_")[-1])
    event = db.get_event_by_id(event_id)
    if not event:
        await callback.message.answer("Игра не найдена.")
        await state.clear()
        await callback.answer()
        return

    date_ru = format_date_ru(event["event_date"])

    # Отменяем игру в БД
    db.cancel_event(event_id)

    # Получаем всех зарегистрированных
    registrations = db.get_registrations_for_event(event_id)

    cancel_text = (
        f"Дорогие капитаны,\n\n"
        f"Мы очень старались организовать незабываемый вечер вместе с вами, "
        f"но обстоятельства сложились таким образом, что мы вынуждены отменить игру "
        f"«<b>{event['title']}</b>» {date_ru}.\n\n"
        f"Просьба сообщить об этом игрокам вашей команды.\n\n"
        f"Приносим извинения за причинённые неудобства и надеемся на ваше понимание."
    )

    sent_count = 0
    for reg in registrations:
        try:
            await bot.send_message(reg["telegram_id"], cancel_text)
            sent_count += 1
        except Exception:
            pass

    await callback.message.answer(
        f"✅ Игра «{event['title']}» отменена.\n"
        f"Уведомление отправлено {sent_count} капитанам.",
        reply_markup=admin_menu()
    )
    await state.clear()
    await callback.answer()


# ── Рандомбой ─────────────────────────────────────────────────

# Хранилище участников рандомбоя (в памяти)
_randoboy_active = False
_randoboy_participants = {}  # {telegram_id: full_name}


@router.message(F.text == "🎲 Рандомбой")
async def randoboy_menu(message: Message, state: FSMContext, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    global _randoboy_active, _randoboy_participants
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Пуск Рандомбой", callback_data="randoboy_start")],
        [InlineKeyboardButton(text="📋 Список участников", callback_data="randoboy_list")],
        [InlineKeyboardButton(text="🏆 Определить победителя", callback_data="randoboy_winner")],
        [InlineKeyboardButton(text="🔄 Сбросить", callback_data="randoboy_reset")],
    ])
    status = f"✅ Активен | Участников: {len(_randoboy_participants)}" if _randoboy_active else "⛔️ Не запущен"
    await message.answer(
        f"🎲 <b>Рандомбой</b>\n\nСтатус: {status}",
        reply_markup=kb
    )


@router.callback_query(F.data == "randoboy_list")
async def randoboy_list(callback: CallbackQuery, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    global _randoboy_participants
    if not _randoboy_participants:
        await callback.message.answer("Участников пока нет.")
        await callback.answer()
        return
    lines = [f"📋 <b>Участники Рандомбой ({len(_randoboy_participants)}):</b>\n"]
    for i, (uid, name) in enumerate(_randoboy_participants.items(), 1):
        username_part = f" (@{uid})" 
        lines.append(f"{i}. {name}{username_part}")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data == "randoboy_start")
async def randoboy_start(callback: CallbackQuery, db, bot, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    global _randoboy_active, _randoboy_participants
    _randoboy_active = True
    _randoboy_participants = {}

    # Рассылаем всем подписчикам кнопку участия
    subscribers = db.get_subscribers()
    join_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Участвовать в Рандомбой!", callback_data="randoboy_join")]
    ])
    sent = 0
    for user in subscribers:
        try:
            await bot.send_message(
                user["telegram_id"],
                "🎲 <b>Рандомбой запущен!</b>\n\n"
                "Нажмите кнопку ниже, чтобы принять участие!",
                reply_markup=join_kb
            )
            sent += 1
        except Exception:
            pass

    await callback.message.answer(f"✅ Рандомбой запущен! Сообщение отправлено {sent} подписчикам.", reply_markup=admin_menu())
    await callback.answer()


@router.callback_query(F.data == "randoboy_winner")
async def randoboy_pick_winner(callback: CallbackQuery, db, bot, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    global _randoboy_participants
    if not _randoboy_participants:
        await callback.message.answer("❌ Нет участников.")
        await callback.answer()
        return
    import random
    winner_id, winner_name = random.choice(list(_randoboy_participants.items()))
    # Убираем победителя из списка чтобы не выбрать повторно
    del _randoboy_participants[winner_id]

    # Получаем username победителя если есть
    winner_user = db.get_user_by_telegram_id(winner_id)
    if winner_user and winner_user["username"]:
        winner_mention = f"@{winner_user['username']}"
    else:
        winner_mention = f"<a href=\'tg://user?id={winner_id}\'>{winner_name}</a>"

    broadcast_text = (
        f"🎲 <b>Рандомбой совершенно случайно и неумышленно выбрал {winner_mention}!</b>\n\n"
        f"🏆 Поздравляем!"
    )

    # Отправляем всем подписчикам
    subscribers = db.get_subscribers()
    for user in subscribers:
        try:
            await bot.send_message(user["telegram_id"], broadcast_text)
        except Exception:
            pass

    await callback.message.answer(
        f"✅ Победитель определён и объявлен!\n"
        f"👤 {winner_name} (ID: {winner_id})\n"
        f"Осталось участников: {len(_randoboy_participants)}"
    )
    await callback.answer()


@router.callback_query(F.data == "randoboy_reset")
async def randoboy_reset(callback: CallbackQuery, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    global _randoboy_active, _randoboy_participants
    _randoboy_active = False
    _randoboy_participants = {}
    await callback.message.answer("🔄 Рандомбой сброшен.")
    await callback.answer()


@router.callback_query(F.data == "randoboy_join")
async def randoboy_join(callback: CallbackQuery):
    global _randoboy_active, _randoboy_participants
    if not _randoboy_active:
        await callback.answer("Рандомбой уже завершён.", show_alert=True)
        return
    user_id = callback.from_user.id
    if user_id in _randoboy_participants:
        await callback.answer("Вы уже зарегистрированы!", show_alert=True)
        return
    _randoboy_participants[user_id] = callback.from_user.full_name
    await callback.answer("✅ Ваша заявка принята!", show_alert=True)


# ── Блиц-квиз ─────────────────────────────────────────────────

# Хранилище блиц-квиза (в памяти)
_blitz_active = False
_blitz_question = ""
_blitz_answer = ""
_blitz_mode = "first"  # 'first' или 'all'
_blitz_duration = 60
_blitz_winners = []
_blitz_end_time = None


@router.message(F.text == "⚡️ Блиц-квиз")
async def blitz_menu(message: Message, state: FSMContext, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    from states import BlitzQuizState
    await state.set_state(BlitzQuizState.question)
    await message.answer(
        "⚡️ <b>Блиц-квиз</b>\n\n"
        "Введите вопрос для участников:"
    )


@router.message(BlitzQuizState.question)
async def blitz_set_question(message: Message, state: FSMContext):
    from states import BlitzQuizState
    await state.update_data(blitz_question=message.text.strip())
    await state.set_state(BlitzQuizState.photo)
    await message.answer("Прикрепите фото к вопросу или напишите <b>-</b> если без фото:")


@router.message(BlitzQuizState.photo)
async def blitz_set_photo(message: Message, state: FSMContext):
    from states import BlitzQuizState
    photo_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(blitz_photo=photo_id)
    await state.set_state(BlitzQuizState.answer)
    await message.answer("Введите правильный ответ:")


@router.message(BlitzQuizState.answer)
async def blitz_set_answer(message: Message, state: FSMContext):
    from states import BlitzQuizState
    await state.update_data(blitz_answer=message.text.strip().lower())
    await state.set_state(BlitzQuizState.duration)
    await message.answer("Введите время на ответ в секундах (например: 60):")


@router.message(BlitzQuizState.duration)
async def blitz_set_duration(message: Message, state: FSMContext):
    from states import BlitzQuizState
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Введите число секунд:")
        return
    await state.update_data(blitz_duration=int(text))
    await state.set_state(BlitzQuizState.mode)
    mode_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥇 Первый правильный ответ", callback_data="blitz_mode_first")],
        [InlineKeyboardButton(text="👥 Все правильно ответившие", callback_data="blitz_mode_all")],
    ])
    await message.answer("Выберите режим победителей:", reply_markup=mode_kb)


@router.callback_query(F.data.startswith("blitz_mode_"), BlitzQuizState.mode)
async def blitz_set_mode(callback: CallbackQuery, state: FSMContext, db, bot, admin_ids: list[int]):
    import asyncio, datetime
    global _blitz_active, _blitz_question, _blitz_answer, _blitz_mode
    global _blitz_duration, _blitz_winners, _blitz_end_time

    mode = callback.data.replace("blitz_mode_", "")
    data = await state.get_data()
    await state.clear()

    _blitz_active = True
    _blitz_question = data["blitz_question"]
    _blitz_answer = data["blitz_answer"]
    _blitz_mode = mode
    _blitz_duration = data["blitz_duration"]
    _blitz_winners = []
    _blitz_end_time = datetime.datetime.now() + datetime.timedelta(seconds=_blitz_duration)

    # Рассылаем вопрос всем подписчикам
    subscribers = db.get_subscribers()
    photo_id = data.get("blitz_photo")
    question_text = (
        f"⚡️ <b>БЛИЦ-КВИЗ!</b>\n\n"
        f"❓ {_blitz_question}\n\n"
        f"⏱ Время на ответ: {_blitz_duration} секунд\n"
        f"Напишите ответ прямо в этот чат!"
    )
    sent = 0
    for user in subscribers:
        try:
            if photo_id:
                await bot.send_photo(user["telegram_id"], photo=photo_id, caption=question_text)
            else:
                await bot.send_message(user["telegram_id"], question_text)
            sent += 1
        except Exception:
            pass

    mode_text = "первый правильный ответ" if mode == "first" else "все правильные ответы"
    await callback.message.answer(
        f"✅ Блиц-квиз запущен!\n"
        f"Вопрос отправлен {sent} подписчикам.\n"
        f"Режим: {mode_text}\n"
        f"Время: {_blitz_duration} сек.\n\n"
        f"Через {_blitz_duration} секунд используйте кнопку <b>⚡️ Блиц-квиз</b> → чтобы завершить и увидеть победителей.",
        reply_markup=admin_menu()
    )
    await callback.answer()

    # Автоматически завершаем квиз через N секунд
    async def finish_blitz():
        await asyncio.sleep(_blitz_duration)
        global _blitz_active
        _blitz_active = False
        if _blitz_winners:
            lines = ["⚡️ <b>Блиц-квиз завершён!</b>\n\n🏆 Победители:"]
            for i, (uid, name, username, ans) in enumerate(_blitz_winners, 1):
                mention = f"@{username}" if username else f"tg://user?id={uid}"
                lines.append(f"{i}. {name} ({mention}) — «{ans}»")
            lines.append("\n🎉 Поздравляем!")
            result_text = "\n".join(lines)
        else:
            result_text = "⚡️ Блиц-квиз завершён. Правильных ответов не было."
        # Отправляем всем подписчикам
        subscribers_list = db.get_subscribers()
        for user in subscribers_list:
            try:
                await bot.send_message(user["telegram_id"], result_text)
            except Exception:
                pass

    asyncio.create_task(finish_blitz())


@router.message(F.text & ~F.text.startswith("/"))
async def blitz_catch_answer(message: Message, bot, db, admin_ids: list[int]):
    """Перехватываем ответы на блиц-квиз"""
    global _blitz_active, _blitz_answer, _blitz_mode, _blitz_winners
    import datetime
    if not _blitz_active:
        return
    if _blitz_end_time and datetime.datetime.now() > _blitz_end_time:
        return

    user_answer = message.text.strip().lower()
    user_id = message.from_user.id
    user_name = message.from_user.full_name

    # Проверяем не отвечал ли уже
    already_answered = any(w[0] == user_id for w in _blitz_winners)
    if already_answered:
        return

    if user_answer == _blitz_answer:
        username = message.from_user.username
        _blitz_winners.append((user_id, user_name, username, message.text.strip()))
        await message.answer("✅ Правильно! Ваш ответ засчитан!")

        if _blitz_mode == "first":
            # Останавливаем квиз
            _blitz_active = False
            mention = f"@{username}" if username else f"tg://user?id={user_id}"
            result_text = (
                f"⚡️ <b>Блиц-квиз завершён!</b>\n\n"
                f"🏆 Победители:\n"
                f"1. {user_name} ({mention}) — «{message.text.strip()}»\n\n"
                f"🎉 Поздравляем!"
            )
            # Отправляем всем подписчикам
            subscribers_list = db.get_subscribers()
            for sub in subscribers_list:
                try:
                    await bot.send_message(sub["telegram_id"], result_text)
                except Exception:
                    pass


# ── База подписчиков (экспорт) ────────────────────────────────

@router.message(F.text == "📥 База подписчиков")
async def export_subscribers(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    profiles = db.get_all_subscriber_profiles()
    if not profiles:
        await message.answer("База подписчиков пуста.")
        return

    lines = ["№,Имя,Фамилия,Пол,Возраст,Телефон,Username,Telegram ID,Дата регистрации"]
    for i, p in enumerate(profiles, 1):
        username = f"@{p['username']}" if p.get('username') else ""
        lines.append(
            f"{i},"
            f"\"{p['first_name'] or ''}\","
            f"\"{p['last_name'] or ''}\","
            f"\"{p['gender'] or ''}\","
            f"\"{p['age'] or ''}\","
            f"{p['phone'] or ''},"
            f"{username},"
            f"{p['telegram_id']},"
            f"{p['created_at'][:10]}"
        )

    csv_content = "\n".join(lines).encode("utf-8-sig")
    filename = "subscribers_profile.csv"
    await message.answer_document(
        document=BufferedInputFile(csv_content, filename=filename),
        caption=f"📥 База подписчиков — {len(profiles)} чел."
    )
