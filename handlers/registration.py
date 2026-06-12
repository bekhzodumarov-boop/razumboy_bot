import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from states import RegistrationState
from keyboards.inline import confirm_registration_kb
from keyboards.reply import main_menu, phone_request_kb
from handlers.common import format_date_short

router = Router()

PHONE_RE = re.compile(r"^\+998\d{9}$")

CANCEL_BTN = InlineKeyboardButton(text="❌ Отмена", callback_data="reg_cancel")


def _cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[CANCEL_BTN]])


def _team_name_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Я без команды", callback_data="reg_no_team")],
        [CANCEL_BTN],
    ])


# ── Отмена из любого шага ──────────────────────────────────────

@router.callback_query(F.data == "reg_cancel")
async def reg_cancel(callback: CallbackQuery, state: FSMContext, admin_ids: list[int]):
    await state.clear()
    await callback.message.answer(
        "Регистрация отменена.",
        reply_markup=main_menu(callback.from_user.id in admin_ids)
    )
    await callback.answer()


# ── Старт регистрации ──────────────────────────────────────────

@router.message(F.text == "📝 Регистрация")
async def start_registration(message: Message, state: FSMContext, db):
    events = db.get_open_events()
    if not events:
        await message.answer("Сейчас нет открытых игр для регистрации.")
        return
    await state.set_state(RegistrationState.team_name)
    await message.answer("Введите название команды:", reply_markup=_team_name_kb())


@router.callback_query(F.data.startswith("register_event_"))
async def register_from_event(callback: CallbackQuery, state: FSMContext, db):
    event_id = int(callback.data.split("_")[-1])
    event = db.get_event_by_id(event_id)
    if not event or event["status"] != "open":
        await callback.message.answer("Эта игра недоступна для регистрации.")
        await callback.answer()
        return
    await state.update_data(event_id=event_id)
    await state.set_state(RegistrationState.team_name)
    await callback.message.answer("Введите название команды:", reply_markup=_team_name_kb())
    await callback.answer()


# ── Шаг 1: название команды ────────────────────────────────────

@router.callback_query(F.data == "reg_no_team", RegistrationState.team_name)
async def reg_no_team(callback: CallbackQuery, state: FSMContext):
    await state.update_data(team_name="")
    await state.set_state(RegistrationState.team_size)
    await callback.message.answer(
        "Сколько вас будет? Введите число от 1 до 12.",
        reply_markup=_cancel_kb()
    )
    await callback.answer()


@router.message(RegistrationState.team_name)
async def reg_team_name(message: Message, state: FSMContext):
    team_name = message.text.strip()
    if len(team_name) < 2:
        await message.answer("Название команды слишком короткое. Введите ещё раз:", reply_markup=_team_name_kb())
        return
    await state.update_data(team_name=team_name)
    await state.set_state(RegistrationState.team_size)
    await message.answer(
        "Сколько будет игроков? Введите число от 1 до 12.",
        reply_markup=_cancel_kb()
    )


# ── Шаг 2: количество игроков ──────────────────────────────────

@router.message(RegistrationState.team_size)
async def reg_team_size(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Нужно ввести число от 1 до 12.", reply_markup=_cancel_kb())
        return
    team_size = int(text)
    if team_size < 1 or team_size > 12:
        await message.answer("Размер команды должен быть от 1 до 12.", reply_markup=_cancel_kb())
        return
    await state.update_data(team_size=team_size)
    await state.set_state(RegistrationState.captain_name)
    await message.answer("Введите имя капитана:", reply_markup=_cancel_kb())


# ── Шаг 3: имя капитана ────────────────────────────────────────

@router.message(RegistrationState.captain_name)
async def reg_captain_name(message: Message, state: FSMContext):
    captain_name = message.text.strip()
    if len(captain_name) < 2:
        await message.answer("Слишком короткое имя. Введите ещё раз:", reply_markup=_cancel_kb())
        return
    await state.update_data(captain_name=captain_name)
    await state.set_state(RegistrationState.phone)
    await message.answer(
        "Укажите номер телефона капитана.\n"
        "Нажмите кнопку ниже или введите вручную в формате <b>+998XXXXXXXXX</b>:",
        reply_markup=phone_request_kb()
    )
    await message.answer("Или отмените регистрацию:", reply_markup=_cancel_kb())


# ── Шаг 4: телефон ─────────────────────────────────────────────

@router.message(RegistrationState.phone, F.contact)
async def reg_phone_contact(message: Message, state: FSMContext, admin_ids: list[int]):
    phone_raw = message.contact.phone_number
    phone = phone_raw if phone_raw.startswith("+") else f"+{phone_raw}"
    await state.update_data(phone=phone)
    await state.set_state(RegistrationState.comment)
    await message.answer(
        "Комментарий к заявке (необязательно). Если нет — напишите: <b>-</b>",
        reply_markup=main_menu(message.from_user.id in admin_ids)
    )
    await message.answer("Или отмените регистрацию:", reply_markup=_cancel_kb())


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
            "Или нажмите кнопку 📱 чтобы поделиться номером автоматически:",
            reply_markup=_cancel_kb()
        )
        return
    await state.update_data(phone=phone)
    await state.set_state(RegistrationState.comment)
    await message.answer(
        "Комментарий к заявке (необязательно). Если нет — напишите: <b>-</b>",
        reply_markup=main_menu(message.from_user.id in admin_ids)
    )
    await message.answer("Или отмените регистрацию:", reply_markup=_cancel_kb())


# ── Шаг 5: комментарий ─────────────────────────────────────────

@router.message(RegistrationState.comment)
async def reg_comment(message: Message, state: FSMContext, db):
    comment = message.text.strip()
    if comment == "-":
        comment = ""
    await state.update_data(comment=comment)
    data = await state.get_data()

    if data.get("event_id"):
        await _show_summary(message, state, data)
        return

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
    buttons.append([CANCEL_BTN])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.set_state(RegistrationState.choose_event)
    await message.answer("На какую игру хотите зарегистрироваться?", reply_markup=kb)


# ── Шаг 6: выбор игры ──────────────────────────────────────────

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


# ── Итоговая сводка ────────────────────────────────────────────

async def _show_summary(message, state, data):
    team_display = data['team_name'] if data['team_name'] else "Без команды"
    summary = (
        "<b>Проверьте заявку:</b>\n\n"
        f"🏷 Команда: {team_display}\n"
        f"👥 Игроков: {data['team_size']}\n"
        f"👤 Капитан: {data['captain_name']}\n"
        f"📞 Телефон: {data['phone']}\n"
        f"💬 Комментарий: {data.get('comment') or 'нет'}"
    )
    await state.set_state(RegistrationState.confirm)
    await message.answer(summary, reply_markup=confirm_registration_kb())


# ── Редактировать / отменить (из сводки) ───────────────────────

@router.callback_query(F.data == "edit_registration")
async def edit_registration(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    event_id = data.get("event_id")
    await state.clear()
    if event_id:
        await state.update_data(event_id=event_id)
    await state.set_state(RegistrationState.team_name)
    await callback.message.answer("Заполним заново. Введите название команды:", reply_markup=_team_name_kb())
    await callback.answer()


@router.callback_query(F.data == "cancel_registration")
async def cancel_registration(callback: CallbackQuery, state: FSMContext, admin_ids: list[int]):
    await state.clear()
    await callback.message.answer("Регистрация отменена.", reply_markup=main_menu(callback.from_user.id in admin_ids))
    await callback.answer()


# ── Подтверждение ──────────────────────────────────────────────

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
    date_short = format_date_short(event["event_date"])

    await callback.message.answer(
        f"✅ Готово! Вы зарегистрированы на игру "
        f"<b>{event['title']}</b> ({date_short}).\n"
        f"Ждём вас! 🧠",
        reply_markup=main_menu(callback.from_user.id in admin_ids)
    )

    team_display = data['team_name'] if data['team_name'] else "Без команды"
    admin_text = (
        "🆕 <b>Новая регистрация</b>\n\n"
        f"Игра: {event['title']} ({date_short})\n"
        f"Команда: {team_display}\n"
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
