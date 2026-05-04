import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from states import RegistrationState
from keyboards.inline import confirm_registration_kb
from keyboards.reply import main_menu, phone_request_kb
from handlers.common import format_date_short

router = Router()

# Пункт 3: строгий формат +998XXXXXXXXX (9 цифр после кода)
PHONE_RE = re.compile(r"^\+998\d{9}$")


@router.message(F.text == "📝 Регистрация")
async def start_registration(message: Message, state: FSMContext, db):
    events = db.get_open_events()
    if not events:
        await message.answer("Сейчас нет открытых игр для регистрации.")
        return
    await state.set_state(RegistrationState.team_name)
    await message.answer("Введите название команды:")


@router.callback_query(F.data.startswith("register_event_"))
async def register_from_event(callback: CallbackQuery, state: FSMContext, db):
    event_id = int(callback.data.split("_")[-1])
    event = db.get_event_by_id(event_id)
    if not event or event["status"] != "open":
        await callback.message.answer("Эта игра недоступна для регистрации.")
        await callback.answer()
        return
    # Сразу сохраняем event_id если пришли из анонса
    await state.update_data(event_id=event_id)
    await state.set_state(RegistrationState.team_name)
    await callback.message.answer("Введите название команды:")
    await callback.answer()


@router.message(RegistrationState.team_name)
async def reg_team_name(message: Message, state: FSMContext):
    team_name = message.text.strip()
    if len(team_name) < 2:
        await message.answer("Название команды слишком короткое. Введите ещё раз:")
        return
    await state.update_data(team_name=team_name)
    await state.set_state(RegistrationState.team_size)
    await message.answer("Сколько будет игроков? Введите число от 1 до 12.")


@router.message(RegistrationState.team_size)
async def reg_team_size(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Нужно ввести число от 1 до 12.")
        return
    team_size = int(text)
    if team_size < 1 or team_size > 12:
        await message.answer("Размер команды должен быть от 1 до 12.")
        return
    await state.update_data(team_size=team_size)
    await state.set_state(RegistrationState.captain_name)
    await message.answer("Введите имя капитана:")


@router.message(RegistrationState.captain_name)
async def reg_captain_name(message: Message, state: FSMContext):
    captain_name = message.text.strip()
    if len(captain_name) < 2:
        await message.answer("Слишком короткое имя. Введите ещё раз:")
        return
    await state.update_data(captain_name=captain_name)
    await state.set_state(RegistrationState.phone)
    await message.answer(
        "Укажите номер телефона капитана.\n"
        "Нажмите кнопку ниже или введите вручную в формате <b>+998XXXXXXXXX</b>:",
        reply_markup=phone_request_kb()
    )


@router.message(RegistrationState.phone, F.contact)
async def reg_phone_contact(message: Message, state: FSMContext, admin_ids: list[int]):
    """Телефон через кнопку 'Поделиться номером'"""
    phone_raw = message.contact.phone_number
    phone = phone_raw if phone_raw.startswith("+") else f"+{phone_raw}"
    await state.update_data(phone=phone)
    await state.set_state(RegistrationState.comment)
    await message.answer(
        "Комментарий к заявке (необязательно). Если нет — напишите: <b>-</b>",
        reply_markup=main_menu(message.from_user.id in admin_ids)
    )


@router.message(RegistrationState.phone)
async def reg_phone(message: Message, state: FSMContext, admin_ids: list[int]):
    if not message.text:
        return
    phone = message.text.strip().replace(" ", "").replace("-", "")
    if not PHONE_RE.match(phone):
        await message.answer(
            "❌ Неверный формат номера.\n\n"
            "Принимаются только узбекские номера в формате:\n"
            "<b>+998XXXXXXXXX</b>\n\n"
            "Пример: <b>+998901234567</b>\n\n"
            "Или нажмите кнопку 📱 чтобы поделиться номером автоматически:"
        )
        return
    await state.update_data(phone=phone)
    await state.set_state(RegistrationState.comment)
    await message.answer(
        "Комментарий к заявке (необязательно). Если нет — напишите: <b>-</b>",
        reply_markup=main_menu(message.from_user.id in admin_ids)
    )


@router.message(RegistrationState.comment)
async def reg_comment(message: Message, state: FSMContext, db):
    comment = message.text.strip()
    if comment == "-":
        comment = ""
    await state.update_data(comment=comment)
    data = await state.get_data()

    # Пункт 6: если event_id уже выбран (через кнопку анонса) — пропускаем выбор игры
    if data.get("event_id"):
        await _show_summary(message, state, data)
        return

    # Пункт 6: показываем кнопки выбора игры
    events = db.get_open_events()
    if not events:
        await message.answer("К сожалению, сейчас нет открытых игр.")
        await state.clear()
        return

    buttons = []
    for event in events:
        date_short = format_date_short(event["event_date"])
        buttons.append([InlineKeyboardButton(
            text=f"📅 {date_short} — {event['title']}",
            callback_data=f"reg_pick_event_{event['id']}"
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.set_state(RegistrationState.choose_event)
    await message.answer("На какую игру хотите зарегистрироваться?", reply_markup=kb)


@router.callback_query(F.data.startswith("reg_pick_event_"), RegistrationState.choose_event)
async def reg_pick_event(callback: CallbackQuery, state: FSMContext, db):
    event_id = int(callback.data.split("_")[-1])
    event = db.get_event_by_id(event_id)
    if not event or event["status"] != "open":
        await callback.message.answer("Эта игра недоступна.")
        await callback.answer()
        return
    await state.update_data(event_id=event_id)
    data = await state.get_data()
    await _show_summary(callback.message, state, data)
    await callback.answer()


async def _show_summary(message, state, data):
    from handlers.common import format_date_short
    from database import Database
    # Получаем название игры для отображения
    summary = (
        "<b>Проверьте заявку:</b>\n\n"
        f"🏷 Команда: {data['team_name']}\n"
        f"👥 Игроков: {data['team_size']}\n"
        f"👤 Капитан: {data['captain_name']}\n"
        f"📞 Телефон: {data['phone']}\n"
        f"💬 Комментарий: {data.get('comment') or 'нет'}"
    )
    await state.set_state(RegistrationState.confirm)
    await message.answer(summary, reply_markup=confirm_registration_kb())


@router.callback_query(F.data == "edit_registration")
async def edit_registration(callback: CallbackQuery, state: FSMContext):
    """Сброс — начать заполнение заново, сохранив event_id"""
    data = await state.get_data()
    event_id = data.get("event_id")
    await state.clear()
    if event_id:
        await state.update_data(event_id=event_id)
    await state.set_state(RegistrationState.team_name)
    await callback.message.answer("Заполним заново. Введите название команды:")
    await callback.answer()


@router.callback_query(F.data == "cancel_registration")
async def cancel_registration(callback: CallbackQuery, state: FSMContext, admin_ids: list[int]):
    await state.clear()
    await callback.message.answer("Регистрация отменена.", reply_markup=main_menu(callback.from_user.id in admin_ids))
    await callback.answer()


@router.callback_query(F.data == "confirm_registration")
async def confirm_registration(callback: CallbackQuery, state: FSMContext, db, bot, admin_ids: list[int]):
    data = await state.get_data()
    event_id = data["event_id"]

    user_row = db.get_user_by_telegram_id(callback.from_user.id)
    if not user_row:
        await callback.message.answer("Ошибка: пользователь не найден. Нажмите /start и попробуйте снова.")
        await callback.answer()
        return

    if db.has_active_registration(event_id, user_row["id"]):
        await callback.message.answer("У вас уже есть активная регистрация на эту игру.")
        await state.clear()
        await callback.answer()
        return

    db.create_registration(
        event_id=event_id,
        user_id=user_row["id"],
        team_name=data["team_name"],
        team_size=data["team_size"],
        captain_name=data["captain_name"],
        phone=data["phone"],
        comment=data.get("comment", ""),
    )

    event = db.get_event_by_id(event_id)
    from handlers.common import format_date_short
    date_short = format_date_short(event["event_date"])

    # Пункт 7: показываем название и дату игры
    await callback.message.answer(
        f"✅ Готово! Ваша команда зарегистрирована на игру "
        f"<b>{event['title']}</b> ({date_short}).\n"
        f"Ждём вас! 🧠"
    )

    admin_text = (
        "🆕 <b>Новая регистрация</b>\n\n"
        f"Игра: {event['title']} ({date_short})\n"
        f"Команда: {data['team_name']}\n"
        f"Игроков: {data['team_size']}\n"
        f"Капитан: {data['captain_name']}\n"
        f"Телефон: {data['phone']}\n"
        f"Комментарий: {data.get('comment') or 'нет'}\n"
        f"User: @{callback.from_user.username or 'без username'} ({callback.from_user.id})"
    )

    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception:
            pass

    await state.clear()
    await callback.answer()
