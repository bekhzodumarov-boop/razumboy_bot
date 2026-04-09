from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from states import ConfirmPlayersState

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
        await message.answer("У вас пока нет активных регистраций.")
        return

    from handlers.common import format_date_short
    lines = ["<b>Ваши актуальные регистрации:</b>\n"]
    for i, r in enumerate(regs, 1):
        date_short = format_date_short(r["event_date"])
        lines.append(
            f"{i}. <b>{r['title']}</b>\n"
            f"   📅 {date_short} в {r['event_time']}\n"
            f"   📍 {r['location']}\n"
            f"   👥 Команда: {r['team_name']} ({r['team_size']} чел.)\n"
        )

    await message.answer("\n".join(lines))


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
