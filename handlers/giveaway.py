"""
handlers/giveaway.py — Розыгрыш бесплатных проходок

Две функции вызываются APScheduler-ом из app.py:
  - giveaway_announce(bot, db, admin_ids, channel_id)  — в 20:30, рассылает объявление
  - giveaway_draw(bot, db, admin_ids, channel_id)      — в 21:00, выбирает победителей
"""

import random
import datetime
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)
router = Router()

TASHKENT_OFFSET = datetime.timezone(datetime.timedelta(hours=5))


def _today() -> str:
    return datetime.datetime.now(tz=TASHKENT_OFFSET).strftime("%Y-%m-%d")


def _now_hhmm() -> str:
    return datetime.datetime.now(tz=TASHKENT_OFFSET).strftime("%H:%M")


# ── Рассылка объявления ────────────────────────────────────────

async def giveaway_announce(bot, db, admin_ids: list, channel_id: int = 0):
    settings = db.get_giveaway_settings()
    if not settings or not settings["active"]:
        return

    today = _today()
    session = db.get_giveaway_session(today)
    if session and session["status"] != "pending":
        return  # уже запускали сегодня

    session_id = db.create_giveaway_session(today)

    announce_text = settings["announce_text"] or (
        "🎉 Скоро часики пробьют 9, значит пришло время принять участие "
        "в нашем розыгрыше бесплатных проходок на Разумбой!\n\n"
        "Нажмите кнопку ниже, чтобы участвовать 👇"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Участвую!",
            callback_data=f"giveaway_join_{session_id}"
        )
    ]])

    subscribers = db.get_subscribers()
    sent_count = 0
    for user in subscribers:
        try:
            if settings["image_file_id"]:
                await bot.send_photo(
                    user["telegram_id"],
                    photo=settings["image_file_id"],
                    caption=announce_text,
                    reply_markup=kb,
                )
            else:
                await bot.send_message(
                    user["telegram_id"],
                    announce_text,
                    reply_markup=kb,
                )
            sent_count += 1
        except Exception as e:
            logger.warning(f"giveaway_announce: не удалось отправить {user['telegram_id']}: {e}")

    db.update_session_status(session_id, "announced", sent_count=sent_count)

    # Дублируем объявление в канал
    if channel_id:
        try:
            if settings["image_file_id"]:
                await bot.send_photo(
                    channel_id,
                    photo=settings["image_file_id"],
                    caption=announce_text,
                    reply_markup=kb,
                )
            else:
                await bot.send_message(channel_id, announce_text, reply_markup=kb)
            logger.info(f"giveaway_announce: объявление отправлено в канал {channel_id}")
        except Exception as e:
            logger.warning(f"giveaway_announce: не удалось отправить в канал {channel_id}: {e}")

    # Статистика для админов
    participants_count = db.count_giveaway_participants(session_id)
    stats = (
        f"📊 <b>Розыгрыш запущен!</b>\n\n"
        f"📨 Отправлено: <b>{sent_count}</b> подписчикам\n"
        f"✅ Участвуют сейчас: <b>{participants_count}</b>\n\n"
        f"Жеребьёвка в {settings['draw_time']} — результаты придут сюда."
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, stats)
        except Exception:
            pass


# ── Жеребьёвка ────────────────────────────────────────────────

async def giveaway_draw(bot, db, admin_ids: list, channel_id: int = 0):
    settings = db.get_giveaway_settings()
    if not settings or not settings["active"]:
        return

    today = _today()
    session = db.get_giveaway_session(today)
    if not session or session["status"] != "announced":
        return  # объявления не было или жеребьёвка уже прошла

    session_id = session["id"]
    participants = db.get_giveaway_participants(session_id)
    participants_count = len(participants)

    if participants_count == 0:
        # Никто не участвовал
        no_participants_text = (
            "😔 К сожалению, никто не принял участие в сегодняшнем розыгрыше.\n\n"
            "Мы обязательно разыграем проходки в следующий раз! 🎟"
        )
        subscribers = db.get_subscribers()
        for user in subscribers:
            try:
                await bot.send_message(user["telegram_id"], no_participants_text)
            except Exception:
                pass

        # Дублируем в канал
        if channel_id:
            try:
                await bot.send_message(channel_id, no_participants_text)
            except Exception as e:
                logger.warning(f"giveaway_draw: не удалось отправить в канал {channel_id}: {e}")

        db.update_session_status(session_id, "done")

        for admin_id in admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    f"⚠️ Жеребьёвка завершена.\n"
                    f"Участников: 0 из {session['sent_count']} получивших."
                )
            except Exception:
                pass
        return

    winners_count = min(settings["winners_count"], participants_count)
    winners = random.sample(list(participants), winners_count)

    # Формируем упоминания победителей
    def mention(p) -> str:
        if p["username"]:
            return f"@{p['username']}"
        return p["full_name"] or f"id{p['telegram_id']}"

    winner_mentions = [mention(w) for w in winners]

    # Текст поздравления
    congrats_template = settings["congrats_text"] or (
        "🎉 Сегодня Рандомбой выбрал {winners}!\n\n"
        "Вы получаете бесплатные пригласительные на игру Razumboy 🎟\n\n"
        "Наш менеджер свяжется с вами в ближайшее время."
    )

    if "{winners}" in congrats_template:
        winners_str = " и ".join(winner_mentions)
        congrats_text = congrats_template.replace("{winners}", winners_str)
    else:
        congrats_text = congrats_template + "\n\n" + " и ".join(winner_mentions)

    # Рассылаем всем подписчикам
    subscribers = db.get_subscribers()
    for user in subscribers:
        try:
            await bot.send_message(user["telegram_id"], congrats_text)
        except Exception:
            pass

    # Дублируем результаты в канал
    if channel_id:
        try:
            await bot.send_message(channel_id, congrats_text)
            logger.info(f"giveaway_draw: результаты отправлены в канал {channel_id}")
        except Exception as e:
            logger.warning(f"giveaway_draw: не удалось отправить в канал {channel_id}: {e}")

    # Сохраняем победителей в таблицу giveaway_winners
    for w in winners:
        db.save_giveaway_winner(w["telegram_id"], w["username"], w["full_name"])

    db.update_session_status(session_id, "done")

    # Статистика для админов
    stats = (
        f"🏆 <b>Жеребьёвка завершена!</b>\n\n"
        f"📨 Получили объявление: <b>{session['sent_count']}</b>\n"
        f"✅ Приняли участие: <b>{participants_count}</b>\n"
        f"🎟 Победители: {', '.join(winner_mentions)}"
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, stats)
        except Exception:
            pass


# ── Проверка расписания (вызывается каждую минуту из APScheduler) ──

def _today_weekday() -> int:
    """0=Пн, 6=Вс — в ташкентском времени."""
    return datetime.datetime.now(tz=TASHKENT_OFFSET).weekday()


async def check_giveaway_schedule(bot, db, admin_ids: list, channel_id: int = 0):
    """Проверяет расписание и запускает announce/draw в нужное время."""
    settings = db.get_giveaway_settings()
    if not settings or not settings["active"]:
        return

    # Проверяем день недели
    active_days = settings["active_days"] if settings["active_days"] else "0,1,2,3,4,5,6"
    today_wd = str(_today_weekday())
    if today_wd not in active_days.split(","):
        return  # сегодня розыгрыш не проводится

    now = _now_hhmm()

    if now == settings["announce_time"]:
        await giveaway_announce(bot, db, admin_ids, channel_id)
    elif now == settings["draw_time"]:
        await giveaway_draw(bot, db, admin_ids, channel_id)


# ── Callback: пользователь нажал «Участвую» ───────────────────

@router.callback_query(F.data.startswith("giveaway_join_"))
async def giveaway_join(callback: CallbackQuery, db):
    session_id = int(callback.data.split("_")[-1])
    session = db.get_giveaway_session_by_id(session_id)

    if not session or session["status"] != "announced":
        await callback.answer("⏰ Регистрация на этот розыгрыш уже закрыта.", show_alert=True)
        return

    user = callback.from_user
    added = db.add_giveaway_participant(
        session_id=session_id,
        telegram_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "",
    )

    if added:
        await callback.answer("✅ Вы участвуете в розыгрыше! Удачи! 🍀", show_alert=True)
    else:
        await callback.answer("Вы уже зарегистрированы 😊", show_alert=True)


# ── Пятничная рассылка победителям ────────────────────────────

WINNER_REMINDER_TEXT = (
    "🎲 Добрый вечер! Рандомбой сделал свой выбор! И вы победили в розыгрыше "
    "бесплатной проходки на Razumboy: стреляй и пой в эту пятницу\n\n"
    "✍️ Подтвердите пожалуйста своё участие и напишите название своей команды"
)


def _winner_reminder_kb(date_compact: str) -> InlineKeyboardMarkup:
    """date_compact — дата без дефисов: YYYYMMDD"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Да, приму участие",
            callback_data=f"winner_yes_{date_compact}"
        )],
        [InlineKeyboardButton(
            text="❌ К сожалению, не смогу принять участие",
            callback_data=f"winner_no_{date_compact}"
        )],
    ])


def _format_admin_winner_list(responses, reminder_date: str) -> str:
    """Форматирует список победителей с иконками статуса для админа."""
    icons = {"pending": "⏳", "confirmed": "✅", "declined": "❌"}
    lines = [f"🎟 <b>Победители Рандомбой ({reminder_date}):</b>\n"]
    for r in responses:
        icon = icons.get(r["status"], "⏳")
        mention = f"@{r['username']}" if r["username"] else r["full_name"] or f"id{r['telegram_id']}"
        line = f"{icon} {mention}"
        if r["status"] == "confirmed" and r["team_name"]:
            line += f" — {r['team_name']}"
        lines.append(line)
    return "\n".join(lines)


async def send_friday_winner_reminders(bot, db, admin_ids: list):
    """Рассылка победителям Рандомбой за последние 5 дней — каждый четверг в 21:10."""
    winners = db.get_giveaway_winners_since(days=5)
    if not winners:
        logger.info("send_friday_winner_reminders: победителей за 5 дней нет")
        return

    today = _today()
    date_compact = today.replace("-", "")  # YYYYMMDD

    sent = 0
    for w in winners:
        # Создаём запись ответа со статусом pending
        db.create_winner_reminder_response(
            telegram_id=w["telegram_id"],
            username=w["username"],
            full_name=w["full_name"],
            reminder_date=today,
        )
        try:
            await bot.send_message(
                w["telegram_id"],
                WINNER_REMINDER_TEXT,
                reply_markup=_winner_reminder_kb(date_compact),
            )
            sent += 1
        except Exception as e:
            logger.warning(f"send_friday_winner_reminders: не удалось отправить {w['telegram_id']}: {e}")

    # Отправляем список победителей админам
    responses = db.get_winner_reminder_responses(today)
    admin_msg = _format_admin_winner_list(responses, today)
    admin_msg += f"\n\n📩 Отправлено: {sent} из {len(winners)}"
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, admin_msg)
        except Exception:
            pass


# ── Callbacks ответа победителя ────────────────────────────────

@router.callback_query(F.data.startswith("winner_yes_"))
async def winner_confirm_yes(callback: CallbackQuery, state):
    """Победитель подтверждает участие — переводим в FSM для получения названия команды."""
    from states import WinnerConfirmState
    date_compact = callback.data.split("winner_yes_")[1]
    reminder_date = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:8]}"
    await state.set_state(WinnerConfirmState.team_name)
    await state.update_data(reminder_date=reminder_date)
    await callback.message.answer(
        "Отлично! Напишите, пожалуйста, <b>название вашей команды</b>:"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("winner_no_"))
async def winner_confirm_no(callback: CallbackQuery, db, bot, admin_ids: list):
    date_compact = callback.data.split("winner_no_")[1]
    reminder_date = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:8]}"

    db.update_winner_reminder_response(
        telegram_id=callback.from_user.id,
        reminder_date=reminder_date,
        status="declined",
    )

    await callback.message.answer(
        "Жаль! Ничего страшного. Удачи в следующий раз! 🍀\n\n"
        "Если передумаете — напишите @razumboy."
    )
    await callback.answer()

    # Обновляем список у админов
    responses = db.get_winner_reminder_responses(reminder_date)
    admin_msg = _format_admin_winner_list(responses, reminder_date)
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, admin_msg)
        except Exception:
            pass
