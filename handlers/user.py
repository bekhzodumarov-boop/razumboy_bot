from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from states import ConfirmPlayersState, WinnerConfirmState, EditTeamSizeState
from database import REFERRAL_THRESHOLDS

router = Router()


# ── Реферальная система ───────────────────────────────────────

async def _build_bonuses_panel(uid: int, db):
    """Строит текст и клавиатуру панели бонусов."""
    import urllib.parse
    stats = db.get_referral_stats(uid)
    active_rewards = db.get_active_rewards(uid)
    referred_users = db.get_referred_users(uid)

    ref_link = f"https://t.me/Razumboy_Bot?start=ref{uid}"
    current = stats["current_count"]
    next_t = stats["next_threshold"]
    next_label = stats["next_label"]
    progress_bar = _progress_bar(current, next_t)

    lines = [
        "🎁 <b>ПРИВОДИ ДРУЗЕЙ — ПОЛУЧАЙ БОНУСЫ!</b>\n",
        "Разумбой запускает реферальную программу для участников бота @Razumboy_Bot\n",
        "Всё просто: делись своей уникальной ссылкой - и получай награды за каждого нового участника, который зарегистрируется по ней.\n",
        "🏅 <b>Система наград:</b>",
        "→ 5 друзей — скидка 30% на следующую игру",
        "→ 10 друзей — скидка 50% на следующую игру",
        "→ 15 друзей — бесплатная проходка 🎟\n",
        "🏆 <b>Амбассадор месяца</b>",
        "Тот, кто пригласит больше всех за месяц, получает фирменную кепку Разумбой + особый статус в боте.\n",
        "ℹ️ Счётчик обнуляется после получения награды и в начале каждого месяца\n",
        f"🔗 <b>Ваша ссылка:</b>",
        f"<code>{ref_link}</code>\n",
        f"📊 <b>Ваш прогресс:</b> {current}/{next_t} — {next_label}",
        progress_bar,
    ]

    if referred_users:
        lines.append(f"\n👥 <b>Ваши приглашённые ({len(referred_users)}):</b>")
        for i, u in enumerate(referred_users, 1):
            mention = f"@{u['username']}" if u['username'] else u['full_name'] or f"id{u['telegram_id']}"
            lines.append(f"  {i}. {mention}")

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

    share_text = "🧠 Квиз Разумбой — Ташкент!\n\nПодпишись на наш бот и стань участником нашего комьюнити!\nТебя ждут интересные игры, веселая компания и крутые призы!"
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={urllib.parse.quote(share_text)}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url)],
        *qr_buttons,
    ])
    return "\n".join(lines), kb


@router.message(F.text == "🎁 Бонусы")
async def referral_panel(message: Message, db):
    text, kb = await _build_bonuses_panel(message.from_user.id, db)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("show_reward_qr_"))
async def show_reward_qr(callback: CallbackQuery, db):
    from aiogram.types import BufferedInputFile
    from handlers.common import _generate_qr
    code = callback.data.split("show_reward_qr_")[1]
    reward = db.get_reward_by_code(code)
    if not reward or reward["status"] != "active":
        await callback.answer("Код уже использован или не найден.", show_alert=True)
        return
    reward_labels = {'discount_30': 'Скидка 30%', 'discount_50': 'Скидка 50%', 'free_pass': 'Бесплатная проходка'}
    label = reward_labels.get(reward["reward_type"], "Бонус")
    qr_buf = _generate_qr(code)
    qr_file = BufferedInputFile(qr_buf.read(), filename="reward_qr.png")
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 Назад к бонусам", callback_data="back_to_bonuses")
    ]])
    await callback.message.answer_photo(
        photo=qr_file,
        caption=(
            f"📱 <b>QR-код для активации</b>\n\n"
            f"🎁 {label}\n"
            f"🔑 Код: <code>{code}</code>\n\n"
            f"Покажите этот QR сотруднику — он отсканирует и активирует бонус."
        ),
        reply_markup=back_kb
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_bonuses")
async def back_to_bonuses(callback: CallbackQuery, db):
    """Возврат в панель бонусов из QR-кода"""
    text, kb = await _build_bonuses_panel(callback.from_user.id, db)
    await callback.message.answer(text, reply_markup=kb)
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
    buttons = []
    for i, r in enumerate(regs, 1):
        date_short = format_date_short(r["event_date"])
        lines.append(
            f"{i}. <b>{r['title']}</b>\n"
            f"   📅 {date_short} в {r['event_time']}\n"
            f"   📍 {r['location']}\n"
            f"   👥 Команда: {r['team_name']} ({r['team_size']} чел.)\n"
        )
        buttons.append([
            InlineKeyboardButton(
                text=f"✏️ Изменить кол-во",
                callback_data=f"edit_team_size_{r['id']}"
            ),
            InlineKeyboardButton(
                text=f"❌ Отменить",
                callback_data=f"pre_cancel_reg_{r['id']}"
            ),
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
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


# ── Редактирование количества игроков ─────────────────────────

@router.callback_query(F.data.startswith("edit_team_size_"))
async def edit_team_size_start(callback: CallbackQuery, state: FSMContext, db):
    registration_id = int(callback.data.split("_")[-1])
    reg = db.get_registration_by_id(registration_id)
    if not reg:
        await callback.answer("Регистрация не найдена.", show_alert=True)
        return
    if reg["status"] == "cancelled":
        await callback.answer("Регистрация уже отменена.", show_alert=True)
        return

    await state.set_state(EditTeamSizeState.waiting_size)
    await state.update_data(registration_id=registration_id, team_name=reg["team_name"])

    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_edit_team_size")
    ]])
    await callback.message.answer(
        f"✏️ Команда: <b>{reg['team_name']}</b>\n"
        f"Сейчас: <b>{reg['team_size']} чел.</b>\n\n"
        f"Введите новое количество игроков (число от 1 до 20):",
        reply_markup=cancel_kb
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_edit_team_size")
async def cancel_edit_team_size(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.")
    await callback.answer()


@router.message(EditTeamSizeState.waiting_size)
async def edit_team_size_save(message: Message, state: FSMContext, db, bot, admin_ids: list[int]):
    import re
    text = message.text.strip() if message.text else ""
    match = re.search(r"\d+", text)
    if not match:
        await message.answer("Пожалуйста, введите число. Например: <b>7</b>")
        return

    new_size = int(match.group())
    if new_size < 1 or new_size > 20:
        await message.answer("Количество игроков должно быть от 1 до 20.")
        return

    data = await state.get_data()
    registration_id = data["registration_id"]
    team_name = data["team_name"]
    await state.clear()

    reg = db.get_registration_by_id(registration_id)
    if not reg:
        await message.answer("Регистрация не найдена.")
        return

    old_size = reg["team_size"]
    db.update_team_size(registration_id, new_size)

    await message.answer(
        f"✅ Готово! Количество игроков обновлено.\n\n"
        f"Команда: <b>{team_name}</b>\n"
        f"Было: {old_size} чел. → Стало: <b>{new_size} чел.</b>"
    )

    # Уведомляем админов
    admin_text = (
        f"✏️ <b>Изменение кол-ва игроков</b>\n\n"
        f"Команда: <b>{team_name}</b>\n"
        f"Игра: {reg['title'] or '—'}\n"
        f"Было: {old_size} → Стало: <b>{new_size}</b>\n"
        f"User: @{message.from_user.username or 'без username'} ({message.from_user.id})"
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
