"""Strict shorthand parser. Amounts are thousands of UZS, never guessed methods."""
import re
import unicodedata
from finance import FinanceError, METHODS, integer


def key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value).casefold() if c.isalnum())


ALIASES = {
    'волосик': 'Праздничный волосик', 'принцессы': 'Я и бал принцесс',
    'бал принцесс': 'Я и бал принцесс', 'котичные': 'Котичные токсята',
    'панды': 'Panda Mafia', 'сыр': 'Сыр маминой подруги',
    'ван пис': 'One Piece', 'втф': 'WTF', 'рояль': 'РОЯЛЬ ФЛЭШ',
    'вылетело': 'Вылетело из головы',
}
METHOD_CODES = {'у':'uzum','п':'payme','к':'click','н':'cash',
                'переводом':'card','перевод':'card','на карту':'card','карта':'card'}


def parse_bulk(text, teams, price):
    if not text or len(text)>12000:
        raise FinanceError('Отправьте до 50 строк: Команда 5 - 280П+70Н. Суммы в тысячах сум')
    if not isinstance(price,int) or price<=0:
        raise FinanceError('Сначала выберите цену игры')
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    if len(lines)>50:
        raise FinanceError('Максимум 50 команд в одном сообщении')
    result, used = [], set()
    for line in lines:
        match=re.fullmatch(r'(.+?)\s+([0-9]{1,3})\s*[-–—]\s*(.+)',line)
        if not match:
            raise FinanceError('Не разобрана строка: '+line[:100]+'. Нужны название, явка и суммы со способами')
        name, actual, expression=match.groups()
        target=key(name)
        candidates=[t for t in teams if key(t['name'])==target]
        if not candidates:
            alias=next((v for k,v in ALIASES.items() if key(k)==target),None)
            candidates=[t for t in teams if alias and key(t['name'])==key(alias)]
        if len(candidates)!=1:
            raise FinanceError('Команда «'+name+'» не найдена однозначно. Напишите точное название из списка')
        t=candidates[0]
        if t['id'] in used:
            raise FinanceError('Команда «'+t['name']+'» указана дважды')
        used.add(t['id'])
        actual=integer(int(actual),500,'Явка')
        amounts={m:0 for m in METHODS}
        for part in expression.split('+'):
            payment=re.fullmatch(r'\s*([0-9]{1,9})\s*([А-Яа-яЁё ]+)\s*',part)
            if not payment:
                raise FinanceError('У каждой суммы нужен способ: У, П, К, Н или «переводом». Строка: '+line[:100])
            value, code=payment.groups()
            method=METHOD_CODES.get(' '.join(code.lower().split()))
            if method is None:
                raise FinanceError('Неизвестный способ: '+code)
            amounts[method]+=int(value)*1000
        if any(v%price for v in amounts.values()):
            raise FinanceError('«'+t['name']+'»: сумма не делится на цену билета. Проверьте скидку или сумму; число оплативших не угадывается')
        rows={m:{'players':v//price} for m,v in amounts.items()}
        paid=sum(r['players'] for r in rows.values())
        if paid>actual:
            raise FinanceError('«'+t['name']+'»: оплат больше, чем пришедших. Проверьте строку')
        result.append({'team_id':t['id'],'name':t['name'],'revision':t['revision'],
                       'actual_players':actual,'rows':rows})
    if not result:
        raise FinanceError('Нет команд для записи')
    return result
