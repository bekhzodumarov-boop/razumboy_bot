"""Private admin attendance, payment totals and per-game expense editing."""
import asyncio
import html
import logging
import secrets
import sqlite3

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from finance import FinanceStore, FinanceError, METHODS, export_csv, format_report, money, parse_integer

log = logging.getLogger(__name__)


class FinanceState(StatesGroup):
    value = State()
    amount = State()
    confirm = State()


class AdminPrivate(BaseFilter):
    async def __call__(self, event, admin_ids):
        msg = getattr(event, 'message', None) or event
        allowed = event.from_user.id in admin_ids and getattr(getattr(msg, 'chat', None), 'type', None) == 'private'
        if not allowed and hasattr(event, 'data'):
            await event.answer('Доступно только администратору в личном чате', show_alert=True)
        return allowed




def esc(value):
    return html.escape(str(value))


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label[:60], callback_data=data) for label, data in row] for row in rows])


async def store_call(db, method, *args):
    # SQLite is off the polling loop. Store is constructed only on admin entry.
    def run():
        return getattr(FinanceStore(db.db_path), method)(*args)
    return await asyncio.to_thread(run)


async def games_page(message, db, page=0):
    rows = await store_call(db, 'games', page)
    buttons = [[(f"{e['event_date']} · {e['title']}", f"af:g:{e['id']}")] for e in rows[:10]]
    nav = []
    if page:
        nav.append(('◀️', f'af:list:{page-1}'))
    if len(rows) > 10:
        nav.append(('▶️', f'af:list:{page+1}'))
    if nav:
        buttons.append(nav)
    await message.answer('👥 <b>Явка, оплаты и расходы</b>\nВыберите игру. Прошедшие игры тоже доступны.\nОплаты отмечаются админом вручную, без проверки банков.', reply_markup=kb(buttons) if buttons else None)


async def game_page(message, db, event_id, page=0):
    await store_call(db, 'prepare', event_id)
    s = await store_call(db, 'snapshot', event_id)
    teams = s['teams'][page*10:page*10+10]
    buttons = []
    for t in teams:
        actual = '?' if t['actual_players'] is None else str(t['actual_players'])
        booked = 'без заявки' if t['registration_id'] is None else f"заявлено {t['booked_players']}"
        status = ' · заявка отменена' if t['booking_status'] == 'cancelled' else ''
        buttons.append([(f"{t['name']} · пришло {actual} · {booked}{status}", f"af:t:{t['id']}")])
    nav = []
    if page:
        nav.append(('◀️', f'af:g:{event_id}:{page-1}'))
    if (page+1)*10 < len(s['teams']):
        nav.append(('▶️', f'af:g:{event_id}:{page+1}'))
    if nav:
        buttons.append(nav)
    buttons += [[('➕ Команда без заявки', f'af:newteam:{event_id}')],
                [('💵 Цена билета', f'af:price:{event_id}'), ('🧾 Расходы', f'af:expenses:{event_id}:0')],
                [('🤝 Распределение прибыли', f'af:distributions:{event_id}:0')],
                [('📊 Итоги игры', f'af:report:{event_id}'), ('📥 CSV', f'af:csv:{event_id}')],
                [('🔙 Игры', 'af:list:0')]]
    price = s['settings'].get('ticket_uzs')
    await message.answer(f"👥 <b>{esc(s['event']['title'])}</b> · {esc(s['event']['event_date'])}\n"
                         f"Заявки: {s['registered_teams']} / {s['registered_players']} чел.\n"
                         f"Явка: {s['arrived_teams']} / {s['actual_players']} чел. · не отмечено {s['unknown_teams']}\n"
                         f"Поступления: {money(s['income_uzs'])}\n"
                         f"Цена билета для подсказки: {money(price) if price is not None else 'не задана'}\n"
                         'Выберите команду, чтобы отметить явку и оплаты', reply_markup=kb(buttons))


async def team_page(message, db, team_id):
    t = await store_call(db, 'team', team_id)
    actual = 'не отмечена' if t['actual_players'] is None else 'не пришли' if not t['actual_players'] else f"{t['actual_players']} чел."
    lines = [f"👥 <b>{esc(t['name'])}</b>", f'Фактическая явка: {actual}', '',
             'Итоги оплат по способам (каждый игрок учитывается один раз):']
    for method, label in METHODS.items():
        p = t['payments'].get(method, {})
        lines.append(f"{label}: {p.get('players',0)} чел. / {money(p.get('amount_uzs',0))}")
    buttons = [[('👥 Указать явку', f'af:att:{team_id}')], [('↩️ Снять отметку явки', f'af:unknown:{team_id}')]]
    buttons += [[(f'💵 {label}', f'af:pay:{team_id}:{method}')] for method, label in METHODS.items()]
    buttons += [[('🔙 К игре', f"af:g:{t['event_id']}")]]
    lines += ['', 'Запись оплаты заменяет итог выбранного способа, а не прибавляет к нему.',
              'Скидки учитывайте фактической суммой. Бесплатные места не отмечайте как оплатившие.']
    await message.answer('\n'.join(lines), reply_markup=kb(buttons))


async def expenses_page(message, db, event_id, page=0, kind='cost'):
    s = await store_call(db, 'snapshot', event_id)
    articles = [x for x in s['expenses'] if x['kind']==kind]
    rows = articles[page*8:page*8+8]
    prefix = 'expenses' if kind=='cost' else 'distributions'
    buttons = []
    for x in rows:
        status = 'не заполнено' if x['status'] == 'pending' else 'исключено' if x['status'] == 'excluded' else money(x['amount_uzs'])
        buttons.append([(f"{'Прибыль' if x['kind']=='distribution' else 'Осн.' if x['template_key'] else 'Другие'}: {x['title']} · {status}", f"af:x:{x['id']}")])
    nav = []
    if page:
        nav.append(('◀️', f'af:{prefix}:{event_id}:{page-1}'))
    if (page+1)*8 < len(articles):
        nav.append(('▶️', f'af:{prefix}:{event_id}:{page+1}'))
    if nav:
        buttons.append(nav)
    buttons += [[('➕ Другие расходы', f'af:newcost:{event_id}')]] if kind=='cost' else [[('➕ Выплата соучредителю', f'af:newdistribution:{event_id}')]]
    buttons += [[('🔙 К игре', f'af:g:{event_id}')]]
    await message.answer(('🧾 <b>Основные и другие расходы этой игры</b>' if kind=='cost' else '🤝 <b>Распределение прибыли соучредителям</b>')+'\nКаждую статью можно переименовать, изменить или исключить. Суммы не переносятся на другие игры.\n'
                         'Для ежемесячных услуг внесите только долю, отнесенную к этой игре.\n'
                         'Распределения прибыли учитываются отдельно от расходов. Рекламу из Meta повторно не добавляем автоматически.', reply_markup=kb(buttons))


async def expense_page(message, db, expense_id):
    # Resolve the event from the exact expense record without accepting user-supplied SQL.
    def read():
        with FinanceStore(db.db_path).connect() as c:
            row = c.execute('SELECT * FROM finance_expenses WHERE id=?', (expense_id,)).fetchone()
            if row is None:
                raise FinanceError('Статья не найдена')
            return dict(row)
    x = await asyncio.to_thread(read)
    value = money(x['amount_uzs']) if x['status'] == 'confirmed' else 'не заполнено' if x['status'] == 'pending' else 'исключено'
    await message.answer(f"🧾 <b>{esc(x['title'])}</b>\nТип: {'расход' if x['kind']=='cost' else 'распределение прибыли (не расход)'}\nУчтено: {value}", reply_markup=kb([
        [('✏️ Указать сумму', f'af:expense:{expense_id}')], [('✏️ Переименовать', f'af:rename:{expense_id}')],
        *([[('🔄 Изменить тип статьи', f'af:kind:{expense_id}')]] if x['template_key'] != 'farruh' else []),
        [('➖ Исключить из этой игры', f'af:exclude:{expense_id}')], [('🔙 К списку', f"af:{'expenses' if x['kind']=='cost' else 'distributions'}:{x['event_id']}:0")]]))
    return x


async def preview(message, state, draft, text):
    nonce = secrets.token_hex(6)
    await state.set_state(FinanceState.confirm)
    await state.set_data({'finance_draft': {**draft, 'nonce': nonce}})
    await message.answer(text+'\n\nСохранить?', reply_markup=kb([
        [('✅ Сохранить', f'af:save:{nonce}')], [('🔙 Отмена', 'af:cancel')]]))


async def entry(message, state: FSMContext, db):
    await state.clear()
    try:
        await games_page(message, db)
    except sqlite3.Error:
        log.warning('finance_storage_unavailable')
        await message.answer('Хранилище явки временно недоступно')


async def cancel_message(message, state: FSMContext):
    await state.clear()
    await message.answer('Ввод отменен. Сохраненные данные не менялись. Открыть: 👥 Явка')


async def callback(callback, state: FSMContext, db):
    try:
        parts = callback.data.split(':')
        action = parts[1]
        if action == 'cancel':
            await state.clear()
            await callback.answer('Ввод отменен')
            return
        if action == 'save':
            data = await state.get_data()
            d = data.get('finance_draft')
            if await state.get_state() != FinanceState.confirm.state or not d or not secrets.compare_digest(d['nonce'], parts[2]):
                raise FinanceError('Эта кнопка устарела. Откройте карточку заново')
            actor, op = callback.from_user.id, 'finance:'+d['nonce']
            kind = d['kind']
            if kind == 'attendance':
                await store_call(db, 'attendance', d['team_id'], d['players'], d['revision'], actor, op)
            elif kind == 'payment':
                await store_call(db, 'payment', d['team_id'], d['method'], d['players'], d['amount'], d['revision'], actor, op)
            elif kind == 'ticket':
                await store_call(db, 'ticket', d['event_id'], d['amount'], d['revision'], actor, op)
            elif kind == 'expense':
                await store_call(db, 'expense', d['expense_id'], d['amount'], d['status'], d['revision'], actor, op)
            elif kind == 'expense_kind':
                await store_call(db, 'expense_kind', d['expense_id'], d['expense_kind'], d['revision'], actor, op)
            elif kind == 'rename':
                await store_call(db, 'rename_expense', d['expense_id'], d['title'], d['revision'], actor, op)
            else:
                await store_call(db, 'add', d['event_id'], d['title'], kind, d.get('amount'), actor, op)
            await state.clear()
            await callback.answer('Сохранено')
            if kind in ('attendance', 'payment'):
                await team_page(callback.message, db, d['team_id'])
            elif kind in ('expense', 'expense_kind', 'rename', 'cost', 'distribution'):
                await expenses_page(callback.message, db, d['event_id'], kind=d.get('category','distribution' if kind=='distribution' else 'cost'))
            else:
                await game_page(callback.message, db, d['event_id'])
            return
        # Navigating away invalidates any previous draft and its confirm button.
        await state.clear()
        ident = int(parts[2])
        if not 0 <= ident < 2**63:
            raise FinanceError('Некорректный идентификатор')
        page = int(parts[3]) if len(parts)>3 and action in ('g','expenses','distributions') else 0
        if page < 0 or page > 100000:
            raise FinanceError('Некорректная страница')
        if action == 'list':
            await games_page(callback.message, db, ident)
        elif action == 'g':
            await game_page(callback.message, db, ident, page)
        elif action == 't':
            await team_page(callback.message, db, ident)
        elif action in ('expenses','distributions'):
            await expenses_page(callback.message, db, ident, page, kind='cost' if action=='expenses' else 'distribution')
        elif action == 'x':
            await expense_page(callback.message, db, ident)
        elif action in ('report', 'csv'):
            s = await store_call(db, 'snapshot', ident)
            if action == 'csv':
                await callback.message.answer_document(BufferedInputFile(export_csv(s), filename=f'game_{ident}_finance.csv'), caption='Явка, оплаты и расходы. Только ручной учет в UZS')
            else:
                await callback.message.answer(format_report(s))
        elif action in ('att','unknown','pay'):
            t = await store_call(db, 'team', ident)
            d = {'team_id': ident, 'event_id': t['event_id'], 'revision': t['revision']}
            if action == 'unknown':
                await preview(callback.message, state, {**d,'kind':'attendance','players':None}, 'Снять отметку явки? Оплаты должны быть предварительно обнулены')
            else:
                if action == 'pay':
                    method = parts[3]
                    if method not in METHODS:
                        raise FinanceError('Неизвестный способ оплаты')
                    if t['actual_players'] is None:
                        raise FinanceError('Сначала укажите фактическую явку')
                    d.update(kind='payment',method=method)
                    p = t['payments'].get(method,{})
                    prompt = f"{METHODS[method]}: сейчас {p.get('players',0)} чел. / {money(p.get('amount_uzs',0))}\nВведите ИТОГОВОЕ число оплативших этим способом. Оно заменит прежнее, не прибавится. 0 — обнулить. Каждый игрок считается только в одном способе"
                else:
                    d['kind'] = 'attendance'
                    prompt = 'Введите фактически пришедшее число игроков (0 — команда не пришла). Исходная заявка сохранится'
                await state.set_state(FinanceState.value)
                await state.set_data({'finance_draft':d})
                await callback.message.answer(f'<b>{esc(t["name"])}</b>\n{prompt}\n/cancel — отменить')
        elif action == 'price':
            s = await store_call(db, 'snapshot', ident)
            await state.set_state(FinanceState.value)
            await state.set_data({'finance_draft':{'kind':'ticket','event_id':ident,'revision':s['settings']['revision']}})
            await callback.message.answer('Введите базовую цену билета в сумах, целым числом. Это подсказка для ввода оплат; сохраненные суммы не пересчитываются. /cancel — отменить')
        elif action in ('expense','exclude','rename','kind'):
            x = await expense_page(callback.message, db, ident)
            d = {'kind':'rename' if action=='rename' else 'expense','expense_id':ident,'event_id':x['event_id'],'revision':x['revision'],'status':'confirmed','category':x['kind']}
            if action == 'kind':
                new_kind = 'cost' if x['kind'] == 'distribution' else 'distribution'
                await preview(callback.message, state, {**d,'kind':'expense_kind','expense_kind':new_kind,'category':new_kind}, f"Считать «{esc(x['title'])}» {'расходом, уменьшающим результат' if new_kind=='cost' else 'распределением прибыли, не уменьшающим результат'}?")
            elif action == 'exclude':
                await preview(callback.message, state, {**d,'status':'excluded','amount':0}, f"Исключить «{esc(x['title'])}» из итогов этой игры? История изменений сохранится")
            else:
                await state.set_state(FinanceState.value)
                await state.set_data({'finance_draft':d})
                await callback.message.answer('Введите новое название (до 120 символов)' if action=='rename' else 'Введите фактическую сумму в сумах. Она заменит прежнюю сумму этой статьи. Для ежемесячных услуг — только долю этой игры.' + (f"\nПодсказка для этой статьи: {money(x['suggested_uzs'])}, можно ввести другую сумму" if x['suggested_uzs'] is not None else '') + '\n/cancel — отменить')
        elif action in ('newteam','newcost','newdistribution'):
            kind = {'newteam':'team','newcost':'cost','newdistribution':'distribution'}[action]
            await state.set_state(FinanceState.value)
            await state.set_data({'finance_draft':{'kind':kind,'event_id':ident}})
            await callback.message.answer('Введите название команды' if kind=='team' else 'Введите название новой статьи для этой игры (до 120 символов). /cancel — отменить')
        else:
            raise FinanceError('Неизвестное действие')
        await callback.answer()
    except (FinanceError, ValueError, KeyError, IndexError) as error:
        await callback.answer(str(error)[:180] if isinstance(error, FinanceError) else 'Кнопка устарела или некорректна', show_alert=True)
    except sqlite3.Error:
        log.warning('finance_storage_unavailable')
        await callback.answer('Не удалось сохранить/прочитать данные. Попробуйте снова', show_alert=True)


async def value(message, state: FSMContext, db):
    d = (await state.get_data()).get('finance_draft')
    if not d:
        await state.clear()
        await message.answer('Черновик потерян. Откройте 👥 Явка заново')
        return
    try:
        kind = d['kind']
        if await state.get_state() == FinanceState.amount.state:
            if kind == 'payment' and message.text == 'По базовой цене':
                s = await store_call(db, 'snapshot', d['event_id'])
                price = s['settings'].get('ticket_uzs')
                if price is None:
                    raise FinanceError('Базовая цена не задана. Введите фактическую сумму')
                amount = price*d['players']
            else:
                amount = parse_integer(message.text, 10**12)
            d['amount'] = amount
            if kind == 'payment':
                text = f"{METHODS[d['method']]}: заменить итог на {d['players']} оплативших / {money(amount)}"
            else:
                text = f"Добавить {'расход' if kind=='cost' else 'распределение прибыли'} «{esc(d['title'])}»: {money(amount)}"
            await preview(message, state, d, text)
            return
        if kind in ('team','cost','distribution','rename'):
            title = ' '.join((message.text or '').split())
            if not title or len(title)>120:
                raise FinanceError('Название: от 1 до 120 символов')
            d['title'] = title
            if kind in ('team','rename'):
                await preview(message, state, d, f"{'Добавить команду без заявки' if kind=='team' else 'Переименовать статью'}: {esc(title)}")
            else:
                await state.set_state(FinanceState.amount)
                await state.set_data({'finance_draft':d})
                await message.answer('Введите фактическую сумму в сумах. /cancel — отменить')
        elif kind == 'attendance':
            d['players'] = parse_integer(message.text, 500)
            await preview(message, state, d, f"Фактически пришло: {d['players']} чел." if d['players'] else 'Команда не пришла')
        elif kind == 'payment':
            d['players'] = parse_integer(message.text, 500)
            if not d['players']:
                await preview(message, state, {**d,'amount':0}, f"Обнулить итог способа {METHODS[d['method']]} для команды? Запись сохранится в истории")
            else:
                await state.set_state(FinanceState.amount)
                await state.set_data({'finance_draft':d})
                s = await store_call(db, 'snapshot', d['event_id'])
                price = s['settings'].get('ticket_uzs')
                text = 'Введите фактически полученную ИТОГОВУЮ сумму этим способом в сумах, с учетом скидок'
                if price is not None:
                    text += f"\nПо базовой цене: {money(price*d['players'])}. Можно отправить текст: По базовой цене"
                await message.answer(text+'\n/cancel — отменить')
        else:
            d['amount'] = parse_integer(message.text, 10**9 if kind=='ticket' else 10**12)
            await preview(message, state, d, ('Базовая цена: ' if kind=='ticket' else 'Фактическая сумма статьи: ')+money(d['amount']))
    except FinanceError as error:
        await message.answer(esc(error)+'\nПопробуйте снова или /cancel')
    except sqlite3.Error:
        log.warning('finance_storage_unavailable')
        await message.answer('Хранилище временно недоступно. Данные не подтверждены, повторите ввод')


def create_router():
    router = Router(name='attendance_finance')
    router.message.filter(AdminPrivate())
    router.callback_query.filter(AdminPrivate())
    router.message.register(entry, F.text == '👥 Явка')
    router.message.register(entry, Command('attendance'))
    router.message.register(cancel_message, StateFilter(FinanceState), Command('cancel'))
    router.callback_query.register(callback, F.data.startswith('af:'))
    router.message.register(value, StateFilter(FinanceState.value, FinanceState.amount))
    return router
