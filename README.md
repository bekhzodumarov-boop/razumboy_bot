# Разумбой — Telegram Бот

Бот для анонсов и регистраций на квиз Разумбой.

## Требования

- Python 3.11+

## Установка и запуск

### 1. Распакуй архив и перейди в папку

```bash
cd razumboy_bot
```

### 2. Создай виртуальное окружение

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Установи зависимости

```bash
pip install -r requirements.txt
```

### 4. Заполни файл .env

Открой файл `.env` и убедись, что там верный токен и твой Telegram ID.

```
BOT_TOKEN=твой_токен
ADMIN_IDS=твой_telegram_id
DB_PATH=razumboy.db
```

### 5. Запусти бота

```bash
python app.py
```

## Планировщик и staging

`SCHEDULER_ENABLED=1` (также значение по умолчанию, если переменная отсутствует)
сохраняет все автоматические задания production. При `SCHEDULER_ENABLED=0`
APScheduler не создаётся: отключены проверки розыгрышей, рассылка победителям,
напоминания перед игрой и повторные напоминания в день игры. Регистрация и
аналитика работают независимо. Допустимы только `0` и `1`; другое значение
останавливает запуск до подключения БД.

Для изолированного staging задать `SCHEDULER_ENABLED=0`, при необходимости
`FUNNEL_ANALYTICS_ENABLED=1`, использовать отдельного тестового бота, отдельную
SQLite/Volume и тестовых администраторов. Флаг отключает задания по расписанию;
ручные административные действия и уведомления о запуске/регистрации остаются.
План безопасной проверки: [docs/railway-analytics-runbook.md](docs/railway-analytics-runbook.md).

## Команды бота

Доступность и статистика рассылок: «Подписчики → Доставка рассылок» в админ-панели.
Блокировка не меняет подписку; `/start` восстанавливает доступность без переподписки.
Подробности и безопасный откат: [доставка](docs/delivery-reachability.md).

Аудит локального автономного backup без персональных данных в выводе:

```powershell
python subscriber_audit.py "C:\Backups\offline-copy.sqlite" --confirm-local-backup
```

Скрипт открывает только явно указанный snapshot в read-only и не запускает бота.
Метрики, ограничения подписки и оценка рекламных сегментов описаны в
[аудите хранения подписчиков](docs/subscriber-storage-audit.md).

### Для пользователей
- `/start` — главное меню

### Для администратора
- `/admin` — открыть админ-панель

## Структура проекта

```
razumboy_bot/
├── app.py              # Точка входа
├── config.py           # Конфигурация
├── database.py         # Работа с SQLite
├── states.py           # FSM состояния
├── requirements.txt
├── .env                # Секреты (не коммить!)
├── handlers/
│   ├── common.py       # /start, меню, правила
│   ├── registration.py # Регистрация команды
│   └── admin.py        # Админ-панель
└── keyboards/
    ├── reply.py        # Reply-клавиатуры
    └── inline.py       # Inline-клавиатуры
```
