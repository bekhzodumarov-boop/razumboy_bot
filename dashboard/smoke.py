"""Staging-only synthetic end-to-end ledger-to-export check."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from finance import FinanceStore
from finance_preview import seed_demo
from dashboard.export_snapshot import snapshot

def run(path):
    event_id=seed_demo(path,fresh=True)
    f=FinanceStore(path)
    settings=f.snapshot(event_id)['settings']
    f.ticket(event_id,70000,settings['revision'],0,f'smoke-price-{event_id}')
    draft=f.preview_bulk(event_id,'Демо: Альфа 6 - 140У+280К')
    f.save_bulk(draft,0,f'smoke-save-{event_id}')
    f.save_bulk(draft,0,f'smoke-save-{event_id}')
    s=f.snapshot(event_id)
    exported=next(e for e in snapshot(path)['events'] if e['id']==f'bot-{event_id}')['finance']
    for k in ('actual_players','paid_players','income_uzs','costs_uzs','distributions_uzs','balance_uzs'):
        if s[k]!=exported[k]:raise RuntimeError('Staging ledger/export mismatch')
    if (s['actual_players'],s['paid_players'],s['income_uzs'])!=(6,6,420000):raise RuntimeError('Staging totals mismatch')
    print('RELEASE_SMOKE_PASS '+json.dumps({'event_id':event_id,'actual_players':6,'paid_players':6,'income_uzs':420000}),flush=True)
    return event_id
