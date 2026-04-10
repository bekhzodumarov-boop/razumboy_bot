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

        # Миграция — добавляет новые колонки если их нет (БД удалять не нужно)
        self._migrate()

    def _migrate(self):
        """Добавляет новые колонки в существующую БД без её удаления."""
        migrations = [
            ("events", "photo_file_id", "TEXT"),
            ("events", "location_url", "TEXT"),
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
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT * FROM events WHERE status = 'open'
                ORDER BY event_date ASC, event_time ASC
            """)
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
