import re
from analytics import begin_attempt, emit
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


def _team_name_kb(prev_name: str = None):
    buttons = []
    if prev_name:
        buttons.append([InlineKeyboardButton(
            text=f"📋 {prev_name}",
            callback_data="reg_use_prev_team"
        )])
    buttons.append([InlineKeyboardButton(text="👤 Я без команды", callback_data="reg_no_team")])
    buttons.append([CANCEL_BTN])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _prev_val_kb(callback_data: str, label: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=callback_data)],
        [CANCEL_BTN],
    ])


def _phone_kb(prev_phone: str = None):
    buttons = []
    if prev_phone:
        buttons.append([InlineKeyboardButton(
            text=f"📞 {prev_phone}",
            callback_data="reg_use_prev_phone"
        )])
    buttons.append([CANCEL_BTN])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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

def _prev_hint(prev) -> str:
    return "\n<i>Или выберите данные с прошлого раза:</i>" if prev else ""


def _load_prev(state_data: dict, prev):
    """Сохранить все прошлые данные в FSM state при старте регистрации."""
    if prev:
        state_data["prev_team"] = prev["team_name"] or ""
        state_data["prev_size"] = prev["team_size"]
        state_data["prev_captain"] = prev["captain_name"]
        state_data["prev_phone"] = prev["phone"]
        state_data["prev_comment"] = prev["comment"] or ""
    return state_data


def _resume_kb(event_id, attempt, can_resume=True):
    rows = []
    if can_resume:
        rows.append([InlineKeyboardButton(text="▶️ Продолжить регистрацию",
                     callback_data=f"reg_resume_{event_id}_{attempt}")])
    rows.append([InlineKeyboardButton(text="🔄 Начать заново",
                 callback_data=f"reg_restart_{event_id}_{attempt}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _valid_progress(current, data):
    steps = ['team_name', 'team_size', 'captain_name', 'phone', 'comment', 'choose_event', 'confirm']
    step = (current or '').removeprefix('RegistrationState:')
    if current != f'RegistrationState:{step}' or step not in steps or not data.get('attempt_id'):
        return False
    required = ['team_name', 'team_size', 'captain_name', 'phone', 'comment'][:min(steps.index(step), 5)]
    if any(key not in data for key in required):
        return False
    if 'team_name' in required and not isinstance(data['team_name'], str):
        return False
    if 'team_size' in required and (type(data['team_size']) is not int or not 1 <= data['team_size'] <= 12):
        return False
    if 'captain_name' in required and (not isinstance(data['captain_name'], str) or len(data['captain_name'].strip()) < 2):
        return False
    if 'phone' in required and (not isinstance(data['phone'], str) or not PHONE_RE.fullmatch(data['phone'])):
        return False
    if 'comment' in required and not isinstance(data['comment'], str):
        return False
    return step != 'confirm' or type(data.get('event_id')) is int


async def _offer_resume(message, state, event_id):
    data = await state.get_data()
    valid = _valid_progress(await state.get_state(), data)
    await message.answer(
        "📝 Вы уже начали регистрацию на эту игру. Продолжите заполнение или начните заново"
        if valid else "Сохранённая форма неполная или устарела. Безопасно начните регистрацию заново.",
        reply_markup=_resume_kb(event_id, data.get('attempt_id') or 'lost', valid))


async def _registration_available(callback, db, event_id):
    event = db.get_event_by_id(event_id)
    if not event or event['status'] != 'open':
        await callback.message.answer("Игра закрыта, отменена или больше недоступна для регистрации.")
        return False
    user = db.get_user_by_telegram_id(callback.from_user.id)
    if user and db.has_active_registration(event_id, user['id']):
        await callback.message.answer("Вы уже зарегистрированы. Посмотреть, изменить или отменить заявку можно в «🗂 Мои регистрации».")
        return False
    return True


async def _repeat_prompt(message, state, db, admin_ids, user_id):
    data = await state.get_data()
    step = (await state.get_state()).split(':')[-1]
    if step == 'team_name':
        await message.answer("Введите название команды:" + _prev_hint(data.get('prev_team')),
                             reply_markup=_team_name_kb(data.get('prev_team')))
    elif step in {'team_size', 'captain_name'}:
        previous, callback, label, prompt = (
            ('prev_size', 'reg_use_prev_size', '👥', 'Сколько будет игроков? Введите число от 1 до 12.')
            if step == 'team_size' else
            ('prev_captain', 'reg_use_prev_captain', '👤', 'Введите имя капитана:'))
        value = data.get(previous)
        await message.answer(prompt, reply_markup=_prev_val_kb(callback, f'{label} {value}') if value else _cancel_kb())
    elif step == 'phone':
        await message.answer("Укажите телефон капитана: +998XXXXXXXXX или поделитесь контактом.", reply_markup=phone_request_kb())
        await message.answer("Или выберите:", reply_markup=_phone_kb(data.get('prev_phone')))
    elif step == 'comment':
        await message.answer("Комментарий к заявке (необязательно). Если нет — напишите: -",
                             reply_markup=main_menu(user_id in admin_ids))
        previous = data.get('prev_comment')
        await message.answer("Или выберите:", reply_markup=_prev_val_kb('reg_use_prev_comment', f'💬 {previous}') if previous else _cancel_kb())
    elif step == 'choose_event':
        buttons = [[InlineKeyboardButton(text=f"📅 {format_date_short(e['event_date'])} — {e['title']}",
                    callback_data=f"reg_pick_event_{e['id']}")] for e in db.get_open_events()]
        await message.answer("На какую игру хотите зарегистрироваться?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons + [[CANCEL_BTN]]))
    else:
        await _show_summary(message, state, data)


@router.callback_query(F.data.startswith('reg_resume_') | F.data.startswith('reg_restart_'))
async def resume_registration(callback: CallbackQuery, state: FSMContext, db, admin_ids: list[int], analytics=None):
    try:
        _, action, raw_event, token = callback.data.split('_', 3)
        event_id = int(raw_event)
    except (ValueError, TypeError):
        await callback.answer("Кнопка устарела. Откройте карточку игры снова.", show_alert=True)
        return
    if not await _registration_available(callback, db, event_id):
        await callback.answer()
        return
    data = await state.get_data()
    attempt = data.get('attempt_id')
    if not attempt and token != 'lost' and not await state.get_state():
        await _offer_resume(callback.message, state, event_id)
    elif token != (attempt or 'lost') or data.get('event_id') not in (None, event_id):
        await callback.message.answer("Эта кнопка относится к прежней форме. Откройте карточку игры снова.")
    elif action == 'resume':
        if _valid_progress(await state.get_state(), data):
            await _repeat_prompt(callback.message, state, db, admin_ids, callback.from_user.id)
        else:
            await _offer_resume(callback.message, state, event_id)
    else:
        # begin_attempt records the old attempt as superseded, never handler_error.
        if await begin_attempt(state, analytics, callback.from_user.id, event_id,
                               delivery_key=f'callback:{callback.id}'):
            await state.update_data(**_load_prev({}, db.get_last_registration_by_telegram(callback.from_user.id)))
            await state.set_state(RegistrationState.team_name)
            await _repeat_prompt(callback.message, state, db, admin_ids, callback.from_user.id)
    await callback.answer()


@router.message(F.text == "📝 Регистрация")
async def start_registration(message: Message, state: FSMContext, db, analytics=None):
    events = db.get_open_events()
    if not events:
        emit(analytics, 'registration_failed', message.from_user.id, {}, 'start',
             'unavailable', key=f'unavailable:{message.chat.id}:{message.message_id}')
        await message.answer("Сейчас нет открытых игр для регистрации.")
        return
    prev = db.get_last_registration_by_telegram(message.from_user.id)
    if not await begin_attempt(state, analytics, message.from_user.id,
                               delivery_key=f'message:{message.chat.id}:{message.message_id}'):
        return
    await state.update_data(**_load_prev({}, prev))
    await state.set_state(RegistrationState.team_name)
    prev_name = prev["team_name"] if prev and prev["team_name"] else None
    await message.answer(
        "Введите название команды:" + _prev_hint(prev_name),
        reply_markup=_team_name_kb(prev_name)
    )


@router.callback_query(F.data.startswith("register_event_"))
async def register_from_event(callback: CallbackQuery, state: FSMContext, db, analytics=None):
    try:
        event_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Некорректная ссылка на игру.", show_alert=True)
        return
    event = db.get_event_by_id(event_id)
    if not event or event["status"] != "open":
        emit(analytics, 'registration_failed', callback.from_user.id,
             {'event_id': event_id}, 'start', 'unavailable', key=f'unavailable:{callback.id}')
        await callback.message.answer("Эта игра недоступна для регистрации.")
        await callback.answer()
        return
    if not await _registration_available(callback, db, event_id):
        await callback.answer()
        return
    prev = db.get_last_registration_by_telegram(callback.from_user.id)
    # A repeated click while already filling this game must not reset the form.
    existing = await state.get_data()
    current = await state.get_state()
    if (existing.get('event_id') == event_id or
            existing.get('event_id') is None and
            (existing.get('attempt_id') or current and current.startswith('RegistrationState:'))):
        await _offer_resume(callback.message, state, event_id)
        await callback.answer()
        return
    if not await begin_attempt(state, analytics, callback.from_user.id, event_id,
                               delivery_key=f'callback:{callback.id}'):
        await callback.answer()
        return
    await state.update_data(event_id=event_id, **_load_prev({}, prev))
    await state.set_state(RegistrationState.team_name)
    prev_name = prev["team_name"] if prev and prev["team_name"] else None
    await callback.message.answer(
        "Введите название команды:" + _prev_hint(prev_name),
        reply_markup=_team_name_kb(prev_name)
    )
    await callback.answer()


# ── Использовать прошлое название команды ─────────────────────

@router.callback_query(F.data == "reg_use_prev_team", RegistrationState.team_name)
async def reg_use_prev_team(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prev_name = data.get("prev_team", "")
    if not prev_name:
        await callback.answer("Прошлые данные не найдены.", show_alert=True)
        return
    await state.update_data(team_name=prev_name)
    prev_size = data.get("prev_size")
    size_hint = f"\n<i>Прошлый раз: {prev_size} чел.</i>" if prev_size else ""
    await state.set_state(RegistrationState.team_size)
    await callback.message.answer(
        f"Команда: <b>{prev_name}</b> ✅\n\nСколько будет игроков? Введите число от 1 до 12." + size_hint,
        reply_markup=_prev_val_kb("reg_use_prev_size", f"👥 {prev_size} чел.") if prev_size else _cancel_kb()
    )
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

@router.callback_query(F.data == "reg_use_prev_size", RegistrationState.team_size)
async def reg_use_prev_size(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prev_size = data.get("prev_size")
    if not prev_size:
        await callback.answer("Прошлые данные не найдены.", show_alert=True)
        return
    await state.update_data(team_size=prev_size)
    prev_captain = data.get("prev_captain", "")
    await state.set_state(RegistrationState.captain_name)
    await callback.message.answer(
        f"Игроков: <b>{prev_size}</b> ✅\n\nВведите имя капитана:" + _prev_hint(prev_captain),
        reply_markup=_prev_val_kb("reg_use_prev_captain", f"👤 {prev_captain}") if prev_captain else _cancel_kb()
    )
    await callback.answer()


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
    data = await state.get_data()
    prev_captain = data.get("prev_captain", "")
    await state.set_state(RegistrationState.captain_name)
    await message.answer(
        "Введите имя капитана:" + _prev_hint(prev_captain),
        reply_markup=_prev_val_kb("reg_use_prev_captain", f"👤 {prev_captain}") if prev_captain else _cancel_kb()
    )


# ── Шаг 3: имя капитана ────────────────────────────────────────

@router.callback_query(F.data == "reg_use_prev_captain", RegistrationState.captain_name)
async def reg_use_prev_captain(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prev_captain = data.get("prev_captain", "")
    if not prev_captain:
        await callback.answer("Прошлые данные не найдены.", show_alert=True)
        return
    await state.update_data(captain_name=prev_captain)
    prev_phone = data.get("prev_phone", "")
    await state.set_state(RegistrationState.phone)
    await callback.message.answer(
        f"Капитан: <b>{prev_captain}</b> ✅\n\n"
        "Укажите номер телефона капитана.\n"
        "Нажмите кнопку ниже или введите вручную в формате <b>+998XXXXXXXXX</b>:" + _prev_hint(prev_phone),
        reply_markup=phone_request_kb()
    )
    await callback.message.answer("Или выберите:", reply_markup=_phone_kb(prev_phone))
    await callback.answer()


@router.message(RegistrationState.captain_name)
async def reg_captain_name(message: Message, state: FSMContext):
    captain_name = message.text.strip()
    if len(captain_name) < 2:
        await message.answer("Слишком короткое имя. Введите ещё раз:", reply_markup=_cancel_kb())
        return
    await state.update_data(captain_name=captain_name)
    data = await state.get_data()
    prev_phone = data.get("prev_phone", "")
    await state.set_state(RegistrationState.phone)
    await message.answer(
        "Укажите номер телефона капитана.\n"
        "Нажмите кнопку ниже или введите вручную в формате <b>+998XXXXXXXXX</b>:" + _prev_hint(prev_phone),
        reply_markup=phone_request_kb()
    )
    await message.answer("Или выберите:", reply_markup=_phone_kb(prev_phone))


# ── Использовать прошлый телефон ──────────────────────────────

@router.callback_query(F.data == "reg_use_prev_phone", RegistrationState.phone)
async def reg_use_prev_phone(callback: CallbackQuery, state: FSMContext, admin_ids: list[int]):
    data = await state.get_data()
    prev_phone = data.get("prev_phone", "")
    prev_comment = data.get("prev_comment", "")
    if not prev_phone:
        await callback.answer("Прошлые данные не найдены.", show_alert=True)
        return
    await state.update_data(phone=prev_phone)
    await state.set_state(RegistrationState.comment)
    await callback.message.answer(
        f"Телефон: <b>{prev_phone}</b> ✅\n\n"
        "Комментарий к заявке (необязательно). Если нет — напишите: <b>-</b>" + _prev_hint(prev_comment),
        reply_markup=main_menu(callback.from_user.id in admin_ids)
    )
    comment_kb = _prev_val_kb("reg_use_prev_comment", f"💬 {prev_comment}") if prev_comment else _cancel_kb()
    await callback.message.answer("Или выберите:", reply_markup=comment_kb)
    await callback.answer()


# ── Шаг 4: телефон ─────────────────────────────────────────────

@router.message(RegistrationState.phone, F.contact)
async def reg_phone_contact(message: Message, state: FSMContext, admin_ids: list[int]):
    phone_raw = message.contact.phone_number
    phone = phone_raw if phone_raw.startswith("+") else f"+{phone_raw}"
    await state.update_data(phone=phone)
    data = await state.get_data()
    prev_comment = data.get("prev_comment", "")
    await state.set_state(RegistrationState.comment)
    await message.answer(
        "Комментарий к заявке (необязательно). Если нет — напишите: <b>-</b>" + _prev_hint(prev_comment),
        reply_markup=main_menu(message.from_user.id in admin_ids)
    )
    comment_kb = _prev_val_kb("reg_use_prev_comment", f"💬 {prev_comment}") if prev_comment else _cancel_kb()
    await message.answer("Или выберите:", reply_markup=comment_kb)


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
    data = await state.get_data()
    prev_comment = data.get("prev_comment", "")
    await state.set_state(RegistrationState.comment)
    await message.answer(
        "Комментарий к заявке (необязательно). Если нет — напишите: <b>-</b>" + _prev_hint(prev_comment),
        reply_markup=main_menu(message.from_user.id in admin_ids)
    )
    comment_kb = _prev_val_kb("reg_use_prev_comment", f"💬 {prev_comment}") if prev_comment else _cancel_kb()
    await message.answer("Или выберите:", reply_markup=comment_kb)


# ── Использовать прошлый комментарий ─────────────────────────

@router.callback_query(F.data == "reg_use_prev_comment", RegistrationState.comment)
async def reg_use_prev_comment(callback: CallbackQuery, state: FSMContext, db):
    data = await state.get_data()
    prev_comment = data.get("prev_comment", "")
    await state.update_data(comment=prev_comment)
    data = await state.get_data()
    if data.get("event_id"):
        await _show_summary(callback.message, state, data)
    else:
        events = db.get_open_events()
        if not events:
            await callback.message.answer("К сожалению, сейчас нет открытых игр.")
            await state.clear()
        else:
            buttons = []
            for event in events:
                date_short = format_date_short(event["event_date"])
                buttons.append([InlineKeyboardButton(
                    text=f"📅 {date_short} — {event['title']}",
                    callback_data=f"reg_pick_event_{event['id']}"
                )])
            buttons.append([CANCEL_BTN])
            await state.set_state(RegistrationState.choose_event)
            await callback.message.answer("На какую игру хотите зарегистрироваться?",
                                          reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


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
    if await state.get_state() != RegistrationState.confirm.state:
        await callback.answer('Форма устарела. Начните регистрацию заново.', show_alert=True)
        return
    data = await state.get_data()
    event_id = data.get("event_id")
    attempt_id = data.get("attempt_id")
    await state.clear()
    await state.update_data(attempt_id=attempt_id,
                            attempt_source=data.get('attempt_source', 'unknown'),
                            attempt_revision=data.get('attempt_revision', 0) + 1)
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
async def confirm_registration(callback: CallbackQuery, state: FSMContext, db, bot, admin_ids: list[int], analytics=None):
    data = await state.get_data()
    if not all(k in data for k in ('event_id', 'team_name', 'team_size', 'captain_name', 'phone')):
        emit(analytics, 'registration_failed', callback.from_user.id, data, 'confirm',
             'state_lost', key=f'state_lost:{callback.from_user.id}:{callback.message.message_id}')
        await callback.answer('Форма устарела. Начните регистрацию заново.', show_alert=True)
        return
    event_id = data["event_id"]

    event = db.get_event_by_id(event_id)
    if not event or event['status'] != 'open':
        emit(analytics, 'registration_failed', callback.from_user.id, data, 'confirm', 'unavailable')
        await callback.message.answer("Игра закрыта или отменена. Подтвердить регистрацию нельзя.")
        await callback.answer()
        return

    user_row = db.get_user_by_telegram_id(callback.from_user.id)
    if not user_row:
        emit(analytics, 'registration_failed', callback.from_user.id, data, 'confirm', 'user_missing')
        await callback.message.answer("Ошибка: пользователь не найден. Нажмите /start и попробуйте снова.")
        await callback.answer()
        return

    if db.has_active_registration(event_id, user_row["id"]):
        emit(analytics, 'registration_failed', callback.from_user.id, data, 'confirm', 'duplicate')
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
    emit(analytics, 'registration_completed', callback.from_user.id, data, 'confirm',
         key=f"{data.get('attempt_id')}:terminal")

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
