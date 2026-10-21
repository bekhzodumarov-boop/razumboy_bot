# RAZUMBOY Marketing Analytics · локальный MVP

Отдельный FastAPI + React/Recharts сервис. Не импортируется Telegram-worker, не меняет его зависимости, конфигурацию, расписание или SQLite. Родительская задача [Issue #5](https://github.com/bekhzodumarov-boop/razumboy_bot/issues/5). В этой работе нет деплоя или подключения production.

Сначала прочитайте [аудит и карту данных](AUDIT.md). Снимок Telegram и рекламные CSV — независимые источники, не точная общая пользовательская когорта.

## Запуск на Windows / PowerShell

Из корня репозитория, Python 3.12+ и Node 20.19+/22.12+:

```powershell
python -m venv .dashboard-venv
.\.dashboard-venv\Scripts\python.exe -m pip install -r marketing_dashboard/requirements.txt
Set-Location marketing_dashboard/frontend
npm ci
npm run build
Set-Location ../..
.\.dashboard-venv\Scripts\python.exe -m marketing_dashboard.demo --db marketing_dashboard/runtime/demo.db
$env:DASHBOARD_DB_PATH = 'marketing_dashboard/runtime/demo.db'
$env:DASHBOARD_ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', (Read-Host 'Задайте локальный пароль (минимум 16 символов)' -AsSecureString)).Password
$env:DASHBOARD_ORIGIN = 'http://127.0.0.1:8765'
$env:DASHBOARD_LOCAL_HTTP = '1'
.\.dashboard-venv\Scripts\python.exe -m uvicorn marketing_dashboard.api:create_app --factory --host 127.0.0.1 --port 8765 --no-access-log
```

Открыть `http://127.0.0.1:8765`. По умолчанию период демо: 10–21 октября 2026; конечная дата фильтра 22 октября **не включена**. Demo-команда откажется заменять существующую БД: выберите новое имя. Никаких встроенных паролей или реальных токенов нет. Linux-команды аналогичны с `.dashboard-venv/bin/python`.

Для реальных импортов создайте новый файл `DASHBOARD_DB_PATH`, не запускайте demo. После входа пустой интерфейс предлагает импорт. Все данные API требуют входа; сама HTML-оболочка и страница входа не содержат данных участников.

## Страницы

1. Обзор: расходы, показы, клики, пользователи, регистрации, команды/игроки, динамика и воронка. Недоступные CPL и стоимость игрока явно обозначены.
2. Воронка: события и уникальные пользователи, соотношения между этапами (не когортная конверсия), исходы и последние шаги открытых попыток.
3. Кампании: поиск, сортировка, защищённый CSV-экспорт, CPM, link CTR/CPC. Охват/частота не суммируются между днями/объявлениями.
4. Игры: команды, игроки, средний размер, максимум команд и регистрационная кривая T−N. Минимальная заполняемость и новые/постоянные команды — «Нет данных».
5. Источники и креативы: допустимые Telegram-метки и отдельный список объявлений CSV. Facebook в боте отдельно не фиксируется.

Общие фильтры: полуоткрытый период, игра, источник; дополнительные — campaign/ad, первая наблюдаемая дата пользователя, валюта, уровень CSV, timezone аккаунта. Telegram всегда в Asia/Tashkent. Даты заявок приводятся экспортёром к Ташкенту с учётом **явно указанного** timezone исходной SQLite.

При выборе кампании/креатива Telegram KPI становятся «Нет данных»: соответствующей атрибуции нет. При выборе игры/источника расходы также неизвестны. Число бизнес-заявок/игроков нельзя фильтровать по source или первому контакту: отсутствует надёжная связь с attempt_id. Нулевое значение означает наблюдённый ноль, null — отсутствующий источник/связь. За пределами полноты журнала нули нельзя трактовать как отсутствие исторической активности; начало доступной истории видно внизу.

## Meta CSV

Скачайте шаблон в окне «Импорт данных». Поддерживаются canonical headers и английские заголовки Ads Manager, например `Account ID`, `Campaign ID`, `Campaign name`, `Reporting starts`, `Reporting ends`, `Amount spent (UZS)`, `Impressions`, `Reach`, `Clicks (all)`, `Link clicks`. Часть русских заголовков указана в `core.ALIASES`; остальные предварительно переименуйте по шаблону. Неизвестные/дублирующиеся колонки отклоняются, а не угадываются.

Canonical колонки:

```csv
account_id,date_start,date_stop,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,impressions,reach,clicks,link_clicks
10001,2026-10-20,2026-10-20,20001,Test,30001,Test,40001,Test,12500.50,1000,800,25,20
```

- Только дневные строки ISO `YYYY-MM-DD`, date_start=date_stop, без итоговых строк. Это предотвращает пересечение многодневных экспортов.
- Явно выберите валюту UZS/USD/EUR, IANA timezone рекламного аккаунта и уровень campaign/adset/ad. Они входят в ключ импорта и фильтр запросов. Нет валютной конвертации.
- Десятичные расходы: до двух знаков. Разделители CSV — запятая, точка с запятой, tab; десятичная запятая поддержана, неоднозначные значения отклоняются. Сохраняйте Meta ID текстом, не Excel scientific notation.
- Для ad обязательны campaign/adset/ad ID и названия; для campaign adset/ad поля пусты. Нельзя складывать строки разных уровней: запрос выбирает ровно один.
- Повторный импорт обновляет тот же account/currency/timezone/level/day/entity. Исправленный spend заменяется; другие дни/сущности остаются. Пустые clicks/link_clicks/reach — неизвестно, не ноль. Есть журнал успешных импортов в API `meta.updates`.
- HTTP: до 1 MiB CSV, 10 000 строк, 4096 символов в ячейке; JSON запроса до 2 MiB. Импорт атомарен. Имена показываются как текст React; CSV-экспорт нейтрализует spreadsheet-формулы.

Meta Marketing API не используется и не нужен. Будущий адаптер должен возвращать тот же дневной контракт и проходить ту же валидацию/upsert; разрешений изменять кампании нет.

## Одностороннее подключение Telegram

В этом PR нет реальной выгрузки production: она не предоставлялась. Адаптер проверен на синтетических изолированных копиях исходной схемы, включая старый журнал без source.

1. После отдельного разрешения владельца снять согласованные SQLite Backup API копии бизнес-БД и журнала. Не копировать живые файлы обычным копированием без WAL; не открывать Volume из внешнего web-сервиса. Хранить копии только в защищённой локальной зоне вне Git.
2. Подтвердить timezone created_at (обычно SQLite CURRENT_TIMESTAMP — UTC). Не угадывать локальное время исторического seed.
3. Задать отдельный стабильный `DASHBOARD_EXPORT_HMAC_KEY` (не меньше 32 символов) в окружении экспортёра; это не bot token. Не публиковать ключ или копии. Один ключ + stream нужен для одинаковых псевдонимов между снимками.
4. Экспортировать только whitelist полей:

```powershell
.\.dashboard-venv\Scripts\python.exe -m marketing_dashboard.export_copy --business-copy C:/secure-copies/business.sqlite --journal-copy C:/secure-copies/journal.sqlite --business-timezone UTC --stream razumboy-main --confirm-isolated-copy --output C:/secure-copies/aggregate-export.json
```

Флаг — осознанное подтверждение оператора, а не автоматическое доказательство происхождения файла. Никогда не передавайте рабочий DB_PATH. Экспортёр открывает оба источника mode=ro с timeout=0.2; не создаёт Database и не запускает миграции. Исходные Telegram/attempt/dedup ID превращаются в keyed HMAC с разделением namespace. Контакты, имена и комментарии вообще не выбираются. Идентичность команды не восстанавливается.

5. В отдельную пустую аналитическую БД загрузить JSON через защищённый интерфейс или CLI:

```powershell
.\.dashboard-venv\Scripts\python.exe -m marketing_dashboard.manage telegram --db marketing_dashboard/runtime/real-analytics.db --file C:/secure-copies/aggregate-export.json
```

HTTP JSON максимум 2 MiB; для больших доверенных локальных файлов CLI ограничен 64 MiB и тем же пределом 100 000 событий. Текущий full-snapshot протокол предназначен для MVP; рост потребует инкрементальной синхронизации/PostgreSQL. Повтор идемпотентен, уменьшение/перезапись истории событий и смена stream запрещены. Бизнес-агрегаты обновляются по текущему состоянию; историческое состояние отменённых заявок восстановить нельзя. Снимки двух SQLite не атомарны между собой; это ограничение явно сохраняется.

Веб-API не принимает файловые пути, не раздаёт SQLite и не выдаёт actor/attempt токены. Псевдонимы внутри аналитического хранилища чувствительны: ограничьте права на файлы, backup и JSON, удаляйте изолированные копии по политике владельца.

## Защита и будущая выкладка

По умолчанию требуется HTTPS и пароль минимум 16 символов. HTTP разрешён только при явной локальной конфигурации и loopback origin; сервер запускать только на 127.0.0.1. За пределами localhost `DASHBOARD_LOCAL_HTTP` выключить, задать точный HTTPS `DASHBOARD_ORIGIN`, TLS завершать доверенным reverse proxy. Настраивать trust proxy IP адресно, не принимать forwarded headers от любого клиента. Реальный деплой этим PR не выполнен.

Один администратор / один web worker. Случайные токены сессий, HttpOnly/SameSite=Strict/Secure cookie, срок час, серверная роль, Origin + CSRF для всех изменений, ограничение неуспешных входов, CSP, no-store и запрет framing. Пароль в environment, а не JS/localStorage/URL. После рестарта сессии сбрасываются. Для внешнего многопользовательского сервиса нужны SSO/MFA, устойчивый session/rate-limit store и аудит ролей. Access logs выключены в примере; не включать тела запросов/секреты в observability.

Не смешивайте demo и реальные снимки. Общие названия рекламных кампаний/игр поступают от администратора: не помещайте в них персональные данные. API экспортирует только агрегаты, но малые группы всё равно могут быть чувствительны; публичный доступ этому MVP не предоставляется.

## Backup отдельного аналитического хранилища

```powershell
.\.dashboard-venv\Scripts\python.exe -m marketing_dashboard.manage backup --db marketing_dashboard/runtime/real-analytics.db --file C:/secure-backups/analytics-20261021.sqlite
```

SQLite Backup API учитывает WAL, проверяет integrity_check и печатает SHA256, существующий файл не перезаписывается. Хранить вне Volume, с доступом только владельцу. Восстановление проверять в **новый** путь и переключать только сервис дашборда; рабочую БД бота не восстанавливать из этих файлов.

## Формулы

Словарь доступен в интерфейсе. CPM=spend/impressions×1000, link CTR=link_clicks/impressions×100%, link CPC=spend/link_clicks. Нулевой знаменатель → «Нет данных». Reach и frequency доступны только для одной исходной строки, иначе неаддитивны.

CPL=атрибутированные расходы/завершённые регистрации того же объекта. Стоимость команды/заявленного игрока требует связи attempts с registrations. CAC=расходы/новые платящие игроки. ROAS=атрибутированная выручка/расходы. ROMI=(атрибутированная маржинальная прибыль−маркетинговые расходы)/маркетинговые расходы×100%. Сейчас исходные связи/оплаты/маржа отсутствуют, эти KPI остаются null. Заявка не подменяет оплату.

## Проверки

```powershell
.\.dashboard-venv\Scripts\python.exe -m unittest discover -s marketing_dashboard/tests -v
.\.test-venv\Scripts\python.exe -m unittest discover -s tests -q
```

Тесты используют только временные синтетические SQLite. Они не загружают .env или production secrets и не запускают polling, задания или Meta API. Снимки экрана демонстрационного интерфейса — `docs/screenshots/`.
