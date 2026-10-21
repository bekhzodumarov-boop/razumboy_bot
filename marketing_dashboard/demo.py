"""Explicit synthetic dataset. Refuses to replace any existing analytics database."""
import argparse
import csv
import hashlib
import io
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .core import CSV_COLUMNS, Store


def demo_payload():
    events, registrations = [], []
    def token(value):
        return hashlib.sha256(('synthetic:'+value).encode()).hexdigest()
    def add(day, actor, attempt, name, source, game, step='start', result='ok'):
        n = len(events)+1
        events.append({'seq':n,'key':token(f'event-{n}'),'actor':token(actor),
                       'attempt':token(attempt) if attempt else None,'game':game,
                       'at':f'{day}T10:00:00+00:00','name':name,'step':step,'result':result,'source':source})
    for offset in range(12):
        day = (date(2026,10,10)+timedelta(days=offset)).isoformat()
        for i in range(24+offset):
            actor = f'user-{(i+offset*13)%180}'
            source = ('instagram','telegram','direct','qr')[i%4]
            game = 51 if i%3==1 else 50
            add(day,actor,None,'bot_started',source,game)
            if i%5==0:
                continue
            add(day,actor,None,'event_card_sent',source,game,'card')
            if i%3==0:
                continue
            attempt = f'attempt-{offset}-{i}'
            add(day,actor,attempt,'registration_started',source,game)
            add(day,actor,attempt,'registration_step_completed',source,game,'team_name')
            if i%7==0:
                add(day,actor,attempt,'registration_cancelled',source,game,'phone','cancelled')
            elif i%11==0:
                add(day,actor,attempt,'registration_cancelled',source,game,'team_size','superseded')
            elif i%13==0:
                add(day,actor,attempt,'registration_failed',source,game,'phone','handler_error')
            elif i%8!=2:
                add(day,actor,attempt,'registration_completed',source,game,'confirm')
                registrations.append({'game':game,'day':day,'status':'confirmed','teams':1,'players':3+i%5})
    registrations += [{'game':50,'day':'2026-10-15','status':'cancelled','teams':3,'players':15}]
    return {'version':1,'stream':'demo-v1','kind':'demo','generated_at':'2026-10-22T00:00:00+00:00',
            'coverage_start':'2026-10-10T10:00:00+00:00','business_timezone':'UTC',
            'games':[{'id':50,'title':'Разумбой: музыкальный вечер','day':'2026-10-22','capacity':24},
                     {'id':51,'title':'Кино, музыка и немного магии','day':'2026-10-24','capacity':20}],
            'registrations':registrations,'events':events}


def demo_csv():
    output = io.StringIO()
    writer = csv.DictWriter(output,fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for offset in range(12):
        day = (date(2026,10,10)+timedelta(days=offset)).isoformat()
        for i in range(2):
            writer.writerow({'account_id':'10001','date_start':day,'date_stop':day,'campaign_id':str(20001+i),
                             'campaign_name':('Осенние музыкальные квизы','Новые команды • Ташкент')[i],
                             'adset_id':str(30001+i),'adset_name':('Музыка / 25–44','Квиз / Ташкент')[i],
                             'ad_id':str(40001+i),'ad_name':('Музыкальный вечер · видео','Вечер с друзьями · сторис')[i],
                             'spend':str(45000+offset*3000+i*12000),'impressions':3500+offset*430+i*900,
                             'reach':2800+offset*100,'clicks':64+offset*8,'link_clicks':35+offset*4})
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True)
    args = parser.parse_args()
    if Path(args.db).exists():
        parser.exit(2,'Choose a new file; existing data will not be replaced.\n')
    store = Store(args.db)
    store.import_snapshot(demo_payload())
    store.import_ads(demo_csv(),currency='UZS',account_timezone='Asia/Tashkent',level='ad')
    print('Synthetic demo ready; no bot config, tokens or production databases were used.')


if __name__=='__main__':
    main()
