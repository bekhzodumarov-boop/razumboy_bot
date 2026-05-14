import os
import sqlite3
from typing import Optional


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Создаём папку если не существует (нужно для Railway Volume /data/)
        os.makedirs(os.path.dirname(db_path), exist_ok=True) if os.path.dirname(db_path) else None
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            cur = conn.cursor()

            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                language_code TEXT,
                subscribed INTEGER NOT NULL DEFAULT 1,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                event_date TEXT NOT NULL,
                event_time TEXT NOT NULL,
                location TEXT NOT NULL,
                location_url TEXT,
                price_text TEXT,
                max_teams INTEGER,
                photo_file_id TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                team_name TEXT NOT NULL,
                team_size INTEGER NOT NULL,
                captain_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                language TEXT NOT NULL DEFAULT '',
                comment TEXT,
                status TEXT NOT NULL DEFAULT 'confirmed',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (event_id) REFERENCES events(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                message_text TEXT NOT NULL,
                sent_count INTEGER NOT NULL DEFAULT 0,
                sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (event_id) REFERENCES events(id)
            )
            """)

            # Таблица подтверждений от игроков в день игры
            cur.execute("""
            CREATE TABLE IF NOT EXISTS confirmations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                registration_id INTEGER NOT NULL UNIQUE,
                confirmed_count INTEGER,
                player_names TEXT,
                replied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (registration_id) REFERENCES registrations(id)
            )
            """)

            conn.commit()

            cur.execute("""
            CREATE TABLE IF NOT EXISTS subscribers_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                first_name TEXT,
                last_name TEXT,
                gender TEXT,
                age TEXT,
                phone TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS randoboy_session (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                active INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS randoboy_participants (
                telegram_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS blitz_session (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                active INTEGER NOT NULL DEFAULT 0,
                question TEXT,
                answer TEXT,
                mode TEXT NOT NULL DEFAULT 'first',
                duration INTEGER NOT NULL DEFAULT 60,
                end_time TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS blitz_winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                full_name TEXT,
                answered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # ── Розыгрыш проходок ─────────────────────────────────
            cur.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                announce_text TEXT NOT NULL DEFAULT '',
                congrats_text TEXT NOT NULL DEFAULT '',
                image_file_id TEXT,
                announce_time TEXT NOT NULL DEFAULT '19:30',
                draw_time TEXT NOT NULL DEFAULT '21:00',
                winners_count INTEGER NOT NULL DEFAULT 2,
                active INTEGER NOT NULL DEFAULT 0,
                active_days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6'
            )
            """)
            # Гарантируем наличие строки — без неё UPDATE не работает
            cur.execute("INSERT OR IGNORE INTO giveaway_settings (id) VALUES (1)")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                sent_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES giveaway_sessions(id),
                UNIQUE (session_id, telegram_id)
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS photo_albums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL UNIQUE,
                url TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                won_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS winner_reminder_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                team_name TEXT,
                reminder_date TEXT NOT NULL,
                responded_at TEXT,
                UNIQUE(telegram_id, reminder_date)
            )
            """)

            # Seed исходных альбомов (INSERT OR IGNORE — не дублируются)
            initial_albums = [
                ("29 марта, Razumbooo", "https://t.me/razumboyphotos/12138"),
                ("22 марта, Razumbooo", "https://t.me/razumboyphotos/12079"),
                ("15 марта, Razumbooo", "https://t.me/razumboyphotos/12043"),
                ("8 марта, Razumbooo",  "https://t.me/razumboyphotos/11986"),
            ]
            for title, url in initial_albums:
                cur.execute(
                    "INSERT OR IGNORE INTO photo_albums (title, url) VALUES (?, ?)",
                    (title, url)
                )

        # Миграция — добавляет новые колонки если их нет (БД удалять не нужно)
        self._migrate()

    def _migrate(self):
        """Добавляет новые колонки в существующую БД без её удаления."""
        migrations = [
            ("events", "photo_file_id", "TEXT"),
            ("events", "location_url", "TEXT"),
            ("giveaway_settings", "active_days", "TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6'"),
        ]
        with self._connect() as conn:
            for table, column, col_type in migrations:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                    conn.commit()
                except Exception:
                    pass  # Колонка уже существует — пропускаем

            # Все существующие пользователи становятся подписчиками если ещё не были
            try:
                conn.execute("UPDATE users SET subscribed = 1 WHERE subscribed = 0")
                conn.commit()
            except Exception:
                pass

            # Заполнить active_days если NULL (после миграции)
            try:
                conn.execute(
                    "UPDATE giveaway_settings SET active_days = '0,1,2,3,4,5,6' WHERE active_days IS NULL OR active_days = ''"
                )
                conn.commit()
            except Exception:
                pass

            # Обновить время объявления с 20:50 на 20:30 (для существующих БД)
            try:
                conn.execute(
                    "UPDATE giveaway_settings SET announce_time = '20:30' WHERE announce_time = '20:50'"
                )
                conn.commit()
            except Exception:
                pass

            # Обновить время объявления с 20:30 на 19:30
            try:
                conn.execute(
                    "UPDATE giveaway_settings SET announce_time = '19:30' WHERE announce_time = '20:30'"
                )
                conn.commit()
            except Exception:
                pass

            # Обновить тексты розыгрыша: проходки → мерч (кепка Разумбой, с 17 мая 2026)
            new_announce = (
                "🧢 Каждый день в 21:00 разыгрываем кепку Разумбой!\n\n"
                "Нажми кнопку ниже и испытай удачу — Рандомбой беспристрастен, "
                "шанс есть у каждого! 😄\n\n"
                "Победитель заберёт приз на ближайшей игре 🎉"
            )
            new_congrats = (
                "🎲 Барабанная дробь... Рандомбой сделал свой выбор!\n\n"
                "Кепку Разумбой 🧢 получают {winners} 🎉\n\n"
                "Поздравляем! Приходите на ближайшую игру и заберите свой приз.\n"
                "А остальные — не расстраивайтесь, розыгрыш повторяется каждый день в 21:00 😉"
            )
            try:
                # Обновляем только если текст ещё содержит старое слово «проходк» или пустой
                conn.execute("""
                    UPDATE giveaway_settings
                    SET announce_text = ?, congrats_text = ?
                    WHERE announce_text LIKE '%проходк%' OR announce_text = ''
                """, (new_announce, new_congrats))
                conn.commit()
            except Exception:
                pass

            # Обновить тексты розыгрыша: новые тексты с 17 мая 2026 (кепки)
            new_announce_v2 = (
                "🧢 ЕЖЕДНЕВНЫЙ РОЗЫГРЫШ КЕПОК РАЗУМБОЙ!\n\n"
                "Каждый вечер в 21:00 мы разыгрываем фирменные кепки Разумбой - "
                "и сегодня не исключение!\n\n"
                "🎲 Победителей определяет Рандомбой - абсолютно честный случайный "
                "выбор среди всех участников.\n\n"
                "👉 Нажми «Участвую» - и у тебя есть шанс выиграть кепку!\n\n"
                "🎁 Приз вручается лично на ближайшей игре Razumboy: стреляй и пой!\n\n"
                "Удача любит смелых. Участвуй - шансов больше! 🔥"
            )
            new_congrats_v2 = (
                "🎲 Барабанная дробь...\n\n"
                "Рандомбой сделал свой выбор! Кепку Разумбой 🧢 получают:\n\n"
                "{winners}\n\n"
                "🎉 Поздравляем! Свяжитесь с нами для получения приза.\n\n"
                "🎁 Напоминаем: кепка вручается лично на ближайшей игре "
                "Razumboy: стреляй и пой!\n\n"
                "Не выиграл сегодня? Новый розыгрыш уже завтра в 19:30 - участвуй снова! 🔥"
            )
            try:
                # Обновляем если текст ещё не обновлён до v2 (не содержит «ЕЖЕДНЕВНЫЙ»)
                conn.execute("""
                    UPDATE giveaway_settings
                    SET announce_text = ?, congrats_text = ?
                    WHERE announce_text NOT LIKE '%ЕЖЕДНЕВНЫЙ%'
                """, (new_announce_v2, new_congrats_v2))
                conn.commit()
            except Exception:
                pass

            # Исторические победители Рандомбой (из экспорта канала, май 2026)
            historical_winners = [
                ('alenabobko',       '2026-05-04 21:00:00'),
                ('sviper07',         '2026-05-04 21:00:00'),
                ('timur_ferro',      '2026-05-05 21:00:00'),
                ('azabdu2006',       '2026-05-05 21:00:00'),
                ('the_normal_one',   '2026-05-06 21:00:00'),
                ('stas_dzi',         '2026-05-06 21:00:00'),
                ('gonrul',           '2026-05-07 21:00:00'),
                ('mariabelyakova_uz','2026-05-07 21:00:00'),
                ('azabdu2006',       '2026-05-10 21:00:00'),
                ('anorarakhimova',   '2026-05-10 21:00:00'),
                ('r_9014',           '2026-05-11 21:00:00'),
                ('akakruz',          '2026-05-11 21:00:00'),
                ('ds8921',           '2026-05-12 21:00:00'),
                ('fimamova',         '2026-05-12 21:00:00'),
                ('just_puzzle',      '2026-05-13 21:00:00'),
                ('habiba_ismailova', '2026-05-13 21:00:00'),
            ]
            try:
                for username, won_at in historical_winners:
                    conn.execute("""
                        INSERT OR IGNORE INTO giveaway_winners
                            (telegram_id, username, full_name, won_at)
                        SELECT 0, ?, ?, ?
                        WHERE NOT EXISTS (
                            SELECT 1 FROM giveaway_winners
                            WHERE username = ? AND date(won_at) = date(?)
                        )
                    """, (username, username, won_at, username, won_at))
                conn.commit()
            except Exception:
                pass

            # Подтянуть telegram_id победителей по username из таблицы users
            try:
                conn.execute("""
                    UPDATE giveaway_winners
                    SET telegram_id = (
                        SELECT u.telegram_id FROM users u
                        WHERE lower(u.username) = lower(giveaway_winners.username)
                        LIMIT 1
                    )
                    WHERE telegram_id = 0
                      AND username != ''
                      AND EXISTS (
                          SELECT 1 FROM users u
                          WHERE lower(u.username) = lower(giveaway_winners.username)
                      )
                """)
                conn.commit()
            except Exception:
                pass

        # Восстановить резервные данные если БД пустая (первый запуск на Railway Volume)
        self._restore_backup_if_empty()

    def _restore_backup_if_empty(self):
        """Вставляет резервные данные один раз при первом запуске на чистой БД."""
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count > 0:
                return  # БД уже заполнена — ничего не делаем

            cur = conn.cursor()

            # ── Пользователи ─────────────────────────────────
            users = [
                (248537708, 'Razumboy', 'RazumBoy', 'en', 1, 1, '2026-04-08 06:48:08'),
                (8091630624, 'SRDproject', 'Qishloq Joylarni Barqaror Rivojlantirish Loyihasi', 'en', 1, 0, '2026-04-08 08:45:09'),
                (5796853392, 'shokhrukhkamolov', 'Shokhrukh Kamolov', 'en', 1, 0, '2026-04-08 08:46:21'),
                (163476178, 'BekhzodUmarov', 'Bekhzod Umarov', 'en', 1, 1, '2026-04-08 11:20:37'),
                (711413, 'Dil_Bek', 'Dilshod_SAFO', 'ru', 1, 0, '2026-04-08 11:50:13'),
                (608165005, 'dreamfoxer', 'Алишер', 'ru', 1, 0, '2026-04-08 11:51:44'),
                (117521272, 'M_Azamov', "Muzaffar A'zamov", 'ru', 1, 0, '2026-04-08 11:58:38'),
                (829331, 'CCO_Fargo', '#2006', 'ru', 1, 0, '2026-04-08 12:00:11'),
                (459740033, 'rakhimov_kh7', 'Khojiakbar Rakhimov', 'ru', 1, 0, '2026-04-08 12:18:33'),
                (347268664, 'erikmananov', 'erik mananov', 'ru', 1, 0, '2026-04-08 12:31:22'),
                (229353196, 'master_job', 'Ralf', 'ru', 1, 0, '2026-04-08 12:42:22'),
                (129519563, 'beha_umarov', 'Bekhruz', 'es', 1, 0, '2026-04-08 12:52:49'),
                (65395, 'abuimronbek', 'No Name', 'en', 1, 0, '2026-04-08 13:20:00'),
            ]
            cur.executemany("""
                INSERT INTO users (telegram_id, username, full_name, language_code, subscribed, is_admin, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, users)

            # ── События ──────────────────────────────────────
            events = [
                (1, '🎯 Разумбой: стреляй и пой!',
                 'Мы объединили морской бой с квизом и музыкой!',
                 '2026-04-10', '18:30', 'WOW BAR, ул. Матбуотчилар, 17',
                 'https://yandex.uz/maps/-/CPV6eOpR', '70 000 сум с игрока', None,
                 'AgACAgIAAxkBAAIBX2nWNe1OPIE6adpipP_pKlkd98yJAALLFmsbOaaxSlf1Rd1-g-9oAQADAgADeQADOwQ',
                 'open', '2026-04-08 11:03:07'),
                (2, 'Razumbooo: 15 игра года',
                 'Привет! Открываем регистрацию на пятнадцатую игру года! Супер-приз от Asialuxe Travel: тур во Вьетнам на 2 персоны!',
                 '2026-04-11', '18:30', 'WOW BAR, ул. Матбуотчилар, 17',
                 'https://yandex.uz/maps/-/CPV6eOpR', '70 000 сум с игрока', None,
                 'AgACAgIAAxkBAAIB9WnWPRU9yKX9cewwKu7JYz88OjmAAAIIF2sbOaaxStBROwgkhJPMAQADAgADeQADOwQ',
                 'open', '2026-04-08 11:35:12'),
            ]
            cur.executemany("""
                INSERT INTO events (id, title, description, event_date, event_time, location,
                    location_url, price_text, max_teams, photo_file_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, events)

            # ── Регистрации ───────────────────────────────────
            # user_id соответствует порядку вставки users выше (1-based)
            regs = [
                (1, 3, 'Шохрух', 8, 'шох', '+998998355500', '', 'confirmed', '2026-04-08 08:47:02'),
                (1, 1, 'dfsd', 4, 'bek', '+998933977599', '', 'confirmed', '2026-04-08 11:23:29'),
                (1, 4, 'dfsd', 4, 'fdsfsdf', '+9985151515', '', 'confirmed', '2026-04-08 11:29:07'),
                (1, 6, 'Разумбой тест', 10, 'Разумбой', '+998944213280', 'Тест', 'confirmed', '2026-04-08 11:53:01'),
                (1, 12, 'Viva Sicilia', 2, 'Stefano', '+39333174', '', 'confirmed', '2026-04-08 13:01:08'),
                (2, 1, 'Uga', 3, 'beka', '+998999999999', '', 'confirmed', '2026-04-08 11:35:45'),
                (2, 6, 'Разумбуууууу', 12, 'Разумбойник', '+998944213280', 'Тест', 'confirmed', '2026-04-08 11:53:49'),
                (2, 12, 'Viva Sicilia', 1, 'Marcello', '+393331742680', 'Это тест', 'confirmed', '2026-04-08 12:58:31'),
            ]
            cur.executemany("""
                INSERT INTO registrations (event_id, user_id, team_name, team_size, captain_name, phone, comment, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, regs)

            conn.commit()

    # ── Пользователи ──────────────────────────────────────────

    def upsert_user(self, telegram_id, username, full_name, language_code, is_admin=False):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cur.fetchone()
            if row:
                cur.execute("""
                    UPDATE users SET username = ?, full_name = ?, language_code = ?, is_admin = ?
                    WHERE telegram_id = ?
                """, (username, full_name, language_code, int(is_admin), telegram_id))
            else:
                # Новый пользователь — сразу подписан автоматически
                cur.execute("""
                    INSERT INTO users (telegram_id, username, full_name, language_code, is_admin, subscribed)
                    VALUES (?, ?, ?, ?, ?, 1)
                """, (telegram_id, username, full_name, language_code, int(is_admin)))
            conn.commit()

    def set_subscription(self, telegram_id, subscribed):
        with self._connect() as conn:
            conn.execute("UPDATE users SET subscribed = ? WHERE telegram_id = ?", (int(subscribed), telegram_id))
            conn.commit()

    def get_user_by_telegram_id(self, telegram_id) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            return cur.fetchone()

    def get_subscribers(self) -> list:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM users WHERE subscribed = 1")
            return cur.fetchall()


    # ── События ───────────────────────────────────────────────

    def create_event(self, title, description, event_date, event_time, location, location_url, price_text, max_teams, photo_file_id=None) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO events (title, description, event_date, event_time, location, location_url, price_text, max_teams, photo_file_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (title, description, event_date, event_time, location, location_url, price_text, max_teams, photo_file_id))
            conn.commit()
            return cur.lastrowid

    def list_events(self) -> list:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM events ORDER BY event_date ASC, event_time ASC")
            return cur.fetchall()

    def get_open_events(self) -> list:
        import datetime
        today = datetime.date.today().strftime("%Y-%m-%d")
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT * FROM events
                WHERE status = 'open' AND event_date >= ?
                ORDER BY event_date ASC, event_time ASC
            """, (today,))
            return cur.fetchall()

    def get_past_events(self) -> list:
        import datetime
        today = datetime.date.today().strftime("%Y-%m-%d")
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT * FROM events
                WHERE event_date < ? OR status != 'open'
                ORDER BY event_date DESC, event_time DESC
            """, (today,))
            return cur.fetchall()

    def get_upcoming_event(self) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT * FROM events WHERE status = 'open'
                ORDER BY event_date ASC, event_time ASC LIMIT 1
            """)
            return cur.fetchone()

    def get_event_by_id(self, event_id) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,))
            return cur.fetchone()

    def get_events_by_date(self, date_str: str) -> list:
        """Получить все открытые игры на конкретную дату (формат YYYY-MM-DD)"""
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT * FROM events WHERE status = 'open' AND event_date = ?
            """, (date_str,))
            return cur.fetchall()

    def get_events_by_date_tomorrow(self, date_str: str) -> list:
        """Получить все открытые игры на конкретную дату — для рассылки за день"""
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT * FROM events WHERE status = 'open' AND event_date = ?
            """, (date_str,))
            return cur.fetchall()

    # ── Регистрации ───────────────────────────────────────────

    def has_active_registration(self, event_id, user_id) -> bool:
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT id FROM registrations
                WHERE event_id = ? AND user_id = ? AND status = 'confirmed' LIMIT 1
            """, (event_id, user_id))
            return cur.fetchone() is not None

    def create_registration(self, event_id, user_id, team_name, team_size, captain_name, phone, comment) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO registrations (event_id, user_id, team_name, team_size, captain_name, phone, language, comment, status)
                VALUES (?, ?, ?, ?, ?, ?, '', ?, 'confirmed')
            """, (event_id, user_id, team_name, team_size, captain_name, phone, comment))
            conn.commit()
            return cur.lastrowid

    def get_registrations_for_event(self, event_id) -> list:
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT r.*, u.telegram_id, u.username, u.full_name
                FROM registrations r JOIN users u ON r.user_id = u.id
                WHERE r.event_id = ? AND r.status = 'confirmed'
                ORDER BY r.created_at ASC
            """, (event_id,))
            return cur.fetchall()

    def get_registrations_for_event_full(self, event_id) -> list:
        """Все регистрации (confirmed + cancelled) с данными подтверждения — для списка заявок."""
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT r.*, u.telegram_id, u.username, u.full_name,
                       c.confirmed_count, c.player_names
                FROM registrations r JOIN users u ON r.user_id = u.id
                LEFT JOIN confirmations c ON c.registration_id = r.id
                WHERE r.event_id = ?
                ORDER BY
                    CASE r.status WHEN 'confirmed' THEN 0 ELSE 1 END,
                    r.created_at ASC
            """, (event_id,))
            return cur.fetchall()

    def cancel_registration_by_id(self, registration_id: int):
        """Отменить регистрацию пользователем."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE registrations SET status = 'cancelled' WHERE id = ?",
                (registration_id,)
            )
            conn.commit()

    def get_registrations_with_confirmations(self, event_id) -> list:
        """Заявки с данными о подтверждении — для экспорта в Excel"""
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT r.team_name, r.team_size, r.captain_name, r.phone,
                       c.confirmed_count, c.player_names
                FROM registrations r
                LEFT JOIN confirmations c ON c.registration_id = r.id
                WHERE r.event_id = ? AND r.status = 'confirmed'
                ORDER BY r.created_at ASC
            """, (event_id,))
            return cur.fetchall()

    def get_user_registrations(self, user_id) -> list:
        """Регистрации конкретного пользователя — только актуальные"""
        import datetime
        today = datetime.date.today().strftime("%Y-%m-%d")
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT r.*, e.title, e.event_date, e.event_time, e.location
                FROM registrations r JOIN events e ON r.event_id = e.id
                WHERE r.user_id = ? AND r.status = 'confirmed'
                  AND e.status = 'open' AND e.event_date >= ?
                ORDER BY e.event_date ASC
            """, (user_id, today))
            return cur.fetchall()

    def get_registration_by_id(self, reg_id) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM registrations WHERE id = ?", (reg_id,))
            return cur.fetchone()

    # ── Подтверждения ─────────────────────────────────────────

    def save_confirmation(self, registration_id, confirmed_count, player_names):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO confirmations (registration_id, confirmed_count, player_names)
                VALUES (?, ?, ?)
                ON CONFLICT(registration_id) DO UPDATE SET
                    confirmed_count = excluded.confirmed_count,
                    player_names = excluded.player_names,
                    replied_at = CURRENT_TIMESTAMP
            """, (registration_id, confirmed_count, player_names))
            conn.commit()

    def get_confirmation(self, registration_id) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM confirmations WHERE registration_id = ?", (registration_id,))
            return cur.fetchone()

    # ── Рассылки ──────────────────────────────────────────────

    def save_broadcast(self, event_id, message_text, sent_count):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO broadcasts (event_id, message_text, sent_count) VALUES (?, ?, ?)
            """, (event_id, message_text, sent_count))
            conn.commit()

    def get_broadcasts(self, limit=10) -> list:
        """История последних рассылок"""
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT b.*, e.title as event_title
                FROM broadcasts b
                LEFT JOIN events e ON b.event_id = e.id
                ORDER BY b.sent_at DESC
                LIMIT ?
            """, (limit,))
            return cur.fetchall()

    def get_all_subscribers(self) -> list:
        """Все подписчики с никами"""
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT telegram_id, username, full_name, subscribed
                FROM users
                WHERE subscribed = 1
                ORDER BY full_name ASC
            """)
            return cur.fetchall()

    def get_subscribers_count(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE subscribed = 1")
            return cur.fetchone()["cnt"]

    def update_event_field(self, event_id: int, field: str, value):
        """Обновить одно поле игры"""
        allowed = {"title", "description", "event_date", "event_time", "location", "location_url", "price_text"}
        if field not in allowed:
            return
        with self._connect() as conn:
            conn.execute(f"UPDATE events SET {field} = ? WHERE id = ?", (value, event_id))
            conn.commit()

    def cancel_event(self, event_id: int):
        """Отменить игру — поставить статус 'cancelled'"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE events SET status = 'cancelled' WHERE id = ?",
                (event_id,)
            )
            conn.commit()

    def save_subscriber_profile(self, telegram_id, first_name, last_name, gender, age, phone):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO subscribers_profile (telegram_id, first_name, last_name, gender, age, phone)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    first_name=excluded.first_name, last_name=excluded.last_name,
                    gender=excluded.gender, age=excluded.age, phone=excluded.phone
            """, (telegram_id, first_name, last_name, gender, age, phone))
            conn.commit()

    def get_subscriber_profile(self, telegram_id) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM subscribers_profile WHERE telegram_id = ?", (telegram_id,)
            )
            return cur.fetchone()

    def get_all_subscriber_profiles(self) -> list:
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT sp.*, u.username
                FROM subscribers_profile sp
                LEFT JOIN users u ON u.telegram_id = sp.telegram_id
                ORDER BY sp.created_at ASC
            """)
            return cur.fetchall()

    # ── Рандомбой ─────────────────────────────────────────────

    def randoboy_start(self):
        """Запустить новый Рандомбой — сбросить участников и поставить active=1."""
        with self._connect() as conn:
            conn.execute("DELETE FROM randoboy_participants")
            conn.execute("""
                INSERT INTO randoboy_session (id, active) VALUES (1, 1)
                ON CONFLICT(id) DO UPDATE SET active=1, updated_at=CURRENT_TIMESTAMP
            """)
            conn.commit()

    def randoboy_stop(self):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO randoboy_session (id, active) VALUES (1, 0)
                ON CONFLICT(id) DO UPDATE SET active=0, updated_at=CURRENT_TIMESTAMP
            """)
            conn.commit()

    def randoboy_is_active(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT active FROM randoboy_session WHERE id=1").fetchone()
            return bool(row and row["active"])

    def randoboy_join(self, telegram_id: int, full_name: str) -> bool:
        """Добавить участника. Возвращает False если уже есть."""
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM randoboy_participants WHERE telegram_id=?", (telegram_id,)
            ).fetchone()
            if exists:
                return False
            conn.execute(
                "INSERT INTO randoboy_participants (telegram_id, full_name) VALUES (?, ?)",
                (telegram_id, full_name)
            )
            conn.commit()
            return True

    def randoboy_get_participants(self) -> list:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM randoboy_participants ORDER BY joined_at").fetchall()

    def randoboy_remove(self, telegram_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM randoboy_participants WHERE telegram_id=?", (telegram_id,))
            conn.commit()

    def randoboy_reset(self):
        with self._connect() as conn:
            conn.execute("DELETE FROM randoboy_participants")
            conn.execute("""
                INSERT INTO randoboy_session (id, active) VALUES (1, 0)
                ON CONFLICT(id) DO UPDATE SET active=0, updated_at=CURRENT_TIMESTAMP
            """)
            conn.commit()

    # ── Блиц-квиз ─────────────────────────────────────────────

    def blitz_start(self, question: str, answer: str, mode: str, duration: int, end_time: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM blitz_winners")
            conn.execute("""
                INSERT INTO blitz_session (id, active, question, answer, mode, duration, end_time)
                VALUES (1, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    active=1, question=excluded.question, answer=excluded.answer,
                    mode=excluded.mode, duration=excluded.duration, end_time=excluded.end_time,
                    updated_at=CURRENT_TIMESTAMP
            """, (question, answer, mode, duration, end_time))
            conn.commit()

    def blitz_stop(self):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO blitz_session (id, active) VALUES (1, 0)
                ON CONFLICT(id) DO UPDATE SET active=0, updated_at=CURRENT_TIMESTAMP
            """)
            conn.commit()

    def blitz_get_session(self) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM blitz_session WHERE id=1").fetchone()

    def blitz_add_winner(self, telegram_id: int, full_name: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO blitz_winners (telegram_id, full_name) VALUES (?, ?)",
                (telegram_id, full_name)
            )
            conn.commit()

    def blitz_get_winners(self) -> list:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM blitz_winners ORDER BY answered_at").fetchall()

    def blitz_winner_exists(self, telegram_id: int) -> bool:
        with self._connect() as conn:
            return bool(conn.execute(
                "SELECT 1 FROM blitz_winners WHERE telegram_id=?", (telegram_id,)
            ).fetchone())

    # ── Фотоальбомы ───────────────────────────────────────────

    def get_photo_albums(self) -> list:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM photo_albums ORDER BY created_at DESC"
            ).fetchall()

    def add_photo_album(self, title: str, url: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR REPLACE INTO photo_albums (title, url) VALUES (?, ?)",
                (title, url)
            )
            conn.commit()
            return cur.lastrowid

    def delete_photo_album(self, album_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM photo_albums WHERE id = ?", (album_id,))
            conn.commit()

    # ── Розыгрыш проходок ─────────────────────────────────────

    def get_giveaway_settings(self) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM giveaway_settings WHERE id = 1").fetchone()

    def save_giveaway_settings(self, announce_text: str, congrats_text: str,
                                image_file_id, announce_time: str, draw_time: str,
                                winners_count: int = 2, active: int = 1):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO giveaway_settings
                    (id, announce_text, congrats_text, image_file_id, announce_time, draw_time, winners_count, active)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    announce_text=excluded.announce_text,
                    congrats_text=excluded.congrats_text,
                    image_file_id=excluded.image_file_id,
                    announce_time=excluded.announce_time,
                    draw_time=excluded.draw_time,
                    winners_count=excluded.winners_count,
                    active=excluded.active
            """, (announce_text, congrats_text, image_file_id,
                  announce_time, draw_time, winners_count, active))
            conn.commit()

    def update_giveaway_field(self, field: str, value):
        allowed = {"announce_text", "congrats_text", "image_file_id",
                   "announce_time", "draw_time", "winners_count", "active", "active_days"}
        if field not in allowed:
            raise ValueError(f"Unknown field: {field}")
        with self._connect() as conn:
            conn.execute(
                f"UPDATE giveaway_settings SET {field} = ? WHERE id = 1", (value,)
            )
            conn.commit()

    def create_giveaway_session(self, date: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO giveaway_sessions (date, status) VALUES (?, 'pending')",
                (date,)
            )
            conn.commit()
            if cur.lastrowid:
                return cur.lastrowid
            return conn.execute(
                "SELECT id FROM giveaway_sessions WHERE date = ?", (date,)
            ).fetchone()["id"]

    def get_giveaway_session_by_id(self, session_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM giveaway_sessions WHERE id = ?", (session_id,)
            ).fetchone()

    def get_giveaway_session(self, date: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM giveaway_sessions WHERE date = ?", (date,)
            ).fetchone()

    def update_session_status(self, session_id: int, status: str, sent_count: int = None):
        with self._connect() as conn:
            if sent_count is not None:
                conn.execute(
                    "UPDATE giveaway_sessions SET status=?, sent_count=? WHERE id=?",
                    (status, sent_count, session_id)
                )
            else:
                conn.execute(
                    "UPDATE giveaway_sessions SET status=? WHERE id=?",
                    (status, session_id)
                )
            conn.commit()

    def add_giveaway_participant(self, session_id: int, telegram_id: int,
                                  username: str, full_name: str) -> bool:
        """Возвращает True если успешно добавлен, False если уже участвует."""
        with self._connect() as conn:
            try:
                conn.execute("""
                    INSERT INTO giveaway_participants (session_id, telegram_id, username, full_name)
                    VALUES (?, ?, ?, ?)
                """, (session_id, telegram_id, username, full_name))
                conn.commit()
                return True
            except Exception:
                return False

    def get_giveaway_participants(self, session_id: int) -> list:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM giveaway_participants WHERE session_id = ?",
                (session_id,)
            ).fetchall()

    def get_giveaway_non_participants(self, session_id: int) -> list:
        """Подписчики, которые ещё не нажали кнопку участия в сессии."""
        with self._connect() as conn:
            return conn.execute("""
                SELECT telegram_id FROM users
                WHERE subscribed = 1
                  AND telegram_id NOT IN (
                      SELECT telegram_id FROM giveaway_participants
                      WHERE session_id = ?
                  )
            """, (session_id,)).fetchall()

    def count_giveaway_participants(self, session_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM giveaway_participants WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            return row["cnt"] if row else 0

    def resolve_winner_telegram_ids(self):
        """Подтягивает telegram_id победителей по username из таблицы users."""
        with self._connect() as conn:
            conn.execute("""
                UPDATE giveaway_winners
                SET telegram_id = (
                    SELECT u.telegram_id FROM users u
                    WHERE lower(u.username) = lower(giveaway_winners.username)
                    LIMIT 1
                )
                WHERE telegram_id = 0
                  AND username != ''
                  AND EXISTS (
                      SELECT 1 FROM users u
                      WHERE lower(u.username) = lower(giveaway_winners.username)
                  )
            """)
            conn.commit()

    def count_winners_without_id(self) -> int:
        """Количество победителей с telegram_id = 0."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM giveaway_winners WHERE telegram_id = 0"
            ).fetchone()
            return row["cnt"] if row else 0

    def save_giveaway_winner(self, telegram_id: int, username: str, full_name: str):
        """Сохранить победителя розыгрыша."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO giveaway_winners (telegram_id, username, full_name) VALUES (?, ?, ?)",
                (telegram_id, username or "", full_name or "")
            )
            conn.commit()

    def get_giveaway_winners_since(self, days: int = 7) -> list:
        """Победители за последние N дней. Дедупликация по (username, дата)."""
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT telegram_id, username, full_name, won_at
                FROM giveaway_winners
                WHERE won_at >= datetime('now', ?)
                GROUP BY username, date(won_at)
                ORDER BY won_at DESC
            """, (f'-{days} days',))
            return cur.fetchall()

    def create_winner_reminder_response(self, telegram_id: int, username: str,
                                         full_name: str, reminder_date: str):
        """Создать запись ответа победителя (pending) при рассылке напоминания."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO winner_reminder_responses
                    (telegram_id, username, full_name, status, reminder_date)
                VALUES (?, ?, ?, 'pending', ?)
            """, (telegram_id, username or "", full_name or "", reminder_date))
            conn.commit()

    def update_winner_reminder_response(self, telegram_id: int, reminder_date: str,
                                         status: str, team_name: str = None):
        """Обновить статус ответа победителя (confirmed/declined)."""
        with self._connect() as conn:
            conn.execute("""
                UPDATE winner_reminder_responses
                SET status=?, team_name=?, responded_at=CURRENT_TIMESTAMP
                WHERE telegram_id=? AND reminder_date=?
            """, (status, team_name, telegram_id, reminder_date))
            conn.commit()

    def get_winner_reminder_responses(self, reminder_date: str) -> list:
        """Все ответы на напоминание за указанную дату."""
        with self._connect() as conn:
            return conn.execute("""
                SELECT * FROM winner_reminder_responses
                WHERE reminder_date=?
                ORDER BY id ASC
            """, (reminder_date,)).fetchall()

    # ── Шаблоны рассылок ─────────────────────────────────────────

    def get_broadcast_templates(self) -> list:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM broadcast_templates ORDER BY created_at DESC"
            ).fetchall()

    def get_broadcast_template(self, template_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM broadcast_templates WHERE id = ?", (template_id,)
            ).fetchone()

    def save_broadcast_template(self, title: str, text: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO broadcast_templates (title, text) VALUES (?, ?)",
                (title, text)
            )
            conn.commit()
            return cur.lastrowid

    def update_broadcast_template_text(self, template_id: int, text: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE broadcast_templates SET text = ? WHERE id = ?",
                (text, template_id)
            )
            conn.commit()

    def delete_broadcast_template(self, template_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM broadcast_templates WHERE id = ?", (template_id,))
            conn.commit()

    # ── Статистика гивэвея ────────────────────────────────────────

    def get_giveaway_stats(self) -> dict:
        """Полная статистика Рандомбой-гивэвея."""
        import datetime
        tz = datetime.timezone(datetime.timedelta(hours=5))
        today = datetime.datetime.now(tz=tz).strftime("%Y-%m-%d")
        yesterday = (datetime.datetime.now(tz=tz) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        week_ago = (datetime.datetime.now(tz=tz) - datetime.timedelta(days=7)).strftime("%Y-%m-%d")

        with self._connect() as conn:
            # Всего завершённых сессий
            total_sessions = conn.execute(
                "SELECT COUNT(*) FROM giveaway_sessions WHERE status='done'"
            ).fetchone()[0]

            # Вчерашние данные
            yesterday_row = conn.execute("""
                SELECT gs.sent_count, COUNT(gp.id) as participants
                FROM giveaway_sessions gs
                LEFT JOIN giveaway_participants gp ON gp.session_id = gs.id
                WHERE gs.date = ?
                GROUP BY gs.id
            """, (yesterday,)).fetchone()

            # Среднее участников за последние 7 дней
            avg_row = conn.execute("""
                SELECT AVG(cnt) FROM (
                    SELECT COUNT(gp.id) as cnt
                    FROM giveaway_sessions gs
                    LEFT JOIN giveaway_participants gp ON gp.session_id = gs.id
                    WHERE gs.date >= ? AND gs.status = 'done'
                    GROUP BY gs.id
                )
            """, (week_ago,)).fetchone()
            avg_7 = round(avg_row[0] or 0, 1)

            # Всего подписчиков (для % вовлечённости)
            total_subs = conn.execute(
                "SELECT COUNT(*) FROM users WHERE subscribed = 1"
            ).fetchone()[0]

            # Всего побед
            total_wins = conn.execute(
                "SELECT COUNT(*) FROM giveaway_winners"
            ).fetchone()[0]

            # Уникальных победителей
            unique_winners = conn.execute("""
                SELECT COUNT(DISTINCT lower(username))
                FROM giveaway_winners WHERE username != ''
            """).fetchone()[0]

            # Победивших несколько раз
            multi_winners = conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT lower(username), COUNT(*) as wins
                    FROM giveaway_winners WHERE username != ''
                    GROUP BY lower(username) HAVING wins > 1
                )
            """).fetchone()[0]

            # Топ-5 победителей
            top_winners = conn.execute("""
                SELECT username, COUNT(*) as wins
                FROM giveaway_winners WHERE username != ''
                GROUP BY lower(username)
                ORDER BY wins DESC LIMIT 5
            """).fetchall()

            # Вовлечённость вчера (%)
            engagement_yesterday = None
            if yesterday_row and total_subs and yesterday_row[0]:
                engagement_yesterday = round(yesterday_row[1] / yesterday_row[0] * 100, 1)

            # Вовлечённость в среднем за 7 дней (%)
            engagement_7 = round(avg_7 / total_subs * 100, 1) if total_subs and avg_7 else 0

            return {
                "total_sessions": total_sessions,
                "total_subs": total_subs,
                "yesterday_sent": yesterday_row[0] if yesterday_row else 0,
                "yesterday_participants": yesterday_row[1] if yesterday_row else 0,
                "engagement_yesterday": engagement_yesterday,
                "avg_7_days": avg_7,
                "engagement_7": engagement_7,
                "total_wins": total_wins,
                "unique_winners": unique_winners,
                "multi_winners": multi_winners,
                "top_winners": top_winners,
            }

    def get_registration_with_user(self, reg_id: int) -> Optional[sqlite3.Row]:
        """Регистрация + telegram_id капитана для уведомления."""
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT r.*, u.telegram_id as user_telegram_id, u.username as user_username
                FROM registrations r JOIN users u ON r.user_id = u.id
                WHERE r.id = ?
            """, (reg_id,))
            return cur.fetchone()
