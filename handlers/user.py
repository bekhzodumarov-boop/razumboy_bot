from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from states import ConfirmPlayersState, WinnerConfirmState
from database import REFERRAL_THRESHOLDS

router = Router()


# ── Реферальная система ───────────────────────────────────────

@router.message(F.text == "🎁 Бонусы")
async def referral_panel(message: Message, db):
    uid = message.from_user.id
    stats = db.get_referral_stats(uid)
    active_rewards = db.get_active_rewards(uid)

    # Реферальная ссылка
    ref_link = f"https://t.me/Razumboy_Bot?start=ref{uid}"

    # Прогресс к следующей награде
    current = stats["current_count"]
    next_t = stats["next_threshold"]
    next_label = stats["next_label"]
    progress_bar = _progress_bar(current, next_t)

    lines = [
        "🎁 <b>Реферальная программа Разумбой</b>\n",
        f"🔗 Ваша ссылка:",
        f"<code>{ref_link}</code>\n",
        f"📊 <b>Прогресс:</b> {current}/{next_t} — {next_label}",
        progress_bar,
    ]

    # Все уровни наград
    lines.append("\n🏅 <b>Уровни наград (в рамках одного цикла):</b>")
    for threshold, rtype, label in REFERRAL_THRESHOLDS:
        lines.append(f"  • {threshold} чел. → {label}")
    lines.append("  ℹ️ После получения награды счётчик обнуляется")

    # Активные коды
    qr_buttons = []
    if active_rewards:
        lines.append(f"\n🎟 <b>Ваши активные коды ({len(active_rewards)}):</b>")
        for r in active_rewards:
            issued = r["issued_at"][:10]
            lines.append(f"  🔑 <code>{r['reward_code']}</code> — {_reward_label(r['reward_type'])} (выдан {issued})")
            qr_buttons.append([InlineKeyboardButton(
                text=f"📱 QR-код — {_reward_label(r['reward_type'])}",
                callback_data=f"show_reward_qr_{r['reward_code']}"
            )])
        lines.append("\n📱 Нажмите кнопку ниже чтобы показать QR-код сотруднику.")

    import urllib.parse
    share_text = "🧠 Квиз Разумбой — Ташкент!\n\nРегистрируйся на игры и участвуй в ежедневных розыгрышах кепок:"
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={urllib.parse.quote(share_text)}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url)],
        *qr_buttons,
    ])

    await message.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("show_reward_qr_"))
async def show_reward_qr(callback: CallbackQuery, db):
    from aiogram.types import BufferedInputFile
    from handlers.common import _generate_qr, _send_reward_notification
    code = callback.data.split("show_reward_qr_")[1]
    reward = db.get_reward_by_code(code)
    if not reward or reward["status"] != "active":
        await callback.answer("Код уже использован или не найден.", show_alert=True)
        return
    reward_labels = {'discount_30': 'Скидка 30%', 'discount_50': 'Скидка 50%', 'free_pass': 'Бесплатная проходка'}
    label = reward_labels.get(reward["reward_type"], "Бонус")
    qr_buf = _generate_qr(code)
    qr_file = BufferedInputFile(qr_buf.read(), filename="reward_qr.png")
    await callback.message.answer_photo(
        photo=qr_file,
        caption=(
            f"📱 <b>QR-код для активации</b>\n\n"
            f"🎁 {label}\n"
            f"🔑 Код: <code>{code}</code>\n\n"
            f"Покажите этот QR сотруднику — он отсканирует и активирует бонус."
        )
    )
    await callback.answer()


def _progress_bar(current: int, total: int) -> str:
    filled = min(current, total)
    bar = "▓" * filled + "░" * (total - filled)
    return f"[{bar}] {current}/{total}"


def _reward_label(reward_type: str) -> str:
    labels = {
        'discount_30': 'Скидка 30%',
        'discount_50': 'Скидка 50%',
        'free_pass':   'Бесплатная проходка',
    }
    return labels.get(reward_type, reward_type)


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
async def winner_team_name(message: Message, state: FSMContext, db, bot, admin_ids: list[int]):
    team_name = message.text.strip() if message.text else ""
    if not team_name:
        await message.answer("Пожалуйста, напишите название команды текстом:")
        return

    data = await state.get_data()
    reminder_date = data.get("reminder_date", "")
    await state.clear()

    if reminder_date:
        db.update_winner_reminder_response(
            telegram_id=message.from_user.id,
            reminder_date=reminder_date,
            status="confirmed",
            team_name=team_name,
        )

    await message.answer(
        f"✅ Спасибо! Команда <b>{team_name}</b> записана.\n\n"
        f"До встречи на игре! 🎉"
    )

    # Отправляем админам обновлённый список
    if reminder_date:
        from handlers.giveaway import _format_admin_winner_list
        responses = db.get_winner_reminder_responses(reminder_date)
        admin_msg = _format_admin_winner_list(responses, reminder_date)
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, admin_msg)
            except Exception:
                pass
