"""Server-only, read-only Meta Insights connector. No credentials in client code."""
from datetime import date
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

class SourceUnavailable(Exception):
    pass

def meta_insights(*, token, account_id, api_version, since, until, opener=urlopen):
    if not token or not re.fullmatch(r'\d+', account_id or '') or not re.fullmatch(r'v\d+\.\d+', api_version or ''):
        raise SourceUnavailable('Meta access is not configured')
    start, stop = date.fromisoformat(since), date.fromisoformat(until)
    if start > stop or (stop-start).days > 93:
        raise ValueError('Meta range must be ordered and at most 94 days')
    query = dict(fields='date_start,date_stop,campaign_id,campaign_name,account_currency,spend,impressions,reach,clicks,inline_link_clicks,outbound_clicks', level='campaign', time_increment='1', limit='500',time_range=json.dumps(dict(since=since, until=until)))
    rows=[]
    for _ in range(40):
        url=f'https://graph.facebook.com/{api_version}/act_{account_id}/insights?'+urlencode(query)
        request=Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
        try:
            with opener(request,timeout=20) as response:
                raw=json.loads(response.read(8*1024*1024))
        except Exception:
            raise SourceUnavailable('Meta request failed; check account access and token expiry') from None
        if 'error' in raw or not isinstance(raw.get('data'),list):
            raise SourceUnavailable('Meta returned an invalid response')
        for row in raw['data']:
            def number(value):
                if value is None:return None
                value=float(value)
                if value<0 or value!=value or value==float('inf'):raise SourceUnavailable('Invalid Meta metric')
                return value
            outbound=next((x.get('value') for x in (row.get('outbound_clicks') or []) if x.get('action_type')=='outbound_click'),None)
            rows.append({**{k:str(row.get(k,''))[:180] for k in ('date_start','date_stop','campaign_id','campaign_name','account_currency')},**{k:number(row.get(k)) for k in ('spend','impressions','reach','clicks','inline_link_clicks')},'outbound_clicks':number(outbound)})
        if not raw.get('paging',{}).get('next'):
            return {'daily_rows':rows,'warning':'Daily reach is not additive. Clicks are not bot starts.'}
        # Ignore upstream paging URLs: never send credentials to a returned host.
        after=raw.get('paging',{}).get('cursors',{}).get('after')
        if not isinstance(after,str) or len(after)>4096 or after==query.get('after'):raise SourceUnavailable('Invalid Meta pagination')
        query['after']=after
    raise SourceUnavailable('Reduce Meta date range')
