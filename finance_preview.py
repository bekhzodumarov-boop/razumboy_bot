"""Isolated staging-only UX preview, using the production finance router.

Never run against the production bot or database. No scheduler, broadcasts,
legacy backup restoration, analytics, or real booking data are used here.
"""
import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.storage.memory import SimpleEventIsolation

from config import load_config
from database import Database
from finance import FinanceStore
from handlers.finance_admin import AdminPrivate, create_router
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext


def preview_menu():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="👥 Явка")],[KeyboardButton(text="🆕 Новый тест")]], resize_keyboard=True)


class PreviewDatabase(Database):
    def _restore_backup_if_empty(self):
        # The production Database embeds historical data. Do not load it here.
        pass


def check_preview_identity(username, environment, path):
    if username.lower() != 'razumboy_test_bot' or environment != 'staging':
        raise ValueError('Finance preview requires Razumboy_Test_Bot in staging')
    if Path(path).resolve() != Path('/data/razumboy-finance-preview.sqlite'):
        raise ValueError('Finance preview requires its dedicated synthetic database')


def seed_demo(path, *, fresh=False):
    db = PreviewDatabase(str(path))
    date = datetime.now(ZoneInfo('Asia/Tashkent')).date().isoformat()
    with db._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        event_id = 900050
        if fresh:
            event_id = max(event_id, c.execute('SELECT COALESCE(MAX(id),0)+1 FROM events').fetchone()[0])
        c.execute('''INSERT OR IGNORE INTO events(id,title,description,event_date,event_time,location,price_text,status)
                     VALUES(?,?,'Только вымышленные данные',?,'19:00','Тест','100000','closed')''',
                  (event_id, f'🧪 ТЕСТ #{event_id}: явка и оплаты', date))
        for index, (name, size) in enumerate(zip(
                ['Альфа','Бета','Гамма','Дельта','Панда','Сигма','Омега','Зета'], [4,2,6,3,6,3,3,2]),1):
            c.execute("INSERT OR IGNORE INTO users(telegram_id,full_name,subscribed) VALUES(?,? ,0)",
                      (-index, f'Демо {index}'))
            user_id = c.execute('SELECT id FROM users WHERE telegram_id=?',(-index,)).fetchone()[0]
            if not c.execute('SELECT 1 FROM registrations WHERE event_id=? AND user_id=?',(event_id,user_id)).fetchone():
                c.execute('''INSERT INTO registrations(event_id,user_id,team_name,team_size,captain_name,phone,status)
                             VALUES(?,?,?,?, 'Демо', 'нет — вымышленная запись','confirmed')''',
                          (event_id,user_id,'Демо: '+name,size))
    f = FinanceStore(path)
    f.prepare(event_id)
    s = f.snapshot(event_id)
    if s['settings'].get('ticket_uzs') is None:
        f.ticket(event_id,100000,0,0,f'preview-price-{event_id}')
    return event_id



def create_preview_dispatcher(db, admin_ids):
    dp = Dispatcher(events_isolation=SimpleEventIsolation())
    dp['db'], dp['admin_ids'] = db, admin_ids
    dp.include_router(create_router())

    async def denied(message):
        logging.getLogger(__name__).info('finance_preview_access_denied')
        await message.answer('Доступ к тесту для этого Telegram-аккаунта пока не настроен.\n'
                             f'Ваш Telegram ID: <code>{message.from_user.id}</code>\n'
                             'Передайте этот ID администратору для проверки доступа')

    async def welcome(message, state: FSMContext):
        if message.from_user.id not in admin_ids:
            await denied(message)
            return
        await state.clear()
        await message.answer('🧪 <b>Тест явки и финансов</b>\nЗдесь только вымышленные данные. Рабочая игра не изменяется.\n'
                             'Нажмите 👥 Явка и выберите тестовую игру. Новая пустая попытка: /newdemo', reply_markup=preview_menu())

    async def new_demo(message, state: FSMContext):
        await state.clear()
        ident = await asyncio.to_thread(seed_demo,db.db_path,fresh=True)
        await message.answer(f'Создан новый тест #{ident}. Старые тесты сохранены. Нажмите 👥 Явка',reply_markup=preview_menu())

    # Telegram clients can drop the optional VS16 emoji presentation selector.
    private = F.chat.type == 'private'
    legacy_admin = F.text.regexp(r'^(?:⚙\ufe0f?\s*)?Панель администратора$')
    dp.message.register(welcome,private,Command('start','help'))
    dp.message.register(welcome,private,legacy_admin | (F.text == '🏠 Главное меню'))
    dp.message.register(new_demo,AdminPrivate(),Command('newdemo'))
    dp.message.register(new_demo,AdminPrivate(),F.text == '🆕 Новый тест')

    async def fallback(message):
        if message.from_user.id not in admin_ids:
            await denied(message)
        else:
            await message.answer('Это тестовый режим явки и финансов. Нажмите /start, чтобы обновить клавиатуру и открыть 👥 Явка', reply_markup=preview_menu())

    # Child-router fallback must follow finance; a parent catch-all would swallow FSM input.
    tail = Router(name='finance_preview_fallback')
    tail.message.register(fallback,private)
    dp.include_router(tail)
    return dp


async def main():
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    # Guard platform and path before creating a Telegram client or opening SQLite.
    check_preview_identity('Razumboy_Test_Bot', os.getenv('RAILWAY_ENVIRONMENT_NAME',''), config.db_path)
    bot = Bot(token=config.bot_token,default=DefaultBotProperties(parse_mode='HTML'))
    try:
        me = await bot.get_me()
        check_preview_identity(me.username or '',os.getenv('RAILWAY_ENVIRONMENT_NAME',''),config.db_path)
        if not config.admin_ids:
            raise ValueError('Preview requires configured admin recipients')
        event_id = await asyncio.to_thread(seed_demo,config.db_path)
        db = PreviewDatabase(config.db_path)
        dp = create_preview_dispatcher(db, config.admin_ids)
        print(f'FINANCE_PREVIEW_READY bot={me.username} demo_event={event_id} scheduler=off',flush=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
