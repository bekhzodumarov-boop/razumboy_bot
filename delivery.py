"""Observe every private send, and separate logical broadcast outcomes from API calls."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
import logging

from aiogram.exceptions import (TelegramForbiddenError, TelegramRetryAfter, TelegramNetworkError,
                               TelegramBadRequest, TelegramServerError)

logger = logging.getLogger(__name__)
_batch = ContextVar('delivery_batch', default=None)
_role = ContextVar('delivery_role', default='primary')
SEND_METHODS = {'sendMessage','sendPhoto','sendDocument','sendVideo','sendAnimation','sendAudio',
                'sendVoice','sendSticker','sendMediaGroup','copyMessage','forwardMessage'}


class DeliverySkipped(Exception):
    """No Telegram request: a previous confirmed block is still in effect."""


def classify_error(error):
    if isinstance(error, TelegramForbiddenError):
        message = error.message.casefold()
        if 'bot was blocked by the user' in message:
            return 'blocked'
        if 'user is deactivated' in message:
            return 'deactivated'
        return 'forbidden_other'
    if isinstance(error, TelegramRetryAfter):
        return 'rate_limited'
    if isinstance(error, (TelegramNetworkError, TimeoutError, ConnectionError)):
        return 'network'
    if isinstance(error, TelegramServerError):
        return 'server_error'
    if isinstance(error, TelegramBadRequest):
        return 'bad_request'
    if isinstance(error, DeliverySkipped):
        return 'skipped_blocked'
    return 'unknown_error'


def safe_db(db, method, *args):
    try:
        return getattr(db, method)(*args)
    except Exception:
        logger.warning('delivery_state_or_metrics_write_failed')
        return None


class Batch:
    def __init__(self, excluded):
        self.excluded = excluded
        self.recipients = {}
        self.additional = dict(attempts=0,success=0,errors={})
        self.unit = None
        self.closed = False
        self.touched = False
        self.invalid_recipients = 0

    def register(self, chat_id, blocked=False):
        if self.closed or chat_id in self.excluded:
            return
        self.recipients.setdefault((self.unit,chat_id), dict(eligible=not blocked,
            attempted=False,success=False,error=None,skipped=blocked))

    def observe(self, chat_id, result, role):
        if self.closed or chat_id in self.excluded:
            return
        if role == 'additional':
            if result != 'skipped_blocked':
                self.additional['attempts'] += 1
            if result == 'success':
                self.additional['success'] += 1
            else:
                errors = self.additional['errors']
                errors[result] = errors.get(result,0)+1
            return
        self.register(chat_id, result == 'skipped_blocked')
        entry = self.recipients[(self.unit,chat_id)]
        if result == 'skipped_blocked':
            entry['skipped'] = True
        else:
            entry['attempted'] = True
            if result == 'success':
                entry['success'] = True
            else:
                entry['error'] = result

    def metrics(self):
        rows = list(self.recipients.values())
        errors = {}
        for row in rows:
            if row['error']:
                errors[row['error']] = errors.get(row['error'],0)+1
        attempted = sum(row['attempted'] for row in rows)
        return dict(eligible=sum(row['eligible'] for row in rows),attempts=attempted,
                    primary_success=sum(row['success'] and not row['error'] for row in rows),
                    primary_errors=errors,skipped_blocked=sum(row['skipped'] and not row['attempted'] for row in rows),
                    additional=self.additional,invalid_recipients=self.invalid_recipients)


@contextmanager
def additional_notification():
    token = _role.set('additional')
    try:
        yield
    finally:
        _role.reset(token)


def set_campaign_unit(value):
    batch = _batch.get()
    if batch and not batch.closed:
        batch.unit = value


def delivery_recipients(rows, db):
    """Snapshot eligible logical recipients before sending; preserve row objects."""
    selected = []
    seen = set()
    batch = _batch.get()
    if batch:
        batch.touched = True
    for row in rows:
        chat_id = row['telegram_id']
        if type(chat_id) is not int or chat_id <= 0:
            if batch:
                batch.invalid_recipients += 1
            continue
        if chat_id in seen:
            continue
        seen.add(chat_id)
        state = safe_db(db,'get_delivery_state',chat_id) or {'availability':'unknown'}
        blocked = state['availability'] == 'blocked'
        if batch:
            batch.register(chat_id,blocked)
        if not blocked:
            selected.append(row)
    return selected


def current_metrics():
    batch = _batch.get()
    return batch.metrics() if batch else None


def format_metrics(metrics):
    if not metrics:
        return 'Нет статистики доставки.'
    errors = ', '.join(f'{key}: {value}' for key,value in sorted(metrics['primary_errors'].items())) or '0'
    extra = metrics['additional']
    extra_errors = ', '.join(f'{key}: {value}' for key,value in sorted(extra['errors'].items())) or '0'
    return (f"Допущено (unknown + reachable): {metrics['eligible']}\n"
            f"Попыток основных отправок: {metrics['attempts']}\n"
            f"Основных успешно: {metrics['primary_success']}\nОшибки основных: {errors}\n"
            f"Пропущено blocked: {metrics['skipped_blocked']}\n"
            f"Некорректных адресатов: {metrics.get('invalid_recipients',0)}\n"
            f"Дополнительные: попыток {extra['attempts']}, успешно {extra['success']}; ошибки: {extra_errors}")


def tracked_broadcast(function):
    signature = inspect.signature(function)
    @wraps(function)
    async def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        values = bound.arguments
        excluded = set(values.get('admin_ids', []))
        if 'admin_ids' not in values:
            source = values.get('message') or values.get('callback')
            if source:
                excluded.add(source.from_user.id)
                message = getattr(source,'message',source)
                chat = getattr(message,'chat',None)
                if chat and chat.id > 0:
                    excluded.add(chat.id)
        batch = Batch(excluded)
        token = _batch.set(batch)
        role_token = _role.set('primary')
        try:
            return await function(*args, **kwargs)
        finally:
            batch.closed = True
            if batch.touched or batch.recipients or batch.additional['attempts']:
                safe_db(values['db'], 'save_delivery_run', function.__name__, batch.metrics())
            _role.reset(role_token)
            _batch.reset(token)
    return wrapped


class DeliveryMiddleware:
    def __init__(self, db):
        self.db = db

    async def __call__(self, make_request, bot, method):
        chat_id = getattr(method,'chat_id',None)
        if method.__api_method__ not in SEND_METHODS or type(chat_id) is not int or chat_id <= 0:
            return await make_request(bot,method)
        state = safe_db(self.db,'get_delivery_state',chat_id) or dict(availability='unknown',revision=0)
        batch = _batch.get()
        def record(result):
            safe_db(self.db,'count_delivery_result',result)
            if batch:
                batch.observe(chat_id,result,_role.get())
        if state['availability'] == 'blocked':
            record('skipped_blocked')
            raise DeliverySkipped()
        try:
            response = await make_request(bot,method)
        except asyncio.CancelledError:
            record('cancelled')
            raise
        except Exception as error:
            category = classify_error(error)
            if category == 'blocked':
                safe_db(self.db,'mark_delivery_blocked',chat_id,state['revision'])
            record(category)
            raise
        safe_db(self.db,'mark_delivery_success',chat_id)
        record('success')
        return response


def configure_delivery(bot, db):
    bot.session.middleware(DeliveryMiddleware(db))
