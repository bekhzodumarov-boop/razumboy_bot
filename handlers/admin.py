import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from keyboards.reply import admin_menu, broadcast_type_kb, events_list_kb
from states import AdminCreateEventState, AdminBroadcastState, AdminEditEventState, BlitzQuizState, AdminPhotoAlbumState, AdminGiveawayState, AdminWinnersBroadcastState, AdminBroadcastTemplateState, AdminReferralCheckState

router = Router()

DAYS_RU = {
    0: "понедельник", 1: "вторник", 2: "среда",
    3: "четверг", 4: "пятница", 5: "суббота", 6: "воскресенье"
}
# Предложный падеж для конструкции «завтра (в ...)»
DAYS_RU_PREP = {
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
    """Преобразует 2026-04-10 → 10 апреля 2026 г. (пятница)"""
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        day_name = DAYS_RU[dt.weekday()]
        month_name = MONTHS_RU[dt.month]
        return f"{dt.day} {month_name} {dt.year} г. ({day_name})"
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


@router.message(F.text == "⚙️ Панель администратора")
async def admin_panel_button(message: Message, state: FSMContext, admin_ids: list[int]):
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
    try:
        datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты.\n\n"
            "Введите дату в формате <b>YYYY-MM-DD</b>\n"
            "Пример: <b>2026-05-10</b>"
        )
        return
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
        buttons.append([InlineKeyboardButton(
            text=f"📋 {event['title']} — {event['event_date']}",
            callback_data=f"view_regs_{event['id']}"
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
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

    registrations = db.get_registrations_for_event_full(event_id)
    date_ru = format_date_ru(event["event_date"])

    if not registrations:
        await callback.message.answer(f"Заявок на «{event['title']}» ({date_ru}) пока нет.")
        await callback.answer()
        return

    active = [r for r in registrations if r["status"] == "confirmed"]
    cancelled = [r for r in registrations if r["status"] == "cancelled"]

    lines = [f"<b>Заявки на «{event['title']}»</b>\n📅 {date_ru}:\n"]

    total_players = 0
    for i, r in enumerate(active, 1):
        if r["confirmed_count"] is not None:
            icon = "✅"
            count = r["confirmed_count"]
        else:
            icon = "⏳"
            count = r["team_size"]
        total_players += count
        lines.append(f"{icon}{i}. {r['team_name']} {count} {r['captain_name']} {r['phone']}")

    lines.append(f"\n<b>Итого: {total_players}</b>")

    if cancelled:
        lines.append("\n<b>Отменили регистрацию:</b>")
        for i, r in enumerate(cancelled, 1):
            lines.append(f"{i}. {r['team_name']} {r['team_size']} {r['captain_name']} {r['phone']}")

    await callback.message.answer("\n".join(lines))

    # Кнопки отмены для активных команд
    if active:
        cancel_buttons = []
        for r in active:
            cancel_buttons.append([InlineKeyboardButton(
                text=f"🗑 Отменить: {r['team_name']}",
                callback_data=f"admin_pre_cancel_{r['id']}"
            )])
        kb = InlineKeyboardMarkup(inline_keyboard=cancel_buttons)
        await callback.message.answer("Отменить регистрацию команды:", reply_markup=kb)

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
        day_name = DAYS_RU_PREP[event_dt.weekday()]
    except Exception:
        day_name = event["event_date"]

    # Пункт 2: добавить локацию со ссылкой если есть
    location_line = f"🏡 {event['location']}"
    if event["location_url"]:
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
        if event["location_url"]:
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
    if not message.text:
        await message.answer("Пожалуйста, отправьте текст поста. ✍️")
        return
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

    db.save_broadcast(None, text, sent_count, broadcast_type="manual", recipients_info="Все подписчики")
    await message.answer(f"✅ Рассылка завершена. Отправлено: {sent_count}", reply_markup=admin_menu())
    await state.clear()


# ── Отмена регистрации команды (admin) ───────────────────────

@router.callback_query(F.data.startswith("admin_pre_cancel_"))
async def admin_pre_cancel(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    registration_id = int(callback.data.split("_")[-1])
    reg = db.get_registration_by_id(registration_id)
    if not reg:
        await callback.answer("Регистрация не найдена.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Да, отменить",
            callback_data=f"admin_do_cancel_{registration_id}"
        )],
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="admin_cancel_dismiss"
        )],
    ])
    await callback.message.answer(
        f"Отменить регистрацию команды <b>{reg['team_name']}</b> "
        f"({reg['team_size']} чел., {reg['captain_name']})?",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cancel_dismiss")
async def admin_cancel_dismiss(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data.startswith("admin_do_cancel_"))
async def admin_do_cancel(callback: CallbackQuery, db, bot, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    registration_id = int(callback.data.split("_")[-1])
    reg = db.get_registration_with_user(registration_id)
    if not reg:
        await callback.answer("Регистрация не найдена.", show_alert=True)
        return
    if reg["status"] == "cancelled":
        await callback.answer("Уже отменена.", show_alert=True)
        return

    db.cancel_registration_by_id(registration_id)

    await callback.message.answer(
        f"✅ Регистрация команды <b>{reg['team_name']}</b> отменена."
    )
    await callback.answer()

    # Уведомляем капитана
    try:
        await bot.send_message(
            reg["user_telegram_id"],
            f"❌ <b>Ваша регистрация отменена</b>\n\n"
            f"Команда: <b>{reg['team_name']}</b>\n\n"
            f"Если возникли вопросы — свяжитесь с организаторами @razumboy."
        )
    except Exception:
        pass


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
    db.save_broadcast(event["id"], text, sent_count, broadcast_type="manual", recipients_info="Все подписчики")
    result = f"✅ Рассылка завершена. Отправлено: {sent_count} из {len(subscribers)}"
    if errors:
        result += f"\n\n⚠️ Ошибки ({len(errors)}):\n" + "\n".join(errors[:5])
    await message.answer(result, reply_markup=admin_menu())


def _reply_confirm_kb(registration_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Подтвердить участие",
            callback_data=f"confirm_players_{registration_id}"
        )],
        [InlineKeyboardButton(
            text="❌ Отменить участие",
            callback_data=f"cancel_players_{registration_id}"
        )],
    ])


# ── Подписчики (список + CSV) ─────────────────────────────────

@router.message(F.text == "👥 Подписчики")
async def show_subscribers_menu(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    count = db.get_subscribers_count()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👁 Просмотреть список", callback_data="subs_view_list")],
        [InlineKeyboardButton(text="📥 Скачать CSV (профили)", callback_data="subs_export_csv")],
    ])
    await message.answer(
        f"👥 <b>Подписчики: {count} чел.</b>\n\nВыберите действие:",
        reply_markup=kb
    )


@router.callback_query(F.data == "subs_view_list")
async def subs_view_list(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    subscribers = db.get_all_subscribers()
    count = len(subscribers)
    if not subscribers:
        await callback.message.answer("Подписчиков пока нет.")
        await callback.answer()
        return

    header = f"👥 <b>Подписчики: {count} чел.</b>\n\n"
    lines = []
    for i, user in enumerate(subscribers, 1):
        if user["username"]:
            link = f'<a href="tg://resolve?domain={user["username"]}">@{user["username"]}</a>'
        else:
            link = f'<a href="tg://user?id={user["telegram_id"]}">{user["full_name"] or "Без имени"}</a>'
        lines.append(f"{i}. {link}")

    chunk_size = 30
    for start in range(0, len(lines), chunk_size):
        chunk = lines[start:start + chunk_size]
        text = (header if start == 0 else "") + "\n".join(chunk)
        await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "subs_export_csv")
async def subs_export_csv(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    profiles = db.get_all_subscriber_profiles()
    if not profiles:
        await callback.message.answer("База подписчиков пуста.")
        await callback.answer()
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
    await callback.message.answer_document(
        document=BufferedInputFile(csv_content, filename="subscribers_profile.csv"),
        caption=f"📥 База подписчиков — {len(profiles)} чел."
    )
    await callback.answer()


# ── Предыдущие рассылки ───────────────────────────────────────

def _broadcast_filter_kb(active: str = "all") -> InlineKeyboardMarkup:
    """Кнопки фильтра: Все / Авто / Вручную."""
    def mark(key):
        return f"{'✅ ' if active == key else ''}"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{mark('all')}📋 Все", callback_data="bcast_filter_all"),
        InlineKeyboardButton(text=f"{mark('auto')}🤖 Авто", callback_data="bcast_filter_auto"),
        InlineKeyboardButton(text=f"{mark('manual')}✍️ Вручную", callback_data="bcast_filter_manual"),
    ]])


async def _show_broadcasts_list(target, db, btype: str = "all"):
    """target — Message или CallbackQuery. btype: 'all', 'auto', 'manual'."""
    import re as _re
    filter_arg = None if btype == "all" else btype
    broadcasts = db.get_broadcasts(limit=20, broadcast_type=filter_arg)

    labels = {"all": "Все рассылки", "auto": "Авторассылки 🤖", "manual": "Ручные рассылки ✍️"}
    header = f"📬 <b>{labels[btype]} (последние {len(broadcasts)}):</b>"

    is_cb = hasattr(target, "message")
    send = target.message.answer if is_cb else target.answer

    if not broadcasts:
        await send(f"{header}\n\nРассылок пока не было.", reply_markup=_broadcast_filter_kb(btype))
        return

    await send(header, reply_markup=_broadcast_filter_kb(btype))

    for i, b in enumerate(broadcasts, 1):
        btype_icon = "🤖" if b["broadcast_type"] == "auto" else "✍️"
        label = b["recipients_info"] or b["event_title"] or "Свой пост"
        clean_text = _re.sub(r"<[^>]+>", "", b["message_text"] or "")
        preview = clean_text[:80].replace("\n", " ")
        if len(clean_text) > 80:
            preview += "..."
        sent_at = b["sent_at"][:16].replace("T", " ")
        text = (
            f"{i}. {btype_icon} <b>{label}</b>\n"
            f"📅 {sent_at} | 📨 {b['sent_count']} чел.\n"
            f"<i>{preview}</i>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="👁 Полный текст", callback_data=f"broadcast_view_{b['id']}")
        ]])
        await send(text, reply_markup=kb)


@router.message(F.text == "📬 История рассылок")
async def show_broadcasts(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    await _show_broadcasts_list(message, db, btype="all")


@router.callback_query(F.data.startswith("bcast_filter_"))
async def broadcasts_filter(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    btype = callback.data.split("bcast_filter_")[1]  # all / auto / manual
    await callback.answer()
    await _show_broadcasts_list(callback, db, btype=btype)


@router.callback_query(F.data.startswith("broadcast_view_"))
async def view_broadcast_text(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    broadcast_id = int(callback.data.split("_")[-1])
    broadcasts = db.get_broadcasts(limit=100)
    b = next((x for x in broadcasts if x["id"] == broadcast_id), None)
    if not b:
        await callback.answer("Рассылка не найдена.", show_alert=True)
        return
    btype_icon = "🤖" if b["broadcast_type"] == "auto" else "✍️"
    label = b["recipients_info"] or b["event_title"] or "Свой пост"
    sent_at = b["sent_at"][:16].replace("T", " ")
    header = f"{btype_icon} <b>{label}</b> | {sent_at} | {b['sent_count']} чел.\n\n"
    full_text = header + b["message_text"]
    if len(full_text) > 4096:
        full_text = full_text[:4090] + "..."
    await callback.message.answer(full_text)
    await callback.answer()


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


# ── Победители Рандомбой ──────────────────────────────────────

@router.message(F.text == "🏆 Победители Рандомбой")
async def giveaway_winners_menu(message: Message, state: FSMContext, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 За последние 5 дней",  callback_data="winners_5")],
        [InlineKeyboardButton(text="📅 За последние 30 дней", callback_data="winners_30")],
        [InlineKeyboardButton(text="📜 За всё время",         callback_data="winners_all")],
        [InlineKeyboardButton(text="🔗 Обновить Telegram ID победителей", callback_data="winners_resolve_ids")],
    ])
    await message.answer("🏆 <b>Победители Рандомбой</b>\n\nВыберите период:", reply_markup=kb)


@router.callback_query(F.data == "winners_resolve_ids")
async def winners_resolve_ids(callback: CallbackQuery, db, admin_ids: list[int]):
    """Подтягивает telegram_id победителей по username из таблицы users."""
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return

    # До обновления — считаем сколько без ID
    before = db.count_winners_without_id()
    db.resolve_winner_telegram_ids()
    after = db.count_winners_without_id()
    found = before - after

    if found > 0:
        await callback.message.answer(
            f"✅ Обновлено: найдено <b>{found}</b> Telegram ID по username.\n"
            f"Ещё без ID: <b>{after}</b> победителей (они не запускали бота)."
        )
    else:
        await callback.message.answer(
            f"ℹ️ Новых совпадений не найдено.\n\n"
            f"Победителей без Telegram ID: <b>{after}</b>\n\n"
            f"Эти пользователи ещё не запускали @Razumboy_Bot. "
            f"Как только они это сделают — их ID появится автоматически."
        )
    await callback.answer()


@router.callback_query(F.data.startswith("winners_") & ~F.data.startswith("winners_send_") & ~F.data.startswith("winners_broadcast_"))
async def show_giveaway_winners(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return

    period = callback.data.split("_")[1]  # "5", "30", "all"

    if period == "all":
        winners = db.get_giveaway_winners_since(days=36500)  # ~100 лет = все
        label = "за всё время"
    else:
        days = int(period)
        winners = db.get_giveaway_winners_since(days=days)
        label = f"за последние {days} дней"

    if not winners:
        await callback.message.answer(f"Победителей {label} нет.")
        await callback.answer()
        return

    lines = [f"🏆 <b>Победители Рандомбой {label} ({len(winners)} чел.):</b>\n"]
    for i, w in enumerate(winners, 1):
        mention = f"@{w['username']}" if w["username"] else w["full_name"] or f"id{w['telegram_id']}"
        won_date = w["won_at"][:10]  # YYYY-MM-DD
        lines.append(f"{i}. {mention} - {won_date}")

    # Разбиваем на части если список большой
    text = "\n".join(lines)
    if len(text) <= 4096:
        await callback.message.answer(text)
    else:
        chunk = []
        header = lines[0]
        for line in lines[1:]:
            chunk.append(line)
            if len(header + "\n" + "\n".join(chunk)) > 3800:
                await callback.message.answer(header + "\n" + "\n".join(chunk[:-1]))
                chunk = [line]
        if chunk:
            await callback.message.answer(header + "\n" + "\n".join(chunk))

    # Кнопка «Отправить сообщение» — показываем всегда
    eligible_count = sum(1 for w in winners if w["telegram_id"] > 0)
    btn_text = (
        f"📨 Отправить сообщение ({eligible_count} из {len(winners)} чел.)"
        if eligible_count < len(winners)
        else f"📨 Отправить сообщение ({eligible_count} чел.)"
    )
    note = ""
    if eligible_count == 0:
        note = "\n\n⚠️ У всех победителей этого периода нет Telegram ID — рассылка недоступна. Это касается победителей, добавленных вручную."
    elif eligible_count < len(winners):
        note = f"\n\n⚠️ {len(winners) - eligible_count} победителей без Telegram ID будут пропущены."

    send_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=btn_text,
            callback_data=f"winners_send_{period}"
        )
    ]])
    await callback.message.answer(
        f"Отправить сообщение победителям {label}?{note}",
        reply_markup=send_kb
    )

    await callback.answer()


# ── Рассылка победителям из списка ───────────────────────────

@router.callback_query(F.data.startswith("winners_send_"))
async def winners_broadcast_start(callback: CallbackQuery, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return

    period = callback.data.split("winners_send_")[1]  # "5", "30", "all"

    if period == "all":
        winners = db.get_giveaway_winners_since(days=36500)
        label = "за всё время"
    else:
        winners = db.get_giveaway_winners_since(days=int(period))
        label = f"за последние {period} дней"

    eligible = [w for w in winners if w["telegram_id"] > 0]

    if not eligible:
        await callback.message.answer(
            f"⚠️ Ни у одного из победителей {label} нет Telegram ID.\n\n"
            f"Рассылка доступна только победителям, которые участвовали через бота. "
            f"Исторические победители, добавленные вручную, не получат сообщение."
        )
        await callback.answer()
        return

    await state.set_state(AdminWinnersBroadcastState.message_text)
    await state.update_data(winners_period=period, eligible_count=len(eligible))
    await callback.message.answer(
        f"✍️ Напишите сообщение для победителей {label}.\n\n"
        f"Получателей: <b>{len(eligible)}</b> чел."
    )
    await callback.answer()


@router.message(AdminWinnersBroadcastState.message_text, F.text)
async def winners_broadcast_text(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    period = data["winners_period"]
    eligible_count = data["eligible_count"]

    await state.update_data(broadcast_text=text)

    label = "за всё время" if period == "all" else f"за последние {period} дней"

    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✅ Отправить {eligible_count} победителям",
            callback_data="winners_broadcast_confirm"
        )],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="winners_broadcast_cancel")],
    ])
    await message.answer(
        f"📋 <b>Предпросмотр:</b>\n\n"
        f"{text}\n\n"
        f"──────────────────\n"
        f"📤 Получатели: победители {label} — <b>{eligible_count}</b> чел.\n\n"
        f"Отправляем?",
        reply_markup=confirm_kb
    )


@router.callback_query(F.data == "winners_broadcast_confirm")
async def winners_broadcast_confirm(callback: CallbackQuery, state: FSMContext, db, bot, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return

    data = await state.get_data()
    period = data["winners_period"]
    text = data["broadcast_text"]
    await state.clear()

    if period == "all":
        winners = db.get_giveaway_winners_since(days=36500)
    else:
        winners = db.get_giveaway_winners_since(days=int(period))

    eligible = [w for w in winners if w["telegram_id"] > 0]

    sent = 0
    for w in eligible:
        try:
            await bot.send_message(w["telegram_id"], text)
            sent += 1
        except Exception:
            pass

    await callback.message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"📨 Отправлено: <b>{sent}</b> из <b>{len(eligible)}</b> победителей.",
        reply_markup=admin_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "winners_broadcast_cancel")
async def winners_broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Рассылка отменена.", reply_markup=admin_menu())
    await callback.answer()


# ── Рандомбой ─────────────────────────────────────────────────

@router.message(F.text == "🎲 Рандомбой")
async def randoboy_menu(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    participants = db.randoboy_get_participants()
    is_active = db.randoboy_is_active()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Пуск Рандомбой", callback_data="randoboy_start")],
        [InlineKeyboardButton(text="📋 Список участников", callback_data="randoboy_list")],
        [InlineKeyboardButton(text="🏆 Определить победителя", callback_data="randoboy_winner")],
        [InlineKeyboardButton(text="🔄 Сбросить", callback_data="randoboy_reset")],
    ])
    status = f"✅ Активен | Участников: {len(participants)}" if is_active else "⛔️ Не запущен"
    await message.answer(f"🎲 <b>Рандомбой</b>\n\nСтатус: {status}", reply_markup=kb)


@router.callback_query(F.data == "randoboy_list")
async def randoboy_list(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    participants = db.randoboy_get_participants()
    if not participants:
        await callback.message.answer("Участников пока нет.")
        await callback.answer()
        return
    lines = [f"📋 <b>Участники Рандомбой ({len(participants)}):</b>\n"]
    for i, p in enumerate(participants, 1):
        lines.append(f"{i}. {p['full_name']}")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data == "randoboy_start")
async def randoboy_start(callback: CallbackQuery, db, bot, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    db.randoboy_start()
    subscribers = db.get_subscribers()
    randoboy_share_url = (
        "https://t.me/share/url"
        "?url=https://t.me/Razumboy_Bot"
        "&text=%F0%9F%8E%B2+%D0%9F%D1%80%D0%B8%D1%81%D0%BE%D0%B5%D0%B4%D0%B8%D0%BD%D1%8F%D0%B9%D1%81%D1%8F+%D0%BA+%D0%A0%D0%B0%D0%BD%D0%B4%D0%BE%D0%BC%D0%B1%D0%BE%D1%8E%21"
    )
    join_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Участвовать в Рандомбой!", callback_data="randoboy_join")],
        [InlineKeyboardButton(text="📤 Поделиться", url=randoboy_share_url)],
    ])
    sent = 0
    for user in subscribers:
        try:
            await bot.send_message(
                user["telegram_id"],
                "🎲 <b>Рандомбой запущен!</b>\n\nНажмите кнопку ниже, чтобы принять участие!",
                reply_markup=join_kb
            )
            sent += 1
        except Exception:
            pass
    await callback.message.answer(f"✅ Рандомбой запущен! Отправлено {sent} подписчикам.", reply_markup=admin_menu())
    await callback.answer()


@router.callback_query(F.data == "randoboy_winner")
async def randoboy_pick_winner(callback: CallbackQuery, db, bot, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    import random
    participants = db.randoboy_get_participants()
    if not participants:
        await callback.message.answer("❌ Нет участников.")
        await callback.answer()
        return
    winner = random.choice(participants)
    winner_id = winner["telegram_id"]
    winner_name = winner["full_name"]
    db.randoboy_remove(winner_id)

    winner_user = db.get_user_by_telegram_id(winner_id)
    if winner_user and winner_user["username"]:
        winner_mention = f"@{winner_user['username']}"
    else:
        winner_mention = f"<a href='tg://user?id={winner_id}'>{winner_name}</a>"

    broadcast_text = (
        f"🎲 <b>Рандомбой совершенно случайно и неумышленно выбрал {winner_mention}!</b>\n\n"
        f"🏆 Поздравляем!"
    )
    remaining = db.randoboy_get_participants()
    subscribers = db.get_subscribers()
    for user in subscribers:
        try:
            await bot.send_message(user["telegram_id"], broadcast_text)
        except Exception:
            pass
    await callback.message.answer(
        f"✅ Победитель определён и объявлен!\n"
        f"👤 {winner_name}\nОсталось участников: {len(remaining)}"
    )
    await callback.answer()


@router.callback_query(F.data == "randoboy_reset")
async def randoboy_reset(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    db.randoboy_reset()
    await callback.message.answer("🔄 Рандомбой сброшен.")
    await callback.answer()


@router.callback_query(F.data == "randoboy_join")
async def randoboy_join(callback: CallbackQuery, db):
    if not db.randoboy_is_active():
        await callback.answer("Рандомбой уже завершён.", show_alert=True)
        return
    joined = db.randoboy_join(callback.from_user.id, callback.from_user.full_name)
    if not joined:
        await callback.answer("Вы уже зарегистрированы!", show_alert=True)
        return
    await callback.answer("✅ Ваша заявка принята!", show_alert=True)


# ── Блиц-квиз ─────────────────────────────────────────────────


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
    if not message.text:
        await message.answer("Введите текст вопроса. ✍️")
        return
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
    if not message.text:
        await message.answer("Введите правильный ответ текстом. ✍️")
        return
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
    mode = callback.data.replace("blitz_mode_", "")
    data = await state.get_data()
    await state.clear()

    duration = data["blitz_duration"]
    end_time = (datetime.datetime.now() + datetime.timedelta(seconds=duration)).isoformat()
    db.blitz_start(
        question=data["blitz_question"],
        answer=data["blitz_answer"],
        mode=mode,
        duration=duration,
        end_time=end_time,
    )

    subscribers = db.get_subscribers()
    photo_id = data.get("blitz_photo")
    question_text = (
        f"⚡️ <b>БЛИЦ-КВИЗ!</b>\n\n"
        f"❓ {data['blitz_question']}\n\n"
        f"⏱ Время на ответ: {duration} секунд\n"
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
        f"Режим: {mode_text} | Время: {duration} сек.",
        reply_markup=admin_menu()
    )
    await callback.answer()

    # Автоматически завершаем квиз через N секунд
    async def finish_blitz():
        await asyncio.sleep(duration)
        session = db.blitz_get_session()
        if not session or not session["active"]:
            return
        db.blitz_stop()
        winners = db.blitz_get_winners()
        if winners:
            lines = ["⚡️ <b>Блиц-квиз завершён!</b>\n\n🏆 Победители:"]
            for i, w in enumerate(winners, 1):
                winner_user = db.get_user_by_telegram_id(w["telegram_id"])
                mention = f"@{winner_user['username']}" if winner_user and winner_user["username"] else w["full_name"]
                lines.append(f"{i}. {mention}")
            lines.append("\n🎉 Поздравляем!")
            result_text = "\n".join(lines)
        else:
            result_text = "⚡️ Блиц-квиз завершён. Правильных ответов не было."
        for user in db.get_subscribers():
            try:
                await bot.send_message(user["telegram_id"], result_text)
            except Exception:
                pass

    asyncio.create_task(finish_blitz())


# ── Прошедшие игры ────────────────────────────────────────────

@router.message(F.text == "🗓 Прошедшие игры")
async def past_events_list(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    events = db.get_past_events()
    if not events:
        await message.answer("Прошедших игр пока нет.")
        return
    buttons = []
    for event in events:
        buttons.append([InlineKeyboardButton(
            text=f"📅 {event['event_date']} — {event['title']}",
            callback_data=f"past_event_{event['id']}"
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("🗓 <b>Прошедшие игры:</b>", reply_markup=kb)


@router.callback_query(F.data.startswith("past_event_"))
async def past_event_registrations(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    event_id = int(callback.data.split("_")[-1])
    event = db.get_event_by_id(event_id)
    regs = db.get_registrations_for_event(event_id)
    if not regs:
        await callback.message.answer(
            f"📅 <b>{event['title']}</b> ({event['event_date']})\n\nЗаявок нет."
        )
        await callback.answer()
        return
    lines = [f"📅 <b>{event['title']}</b> ({event['event_date']})\n"
             f"Всего команд: {len(regs)}\n"]
    for i, r in enumerate(regs, 1):
        username = f"@{r['username']}" if r.get('username') else "—"
        lines.append(
            f"{i}. <b>{r['team_name']}</b> — {r['team_size']} чел.\n"
            f"   Капитан: {r['captain_name']} | {r['phone']}\n"
            f"   TG: {username}"
        )
    await callback.message.answer("\n".join(lines))
    await callback.answer()


# ── (📥 База подписчиков удалена, объединена с 👥 Подписчики) ──


# ── Проходка — розыгрыш ───────────────────────────────────────

def _giveaway_settings_text(s, session=None) -> str:
    active = "✅ Активен" if s and s["active"] else "⛔️ Выключен"
    announce_time = s["announce_time"] if s else "20:50"
    draw_time = s["draw_time"] if s else "21:00"
    announce_preview = (s["announce_text"][:80] + "…") if s and s["announce_text"] else "—"
    congrats_preview = (s["congrats_text"][:80] + "…") if s and s["congrats_text"] else "—"
    img = "✅ есть" if s and s["image_file_id"] else "—"

    if s and s["active_days"]:
        day_names = [DAYS_LABELS[int(d)] for d in sorted(s["active_days"].split(",")) if d.isdigit()]
        days_str = ", ".join(day_names) if day_names else "—"
    else:
        days_str = "Пн, Вт, Ср, Чт, Пт, Сб, Вс"

    text = (
        f"🎟 <b>Розыгрыш проходок</b>\n\n"
        f"Статус: {active}\n"
        f"⏰ Рассылка: <b>{announce_time}</b> | Жеребьёвка: <b>{draw_time}</b>\n"
        f"📅 Дни: <b>{days_str}</b>\n"
        f"🖼 Картинка: {img}\n\n"
        f"📢 Текст объявления:\n<i>{announce_preview}</i>\n\n"
        f"🏆 Текст поздравления:\n<i>{congrats_preview}</i>\n"
        f"<code>{{winners}}</code> — плейсхолдер для имён победителей\n"
    )
    if session:
        status_map = {"pending": "⏳ Ожидает", "announced": "📢 Объявлено", "done": "✅ Завершено"}
        text += (
            f"\n📊 <b>Сегодня ({session['date']}):</b>\n"
            f"Статус: {status_map.get(session['status'], session['status'])}\n"
            f"Отправлено: {session['sent_count']} | Участвуют: {session['_participants']}"
        )
    return text


DAYS_LABELS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _giveaway_menu_kb(has_settings: bool, active: bool) -> InlineKeyboardMarkup:
    toggle = "⛔️ Выключить" if active else "✅ Включить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Текст объявления", callback_data="gw_edit_announce")],
        [InlineKeyboardButton(text="🏆 Текст поздравления", callback_data="gw_edit_congrats")],
        [InlineKeyboardButton(text="⏰ Изменить время", callback_data="gw_edit_time")],
        [InlineKeyboardButton(text="🖼 Изменить картинку", callback_data="gw_edit_image")],
        [InlineKeyboardButton(text="📅 Дни недели", callback_data="gw_edit_days")],
        [InlineKeyboardButton(text=toggle, callback_data="gw_toggle")],
        [InlineKeyboardButton(text="▶️ Запустить сейчас", callback_data="gw_run_now")],
        [InlineKeyboardButton(text="📊 Статистика гивэвея", callback_data="gw_stats")],
    ])


def _days_kb(active_days_str: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора дней: 7 кнопок с галочками, потом Сохранить."""
    active = set(active_days_str.split(",")) if active_days_str else set()
    buttons = []
    row = []
    for i, label in enumerate(DAYS_LABELS):
        mark = "✅" if str(i) in active else "◻️"
        row.append(InlineKeyboardButton(
            text=f"{mark} {label}",
            callback_data=f"gw_day_{i}"
        ))
    buttons.append(row)
    buttons.append([InlineKeyboardButton(text="💾 Сохранить", callback_data="gw_days_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(F.text == "🎟 Проходка")
async def giveaway_panel(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    import datetime as dt
    s = db.get_giveaway_settings()
    today = dt.datetime.now(tz=dt.timezone(dt.timedelta(hours=5))).strftime("%Y-%m-%d")
    raw_session = db.get_giveaway_session(today)
    session = None
    if raw_session:
        session = dict(raw_session)
        session["_participants"] = db.count_giveaway_participants(raw_session["id"])

    text = _giveaway_settings_text(s, session)
    active = bool(s and s["active"])
    await message.answer(text, reply_markup=_giveaway_menu_kb(bool(s), active))


# ── Редактирование настроек ────────────────────────────────────

@router.callback_query(F.data == "gw_edit_announce")
async def gw_edit_announce(callback: CallbackQuery, state: FSMContext, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    await state.set_state(AdminGiveawayState.announce_text)
    await callback.message.answer(
        "Введите новый текст объявления:\n\n"
        "<i>Используйте HTML: &lt;b&gt;жирный&lt;/b&gt;, &lt;i&gt;курсив&lt;/i&gt;</i>"
    )
    await callback.answer()


@router.message(AdminGiveawayState.announce_text, F.text)
async def gw_save_announce(message: Message, state: FSMContext, db):
    try:
        db.update_giveaway_field("announce_text", message.text.strip())
        await state.clear()
        await message.answer("✅ Текст объявления сохранён.", reply_markup=admin_menu())
    except Exception as e:
        await message.answer(f"❌ Ошибка сохранения: {e}")


@router.callback_query(F.data == "gw_edit_congrats")
async def gw_edit_congrats(callback: CallbackQuery, state: FSMContext, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    await state.set_state(AdminGiveawayState.congrats_text)
    await callback.message.answer(
        "Введите текст поздравления победителей.\n\n"
        "Используйте <code>{winners}</code> — туда подставятся имена победителей.\n\n"
        "Пример:\n"
        "<i>🎉 Сегодня Рандомбой выбрал {winners}! Вы получаете бесплатные пригласительные 🎟</i>"
    )
    await callback.answer()


@router.message(AdminGiveawayState.congrats_text, F.text)
async def gw_save_congrats(message: Message, state: FSMContext, db):
    try:
        db.update_giveaway_field("congrats_text", message.text.strip())
        await state.clear()
        await message.answer("✅ Текст поздравления сохранён.", reply_markup=admin_menu())
    except Exception as e:
        await message.answer(f"❌ Ошибка сохранения: {e}")


@router.callback_query(F.data == "gw_edit_time")
async def gw_edit_time(callback: CallbackQuery, state: FSMContext, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    await state.set_state(AdminGiveawayState.announce_time)
    await callback.message.answer(
        "Введите два времени через пробел:\n"
        "<b>время рассылки</b> и <b>время жеребьёвки</b>\n\n"
        "Пример: <code>20:50 21:00</code>"
    )
    await callback.answer()


@router.message(AdminGiveawayState.announce_time, F.text)
async def gw_save_time(message: Message, state: FSMContext, db):
    import re
    parts = message.text.strip().split()
    if len(parts) != 2 or not all(re.match(r"^\d{2}:\d{2}$", p) for p in parts):
        await message.answer("Неверный формат. Введите два времени: <code>20:50 21:00</code>")
        return
    try:
        db.update_giveaway_field("announce_time", parts[0])
        db.update_giveaway_field("draw_time", parts[1])
        await state.clear()
        await message.answer(
            f"✅ Время обновлено: рассылка в <b>{parts[0]}</b>, жеребьёвка в <b>{parts[1]}</b>",
            reply_markup=admin_menu()
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.callback_query(F.data == "gw_edit_image")
async def gw_edit_image(callback: CallbackQuery, state: FSMContext, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    await state.set_state(AdminGiveawayState.image)
    await callback.message.answer("Отправьте картинку для объявления (или /cancel чтобы убрать картинку):")
    await callback.answer()


@router.message(AdminGiveawayState.image, F.photo)
async def gw_save_image(message: Message, state: FSMContext, db):
    file_id = message.photo[-1].file_id
    db.update_giveaway_field("image_file_id", file_id)
    await state.clear()
    await message.answer("✅ Картинка сохранена.", reply_markup=admin_menu())


@router.callback_query(F.data == "gw_edit_days")
async def gw_edit_days(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    s = db.get_giveaway_settings()
    try:
        active_days = s["active_days"] if s and s["active_days"] else "0,1,2,3,4,5,6"
    except Exception:
        active_days = "0,1,2,3,4,5,6"
    await callback.message.answer(
        "📅 <b>Выбери дни розыгрыша</b>\n\n"
        "✅ — розыгрыш проводится\n◻️ — розыгрыш пропускается\n\n"
        "Нажимай на кнопки чтобы включить/выключить дни, затем <b>Сохранить</b>.",
        reply_markup=_days_kb(active_days)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gw_day_"))
async def gw_toggle_day(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    try:
        day = callback.data.split("gw_day_")[1]  # "0"–"6"
        s = db.get_giveaway_settings()
        # Безопасное чтение active_days — поле могло не быть в старой БД
        try:
            raw = s["active_days"] if s else ""
        except Exception:
            raw = "0,1,2,3,4,5,6"
        active_days = set(raw.split(",")) if raw else {"0","1","2","3","4","5","6"}
        if day in active_days:
            active_days.discard(day)
        else:
            active_days.add(day)
        new_days_str = ",".join(sorted(active_days))
        db.update_giveaway_field("active_days", new_days_str)
        await callback.message.edit_reply_markup(reply_markup=_days_kb(new_days_str))
        await callback.answer()
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@router.callback_query(F.data == "gw_days_done")
async def gw_days_done(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    s = db.get_giveaway_settings()
    try:
        active_days = s["active_days"] if s and s["active_days"] else "0,1,2,3,4,5,6"
    except Exception:
        active_days = "0,1,2,3,4,5,6"
    day_names = [DAYS_LABELS[int(d)] for d in sorted(active_days.split(",")) if d.isdigit()]
    await callback.message.answer(
        f"✅ Дни розыгрыша сохранены: <b>{', '.join(day_names)}</b>",
        reply_markup=admin_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "gw_toggle")
async def gw_toggle(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    s = db.get_giveaway_settings()
    new_active = 0 if (s and s["active"]) else 1
    db.update_giveaway_field("active", new_active)
    status = "включён ✅" if new_active else "выключен ⛔️"
    await callback.message.answer(f"Розыгрыш {status}.", reply_markup=admin_menu())
    await callback.answer()


@router.callback_query(F.data == "gw_stats")
async def gw_stats(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return

    s = db.get_giveaway_stats()

    top_lines = []
    for i, w in enumerate(s["top_winners"], 1):
        top_lines.append(f"  {i}. @{w['username']} — {w['wins']} раз")
    top_text = "\n".join(top_lines) if top_lines else "  нет данных"

    eng_yesterday = f"{s['engagement_yesterday']}%" if s["engagement_yesterday"] is not None else "нет данных"

    text = (
        f"📊 <b>Статистика Рандомбой-гивэвея</b>\n\n"
        f"📅 <b>Вчера:</b>\n"
        f"  Получили рассылку: {s['yesterday_sent']} чел.\n"
        f"  Участвовали: {s['yesterday_participants']} чел.\n"
        f"  Вовлечённость: {eng_yesterday}\n\n"
        f"📈 <b>За последние 7 дней:</b>\n"
        f"  Среднее участников/день: {s['avg_7_days']} чел.\n"
        f"  Вовлечённость: {s['engagement_7']}% от подписчиков\n\n"
        f"🏆 <b>Победители всего:</b>\n"
        f"  Всего побед: {s['total_wins']}\n"
        f"  Уникальных победителей: {s['unique_winners']}\n"
        f"  Побеждали >1 раза: {s['multi_winners']} чел.\n\n"
        f"🥇 <b>Топ-5 победителей:</b>\n{top_text}\n\n"
        f"👥 Подписчиков сейчас: {s['total_subs']}\n"
        f"🎲 Проведено розыгрышей: {s['total_sessions']}"
    )
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "gw_run_now")
async def gw_run_now(callback: CallbackQuery, db, bot, admin_ids: list[int]):
    """Ручной запуск — сначала рассылка, через сообщение админ запускает жеребьёвку."""
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    from handlers.giveaway import giveaway_announce
    await callback.message.answer("⏳ Запускаю рассылку объявления…")
    await giveaway_announce(bot, db, admin_ids)
    await callback.answer()


# ── Фотографии с игр (управление) ────────────────────────────

@router.message(F.text == "📸 Фото с игр")
async def manage_photo_albums(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    albums = db.get_photo_albums()
    text = "📸 <b>Фотографии с игр</b>\n\n"
    if albums:
        for a in albums:
            text += f"• {a['title']}\n"
    else:
        text += "Альбомов пока нет.\n"

    del_buttons = [
        [InlineKeyboardButton(text=f"🗑 {a['title']}", callback_data=f"photo_del_{a['id']}")]
        for a in albums
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить альбом", callback_data="photo_add")],
        *del_buttons,
    ])
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "photo_add")
async def photo_add_start(callback: CallbackQuery, state: FSMContext, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    await state.set_state(AdminPhotoAlbumState.date_text)
    await callback.message.answer("Введите дату игры в формате <b>«29 марта»</b>:")
    await callback.answer()


@router.message(AdminPhotoAlbumState.date_text)
async def photo_enter_date(message: Message, state: FSMContext):
    await state.update_data(date_text=message.text.strip())
    await state.set_state(AdminPhotoAlbumState.game_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Razumboy", callback_data="photo_type_Razumboy")],
        [InlineKeyboardButton(text="Razumbooo", callback_data="photo_type_Razumbooo")],
    ])
    await message.answer("Выберите тип игры:", reply_markup=kb)


@router.callback_query(F.data.startswith("photo_type_"), AdminPhotoAlbumState.game_type)
async def photo_choose_type(callback: CallbackQuery, state: FSMContext):
    game_type = callback.data.split("photo_type_")[1]
    await state.update_data(game_type=game_type)
    await state.set_state(AdminPhotoAlbumState.url)
    await callback.message.answer("Вставьте <b>ссылку</b> на фотографии:")
    await callback.answer()


@router.message(AdminPhotoAlbumState.url)
async def photo_enter_url(message: Message, state: FSMContext, db, bot):
    url = message.text.strip()
    data = await state.get_data()
    title = f"{data['date_text']}, {data['game_type']}"
    db.add_photo_album(title, url)
    await state.clear()

    # Рассылка подписчикам
    broadcast_text = (
        f"📸 <b>Новые фотографии с игры!</b>\n\n"
        f"🎉 Мы разобрали фотоархив — и спешим поделиться яркими моментами с <b>{title}</b>!\n\n"
        f"Смотрите, как это было: смех, азарт, командный дух и, конечно, правильные ответы 😄\n\n"
        f"👇 Нажмите кнопку ниже, чтобы посмотреть фотографии:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"📸 Смотреть фото — {title}", url=url)
    ]])

    subscribers = db.get_subscribers()
    sent_count = 0
    for user in subscribers:
        try:
            await bot.send_message(user["telegram_id"], broadcast_text, reply_markup=kb)
            sent_count += 1
        except Exception:
            pass

    db.save_broadcast(
        None, broadcast_text, sent_count,
        broadcast_type="auto",
        recipients_info=f"Все подписчики (новый фотоальбом: {title})"
    )
    await message.answer(
        f"✅ Альбом <b>«📸 {title}»</b> добавлен!\n\n"
        f"📨 Уведомление отправлено {sent_count} из {len(subscribers)} подписчиков.",
        reply_markup=admin_menu()
    )


@router.callback_query(F.data.startswith("photo_del_"))
async def photo_delete(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    album_id = int(callback.data.split("_")[-1])
    db.delete_photo_album(album_id)
    await callback.message.answer("🗑 Альбом удалён.", reply_markup=admin_menu())
    await callback.answer()


# ── Авторассылки (APScheduler) ───────────────────────────────

async def auto_remind_day_before(bot, db, admin_ids: list):
    """Авторассылка за день до игры — в 10:00 всем подписчикам."""
    import datetime
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    events = db.get_events_by_date_tomorrow(tomorrow)
    if not events:
        return

    subscribers = db.get_subscribers()
    for event in events:
        location_line = event["location"]
        if event["location_url"]:
            location_line += f"\n📍 {event['location_url']}"

        text = (
            f"😎 Добрый день!\n\n"
            f"Напоминаем, что завтра состоится <b>{event['title']}</b> - "
            f"и вы ещё можете к нам присоединиться!\n\n"
            f"📍 {location_line}\n"
            f"⏰ {event['event_time']}\n"
            f"💰 {event['price_text'] or 'уточняется'}\n\n"
            f"📞 Дополнительные заявки принимаются до 16:00 завтрашнего дня.\n"
            f"✍️ Регистрация: @Razumboy_Bot\n\n"
            f"До встречи! 😄"
        )
        sent = 0
        for user in subscribers:
            try:
                if event["photo_file_id"]:
                    await bot.send_photo(user["telegram_id"], photo=event["photo_file_id"], caption=text[:1024])
                else:
                    await bot.send_message(user["telegram_id"], text)
                sent += 1
            except Exception:
                pass

        db.save_broadcast(
            event["id"], text, sent,
            broadcast_type="auto",
            recipients_info=f"Все подписчики (за день до игры)"
        )
        for admin_id in admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    f"📅 <b>Авторассылка «за день до»</b> отправлена!\n"
                    f"Игра: {event['title']}\n"
                    f"Получили: {sent} из {len(subscribers)} подписчиков"
                )
            except Exception:
                pass


async def auto_remind_day_of(bot, db, admin_ids: list):
    """Авторассылка в день игры — в 10:00 зарегистрированным командам."""
    import datetime
    today = datetime.date.today().strftime("%Y-%m-%d")
    events = db.get_events_by_date(today)
    if not events:
        return

    for event in events:
        registrations = db.get_registrations_for_event(event["id"])
        if not registrations:
            continue

        location_line = event["location"]
        if event["location_url"]:
            location_line += f"\n🗺 {event['location_url']}"

        sent = 0
        for reg in registrations:
            text = (
                f"❤️ Добрый день!\n\n"
                f"Напоминаем - сегодня вечером <b>{event['title']}</b>!\n\n"
                f"Вы зарегистрировали <b>{reg['team_size']}</b> игроков. "
                f"Пожалуйста, уточните у команды точное количество участников.\n\n"
                f"📍 {location_line}\n"
                f"⏰ {event['event_time']}\n\n"
                f"Ждём вас! 💃"
            )
            try:
                await bot.send_message(reg["telegram_id"], text)
                sent += 1
            except Exception:
                pass

        # Сохраняем одну запись с общим текстом-шаблоном (без персональных данных)
        sample_text = (
            f"❤️ Добрый день!\n\n"
            f"Напоминаем - сегодня вечером <b>{event['title']}</b>!\n\n"
            f"Пожалуйста, уточните у команды точное количество участников.\n\n"
            f"📍 {location_line}\n"
            f"⏰ {event['event_time']}\n\n"
            f"Ждём вас! 💃"
        )
        db.save_broadcast(
            event["id"], sample_text, sent,
            broadcast_type="auto",
            recipients_info=f"Зарегистрированные команды (в день игры)"
        )
        for admin_id in admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    f"🎮 <b>Авторассылка «день игры»</b> отправлена!\n"
                    f"Игра: {event['title']}\n"
                    f"Получили: {sent} из {len(registrations)} команд"
                )
            except Exception:
                pass


# ── Шаблоны рассылок ─────────────────────────────────────────

def _templates_kb(templates) -> InlineKeyboardMarkup:
    buttons = []
    for t in templates:
        preview = t["title"]
        buttons.append([
            InlineKeyboardButton(text=f"▶️ {preview}", callback_data=f"tmpl_use_{t['id']}"),
            InlineKeyboardButton(text="✏️", callback_data=f"tmpl_edit_{t['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"tmpl_del_{t['id']}"),
        ])
    buttons.append([InlineKeyboardButton(text="➕ Новый шаблон", callback_data="tmpl_new")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(F.text == "📋 Шаблоны рассылок")
async def broadcast_templates_menu(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()
    templates = db.get_broadcast_templates()
    if not templates:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Создать первый шаблон", callback_data="tmpl_new")
        ]])
        await message.answer("📋 <b>Шаблоны рассылок</b>\n\nШаблонов пока нет.", reply_markup=kb)
        return
    await message.answer(
        f"📋 <b>Шаблоны рассылок ({len(templates)} шт.)</b>\n\n"
        f"▶️ — использовать  ✏️ — изменить текст  🗑 — удалить",
        reply_markup=_templates_kb(templates)
    )


@router.callback_query(F.data == "broadcast_from_template")
async def broadcast_from_template(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    templates = db.get_broadcast_templates()
    if not templates:
        await callback.message.answer(
            "Шаблонов пока нет. Создайте через «📋 Шаблоны рассылок» в меню."
        )
        await callback.answer()
        return
    await callback.message.answer(
        "Выберите шаблон для рассылки:",
        reply_markup=_templates_kb(templates)
    )
    await callback.answer()


@router.callback_query(F.data == "tmpl_new")
async def tmpl_new(callback: CallbackQuery, state: FSMContext, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    await state.set_state(AdminBroadcastTemplateState.new_title)
    await callback.message.answer("Введите <b>название шаблона</b> (для вашего удобства):\nПример: «Анонс пятницы»")
    await callback.answer()


@router.message(AdminBroadcastTemplateState.new_title, F.text)
async def tmpl_new_title(message: Message, state: FSMContext):
    await state.update_data(tmpl_title=message.text.strip())
    await state.set_state(AdminBroadcastTemplateState.new_text)
    await message.answer("Теперь введите <b>текст шаблона</b>:")


@router.message(AdminBroadcastTemplateState.new_text, F.text)
async def tmpl_new_text(message: Message, state: FSMContext, db):
    data = await state.get_data()
    title = data["tmpl_title"]
    text = message.text.strip()
    db.save_broadcast_template(title, text)
    await state.clear()
    templates = db.get_broadcast_templates()
    await message.answer(
        f"✅ Шаблон <b>«{title}»</b> сохранён!",
        reply_markup=_templates_kb(templates)
    )


@router.callback_query(F.data.startswith("tmpl_use_"))
async def tmpl_use(callback: CallbackQuery, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    tmpl_id = int(callback.data.split("tmpl_use_")[1])
    tmpl = db.get_broadcast_template(tmpl_id)
    if not tmpl:
        await callback.answer("Шаблон не найден.", show_alert=True)
        return
    await state.update_data(custom_text=tmpl["text"])
    await state.set_state(AdminBroadcastState.custom_photo)
    await callback.message.answer(
        f"📋 Шаблон <b>«{tmpl['title']}»</b> загружен.\n\n"
        f"Прикрепите картинку или напишите <b>-</b> чтобы без картинки:"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tmpl_edit_"))
async def tmpl_edit(callback: CallbackQuery, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    tmpl_id = int(callback.data.split("tmpl_edit_")[1])
    tmpl = db.get_broadcast_template(tmpl_id)
    if not tmpl:
        await callback.answer("Шаблон не найден.", show_alert=True)
        return
    await state.set_state(AdminBroadcastTemplateState.edit_text)
    await state.update_data(edit_tmpl_id=tmpl_id)
    await callback.message.answer(
        f"✏️ Редактирование шаблона <b>«{tmpl['title']}»</b>\n\n"
        f"Текущий текст:\n<i>{tmpl['text'][:300]}{'...' if len(tmpl['text']) > 300 else ''}</i>\n\n"
        f"Введите новый текст:"
    )
    await callback.answer()


@router.message(AdminBroadcastTemplateState.edit_text, F.text)
async def tmpl_edit_save(message: Message, state: FSMContext, db):
    data = await state.get_data()
    tmpl_id = data["edit_tmpl_id"]
    db.update_broadcast_template_text(tmpl_id, message.text.strip())
    await state.clear()
    tmpl = db.get_broadcast_template(tmpl_id)
    templates = db.get_broadcast_templates()
    await message.answer(
        f"✅ Шаблон <b>«{tmpl['title']}»</b> обновлён!",
        reply_markup=_templates_kb(templates)
    )


@router.callback_query(F.data.startswith("tmpl_del_"))
async def tmpl_del(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    tmpl_id = int(callback.data.split("tmpl_del_")[1])
    db.delete_broadcast_template(tmpl_id)
    templates = db.get_broadcast_templates()
    if templates:
        await callback.message.edit_reply_markup(reply_markup=_templates_kb(templates))
    else:
        await callback.message.answer("Шаблон удалён. Шаблонов больше нет.")
    await callback.answer("🗑 Удалено")


@router.message(F.text & ~F.text.startswith("/"))
async def blitz_catch_answer(message: Message, bot, db, admin_ids: list[int]):
    """Перехватываем ответы на блиц-квиз"""
    import datetime
    session = db.blitz_get_session()
    if not session or not session["active"]:
        return
    if session["end_time"] and datetime.datetime.now() > datetime.datetime.fromisoformat(session["end_time"]):
        return

    user_answer = message.text.strip().lower()
    user_id = message.from_user.id
    user_name = message.from_user.full_name

    if db.blitz_winner_exists(user_id):
        return

    if user_answer == session["answer"]:
        db.blitz_add_winner(user_id, user_name)
        await message.answer("✅ Правильно! Ваш ответ засчитан!")

        if session["mode"] == "first":
            db.blitz_stop()
            username = message.from_user.username
            mention = f"@{username}" if username else user_name
            result_text = (
                f"⚡️ <b>Блиц-квиз завершён!</b>\n\n"
                f"🏆 Первый правильный ответ:\n"
                f"1. {mention} — «{message.text.strip()}»\n\n"
                f"🎉 Поздравляем!"
            )
            for sub in db.get_subscribers():
                try:
                    await bot.send_message(sub["telegram_id"], result_text)
                except Exception:
                    pass


# ── Реферальная система (панель администратора) ───────────────

@router.message(F.text == "🔗 Рефералы (панель)")
async def referral_admin_panel(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.clear()

    import datetime as dt
    current_month = dt.date.today().strftime("%Y-%m")
    leaderboard = db.get_referral_leaderboard(month=current_month)

    lines = [f"🔗 <b>Рефералы — {current_month}</b>\n"]

    if leaderboard:
        lines.append("🏆 <b>Топ рефереров этого месяца:</b>")
        for i, row in enumerate(leaderboard, 1):
            mention = f"@{row['username']}" if row['username'] else row['full_name'] or f"id{row['telegram_id']}"
            lines.append(f"{i}. {mention} — {row['count']} чел.")
    else:
        lines.append("Рефералов в этом месяце пока нет.")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Проверить код скидки", callback_data="ref_check_code")],
        [InlineKeyboardButton(text="📊 Топ за всё время", callback_data="ref_leaderboard_all")],
    ])
    await message.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data == "ref_check_code")
async def ref_check_code_start(callback: CallbackQuery, state: FSMContext, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    await state.set_state(AdminReferralCheckState.waiting_code)
    await callback.message.answer("🔑 Введите код скидки (например: RAZUM-AB3X9K):")
    await callback.answer()


@router.message(AdminReferralCheckState.waiting_code)
async def ref_check_code_verify(message: Message, state: FSMContext, db, admin_ids: list[int]):
    if not is_admin(message.from_user.id, admin_ids):
        return
    code = message.text.strip().upper()
    reward = db.get_reward_by_code(code)

    if not reward:
        await message.answer(
            f"❌ Код <code>{code}</code> не найден.\n\nПроверьте правильность ввода.",
            reply_markup=admin_menu()
        )
        await state.clear()
        return

    reward_labels = {
        'discount_30': '🎉 Скидка 30%',
        'discount_50': '🔥 Скидка 50%',
        'free_pass':   '🏆 Бесплатная проходка',
    }
    label = reward_labels.get(reward['reward_type'], reward['reward_type'])
    owner = f"@{reward['username']}" if reward['username'] else reward['full_name'] or f"id{reward['telegram_id']}"
    issued = reward['issued_at'][:16].replace('T', ' ')
    status_icon = "✅ Активен" if reward['status'] == 'active' else f"❌ Использован ({reward['used_at'][:10] if reward['used_at'] else ''})"

    text = (
        f"🔑 <b>Код: <code>{code}</code></b>\n\n"
        f"🎁 Награда: {label}\n"
        f"👤 Владелец: {owner}\n"
        f"📅 Выдан: {issued}\n"
        f"📌 Статус: {status_icon}"
    )

    if reward['status'] == 'active':
        if reward['reward_type'] == 'free_pass':
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Активировать проходку", callback_data=f"ref_use_{code}")
            ]])
            await message.answer(text, reply_markup=kb)
            await state.clear()
        else:
            # Скидка — показываем игры с ценами
            await message.answer(text)
            await _ask_event_for_discount(
                message, db, state,
                reward_code=code, reward_type=reward['reward_type'],
                owner=owner, owner_tid=reward['telegram_id']
            )
    else:
        await message.answer(text, reply_markup=admin_menu())
        await state.clear()


@router.callback_query(F.data.startswith("ref_use_"))
async def ref_mark_used(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    code = callback.data.split("ref_use_")[1]
    success = db.mark_reward_used(code)
    if success:
        await callback.message.answer(
            f"✅ Код <code>{code}</code> отмечен как использованный.",
            reply_markup=admin_menu()
        )
    else:
        await callback.message.answer("⚠️ Код уже был использован или не найден.", reply_markup=admin_menu())
    await callback.answer()


@router.callback_query(F.data == "ref_leaderboard_all")
async def ref_leaderboard_all(callback: CallbackQuery, db, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return
    leaderboard = db.get_referral_leaderboard(month=None)
    if not leaderboard:
        await callback.message.answer("Рефералов пока нет.")
        await callback.answer()
        return
    lines = ["🏆 <b>Топ рефереров за всё время:</b>\n"]
    for i, row in enumerate(leaderboard, 1):
        mention = f"@{row['username']}" if row['username'] else row['full_name'] or f"id{row['telegram_id']}"
        lines.append(f"{i}. {mention} — {row['count']} чел.")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


# ── Отладочные команды реферальной системы ────────────────────

@router.message(Command("testref"))
async def cmd_testref(message: Message, db, bot, admin_ids: list[int]):
    """
    /testref N — добавляет N фейковых квалифицированных рефералов (только для админа).
    Фейковые пользователи имеют отрицательные ID и не влияют на реальных юзеров.
    """
    if not is_admin(message.from_user.id, admin_ids):
        return

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /testref 5\nДобавляет 5 тестовых рефералов.")
        return

    count = int(parts[1])
    if count > 30:
        await message.answer("Максимум 30 за раз.")
        return

    uid = message.from_user.id
    import time

    added = 0
    rewards_issued = []
    for i in range(count):
        fake_id = -(int(time.time() * 1000) + i)  # уникальный отрицательный ID
        recorded = db.record_referral(uid, fake_id)
        if recorded:
            # Сразу квалифицируем
            with db._connect() as conn:
                conn.execute(
                    "UPDATE referrals SET qualified = 1, qualified_at = datetime('now') WHERE referred_telegram_id = ?",
                    (fake_id,)
                )
                conn.commit()
            added += 1

        # Проверяем порог после каждого добавления
        reward = db.check_and_issue_reward(uid)
        if reward:
            rewards_issued.append(reward)
            from handlers.common import _send_reward_notification
            await _send_reward_notification(bot, uid, reward)

    stats = db.get_referral_stats(uid)
    lines = [
        f"🧪 <b>Тест рефералов</b>",
        f"Добавлено: {added} фейковых рефералов",
        f"Текущий счёт: {stats['current_count']}/{stats['next_threshold']} → {stats['next_label']}",
        f"Всего квалифицированных: {stats['total_qualified']}",
    ]
    if rewards_issued:
        lines.append(f"\n🎉 Выдано наград: {len(rewards_issued)}")
        for r in rewards_issued:
            lines.append(f"  • {r['reward_label']}: <code>{r['code']}</code>")
    else:
        lines.append("\nНаград пока не выдано — порог не достигнут.")

    lines.append("\n<i>Для сброса тестовых данных: /resetref</i>")
    await message.answer("\n".join(lines))


@router.message(Command("resetref"))
async def cmd_resetref(message: Message, db, admin_ids: list[int]):
    """Удаляет все тестовые (фейковые) рефералы — только для отладки."""
    if not is_admin(message.from_user.id, admin_ids):
        return

    with db._connect() as conn:
        deleted = conn.execute(
            "DELETE FROM referrals WHERE referred_telegram_id < 0"
        ).rowcount
        conn.commit()

    # Пересчитываем stats после сброса
    stats = db.get_referral_stats(message.from_user.id)
    await message.answer(
        f"🗑 Удалено {deleted} тестовых рефералов.\n"
        f"Текущий реальный счёт: {stats['current_count']}/{stats['next_threshold']}"
    )


# ── Расчёт скидки через выбор игры ───────────────────────────

def _parse_price(price_text: str):
    """Извлекает число из текста цены: '80 000 сум' → 80000. None если не удалось."""
    import re
    if not price_text:
        return None
    cleaned = re.sub(r'(\d)[\s,](\d)', r'\1\2', price_text)
    cleaned = re.sub(r'(\d)[\s,](\d)', r'\1\2', cleaned)  # дважды для «80 000 000»
    match = re.search(r'\d+', cleaned)
    return int(match.group()) if match else None


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


async def _ask_event_for_discount(target, db, state, reward_code, reward_type, owner, owner_tid):
    """Показывает список ближайших игр с ценами для выбора."""
    events = db.get_open_events()
    discounts = {'discount_30': 30, 'discount_50': 50}
    pct = discounts.get(reward_type, 0)

    send = target.answer if hasattr(target, 'answer') else target.message.answer

    if not events:
        await send(
            "⚠️ Нет активных игр. Введите сумму вручную (цифрами, в сумах):"
        )
        await state.set_state(AdminReferralCheckState.waiting_event)
        await state.update_data(reward_code=reward_code, reward_type=reward_type,
                                owner=owner, owner_tid=owner_tid, manual=True)
        return

    buttons = []
    for e in events:
        price = _parse_price(e["price_text"])
        if price:
            discount_amount = round(price * pct / 100)
            to_pay = price - discount_amount
            btn_text = f"🎯 {e['title']} — {_fmt(to_pay)} сум (было {_fmt(price)})"
        else:
            btn_text = f"🎯 {e['title']} — цена не указана"
        buttons.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"ref_event_{e['id']}"
        )])

    buttons.append([InlineKeyboardButton(text="✏️ Ввести сумму вручную", callback_data="ref_event_manual")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await state.set_state(AdminReferralCheckState.waiting_event)
    await state.update_data(reward_code=reward_code, reward_type=reward_type,
                            owner=owner, owner_tid=owner_tid, manual=False)
    await send(f"🎯 Выберите игру для применения скидки {pct}%:", reply_markup=kb)


@router.callback_query(F.data.startswith("ref_event_"), AdminReferralCheckState.waiting_event)
async def ref_apply_discount_event(callback: CallbackQuery, state: FSMContext, db, bot, admin_ids: list[int]):
    if not is_admin(callback.from_user.id, admin_ids):
        await callback.answer()
        return

    data = await state.get_data()
    code = data["reward_code"]
    reward_type = data["reward_type"]
    owner = data["owner"]
    owner_tid = data["owner_tid"]
    discounts = {'discount_30': 30, 'discount_50': 50}
    pct = discounts[reward_type]

    if callback.data == "ref_event_manual":
        await callback.message.answer("✏️ Введите полную стоимость участия (в сумах):")
        await state.update_data(manual=True)
        await callback.answer()
        return

    event_id = int(callback.data.split("ref_event_")[1])
    event = db.get_event_by_id(event_id)
    price = _parse_price(event["price_text"]) if event else None

    if not price:
        await callback.message.answer("⚠️ Цена этой игры не задана числом. Введите сумму вручную (в сумах):")
        await state.update_data(manual=True)
        await callback.answer()
        return

    await _finalize_discount(callback.message, db, bot, state, code, reward_type,
                             pct, price, owner, owner_tid)
    await callback.answer()


@router.message(AdminReferralCheckState.waiting_event)
async def ref_manual_amount(message: Message, state: FSMContext, db, bot, admin_ids: list[int]):
    """Хендлер ручного ввода суммы (fallback)."""
    if not is_admin(message.from_user.id, admin_ids):
        return
    data = await state.get_data()
    if not data.get("manual"):
        return

    raw = message.text.strip().replace(" ", "").replace(",", "")
    if not raw.isdigit():
        await message.answer("❌ Введите сумму цифрами, например: 80000")
        return

    code = data["reward_code"]
    reward_type = data["reward_type"]
    owner = data["owner"]
    owner_tid = data["owner_tid"]
    discounts = {'discount_30': 30, 'discount_50': 50}
    pct = discounts[reward_type]

    await _finalize_discount(message, db, bot, state, code, reward_type,
                             pct, int(raw), owner, owner_tid)


async def _finalize_discount(message, db, bot, state, code, reward_type, pct, total, owner, owner_tid):
    discount_amount = round(total * pct / 100)
    to_pay = total - discount_amount
    db.mark_reward_used(code)
    await state.clear()

    await message.answer(
        f"✅ <b>Скидка применена!</b>\n\n"
        f"👤 Владелец: {owner}\n"
        f"🎁 Скидка: {pct}%\n\n"
        f"💵 Полная стоимость: <s>{_fmt(total)} сум</s>\n"
        f"💰 Скидка: -{_fmt(discount_amount)} сум\n"
        f"✅ <b>К оплате: {_fmt(to_pay)} сум</b>",
        reply_markup=admin_menu()
    )
    try:
        await bot.send_message(
            owner_tid,
            f"✅ Ваша скидка {pct}% активирована!\n\n"
            f"💰 Вы сэкономили {_fmt(discount_amount)} сум. Наслаждайтесь игрой! 🎉"
        )
    except Exception:
        pass
