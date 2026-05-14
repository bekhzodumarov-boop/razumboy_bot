from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from states import ConfirmPlayersState, WinnerConfirmState

router = Router()


# ── Мои регистрации ───────────────────────────────────────────

@router.message(F.text == "🗂 Мои регистрации")
async def my_registrations(message: Message, db):
    user = db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return

    regs = db.get_user_registrations(user["id"])
    if not regs:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📝 Зарегистрироваться на игру", callback_data="go_to_events")
        ]])
        await message.answer(
            "У вас пока нет активных регистраций. 🙁\n\n"
            "Хотите записаться на ближайшую игру?",
            reply_markup=kb
        )
        return

    from handlers.common import format_date_short
    lines = ["<b>Ваши актуальные регистрации:</b>\n"]
    cancel_buttons = []
    for i, r in enumerate(regs, 1):
        date_short = format_date_short(r["event_date"])
        lines.append(
            f"{i}. <b>{r['title']}</b>\n"
            f"   📅 {date_short} в {r['event_time']}\n"
            f"   📍 {r['location']}\n"
            f"   👥 Команда: {r['team_name']} ({r['team_size']} чел.)\n"
        )
        cancel_buttons.append([InlineKeyboardButton(
            text=f"❌ Отменить: {r['team_name']}",
            callback_data=f"pre_cancel_reg_{r['id']}"
        )])

    kb = InlineKeyboardMarkup(inline_keyboard=cancel_buttons)
    await message.answer("\n".join(lines), reply_markup=kb)


# ── Кнопка "Зарегистрироваться на игру" из раздела Мои регистрации ──

@router.callback_query(F.data == "go_to_events")
async def go_to_events(callback: CallbackQuery, db):
    from handlers.common import _show_events_list
    events = db.get_open_events()
    if not events:
        await callback.message.answer("Пока нет открытых игр. Следите за анонсами! 🔔")
    else:
        await _show_events_list(callback.message, events)
    await callback.answer()


# ── Отмена регистрации игроком (с подтверждением) ─────────────

@router.callback_query(F.data.startswith("pre_cancel_reg_"))
async def pre_cancel_reg(callback: CallbackQuery, db):
    registration_id = int(callback.data.split("_")[-1])
    reg = db.get_registration_by_id(registration_id)
    if not reg:
        await callback.answer("Регистрация не найдена.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Да, отменить",
            callback_data=f"cancel_players_{registration_id}"
        )],
        [InlineKeyboardButton(
            text="🔙 Нет, оставить",
            callback_data="dismiss_cancel_reg"
        )],
    ])
    await callback.message.answer(
        f"Вы уверены, что хотите отменить регистрацию команды <b>{reg['team_name']}</b>?",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data == "dismiss_cancel_reg")
async def dismiss_cancel_reg(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


# ── Подтверждение участия в день игры ─────────────────────────

@router.callback_query(F.data.startswith("confirm_players_"))
async def confirm_players_start(callback: CallbackQuery, state: FSMContext):
    registration_id = int(callback.data.split("_")[-1])
    await state.update_data(registration_id=registration_id)
    await state.set_state(ConfirmPlayersState.waiting_reply)
    await callback.message.answer(
        "Пожалуйста, напишите точное количество игроков, кто придёт с вашей стороны.\n\n"
        "Пример:\n<i>5 человек</i>"
    )
    await callback.answer()


@router.message(ConfirmPlayersState.waiting_reply)
async def confirm_players_save(message: Message, state: FSMContext, db, bot, admin_ids: list[int]):
    data = await state.get_data()
    registration_id = data["registration_id"]

    text = message.text.strip()

    # Пытаемся вытащить число из начала текста
    import re
    match = re.search(r"\d+", text)
    confirmed_count = int(match.group()) if match else None

    db.save_confirmation(
        registration_id=registration_id,
        confirmed_count=confirmed_count,
        player_names=text,
    )

    reg = db.get_registration_by_id(registration_id)

    await message.answer(
        "✅ Спасибо! Ваш ответ сохранён. До встречи вечером! 💃"
    )

    # Уведомляем админа
    admin_text = (
        f"📋 <b>Подтверждение от команды</b>\n\n"
        f"Команда: {reg['team_name']}\n"
        f"Ответ: {text}\n"
        f"User: @{message.from_user.username or 'без username'} ({message.from_user.id})"
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception:
            pass

    await state.clear()


@router.callback_query(F.data.startswith("cancel_players_"))
async def cancel_players(callback: CallbackQuery, db, bot, admin_ids: list[int]):
    registration_id = int(callback.data.split("_")[-1])
    reg = db.get_registration_by_id(registration_id)
    if not reg:
        await callback.answer("Регистрация не найдена.", show_alert=True)
        return
    if reg["status"] == "cancelled":
        await callback.answer("Регистрация уже отменена.", show_alert=True)
        return

    db.cancel_registration_by_id(registration_id)

    await callback.message.answer(
        "❌ Ваша регистрация отменена. Жаль, что не увидимся! 😔\n\n"
        "Если планы изменятся — регистрируйтесь снова через бот."
    )
    await callback.answer()

    # Уведомляем админов
    admin_text = (
        f"❌ <b>Отмена регистрации</b>\n\n"
        f"Команда: <b>{reg['team_name']}</b> ({reg['team_size']} чел.)\n"
        f"Капитан: {reg['captain_name']} | {reg['phone']}\n"
        f"User: @{callback.from_user.username or 'без username'} ({callback.from_user.id})"
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception:
            pass


# ── Победитель Рандомбой: ввод названия команды ───────────────

@router.message(WinnerConfirmState.team_name)
async def winner_team_name(message: Message, state: FSMContext, bot, admin_ids: list[int]):
    team_name = message.text.strip() if message.text else ""
    if not team_name:
        await message.answer("Пожалуйста, напишите название команды текстом:")
        return

    await state.clear()
    await message.answer(
        f"✅ Спасибо! Команда <b>{team_name}</b> записана.\n\n"
        f"До встречи на игре! 🎉"
    )

    admin_text = (
        f"🎟 <b>Победитель подтвердил участие</b>\n\n"
        f"Команда: <b>{team_name}</b>\n"
        f"User: @{message.from_user.username or 'без username'} ({message.from_user.id})"
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception:
            pass
