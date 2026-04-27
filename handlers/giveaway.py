"""
handlers/giveaway.py — Розыгрыш бесплатных проходок

Две функции вызываются APScheduler-ом из app.py:
  - giveaway_announce(bot, db, admin_ids)  — в 20:50, рассылает объявление
  - giveaway_draw(bot, db, admin_ids)      — в 21:00, выбирает победителей
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

async def giveaway_announce(bot, db, admin_ids: list):
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

async def giveaway_draw(bot, db, admin_ids: list):
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

async def check_giveaway_schedule(bot, db, admin_ids: list):
    """Проверяет расписание и запускает announce/draw в нужное время."""
    settings = db.get_giveaway_settings()
    if not settings or not settings["active"]:
        return

    now = _now_hhmm()

    if now == settings["announce_time"]:
        await giveaway_announce(bot, db, admin_ids)
    elif now == settings["draw_time"]:
        await giveaway_draw(bot, db, admin_ids)


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
