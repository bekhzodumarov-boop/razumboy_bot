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

## Команды

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
