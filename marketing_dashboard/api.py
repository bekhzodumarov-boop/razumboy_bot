"""Same-origin web application. Does not import bot config or open bot databases."""
import csv
import hashlib
import hmac
import io
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .core import CSV_COLUMNS, Store, Strict


@dataclass
class Settings:
    db: str
    password: str
    origin: str
    local_http: bool = False

    def validate(self):
        parts = urlsplit(self.origin)
        if len(self.password)<16 or parts.path not in ('','/') or parts.query or parts.fragment:
            raise ValueError('Set a strong administrator password and exact origin')
        if parts.scheme!='https' and not (self.local_http and parts.scheme=='http' and parts.hostname in {'127.0.0.1','localhost'}):
            raise ValueError('HTTPS is required, except explicit loopback preview')


def env_settings():
    return Settings(os.getenv('DASHBOARD_DB_PATH', 'marketing_dashboard/runtime/analytics.db'),
                    os.getenv('DASHBOARD_ADMIN_PASSWORD',''), os.getenv('DASHBOARD_ORIGIN','https://localhost'),
                    os.getenv('DASHBOARD_LOCAL_HTTP')=='1')


def create_app(settings=None):
    settings = settings or env_settings()
    settings.validate()
    store = Store(settings.db)
    app = FastAPI(title='RAZUMBOY Marketing Analytics', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    sessions, failures = {}, {}
    cookie = 'razumboy_session'

    @app.exception_handler(RequestValidationError)
    async def bad_fields(request, error):
        return JSONResponse({'detail':'Invalid request fields'}, status_code=422)

    @app.middleware('http')
    async def boundary(request, call_next):
        if request.headers.get('host') != urlsplit(settings.origin).netloc:
            return JSONResponse({'detail':'Invalid host'}, status_code=400)
        if request.url.scheme!='https' and not settings.local_http:
            return JSONResponse({'detail':'HTTPS required'}, status_code=400)
        if request.method not in {'GET','HEAD','OPTIONS'}:
            if request.headers.get('origin') != settings.origin.rstrip('/'):
                return JSONResponse({'detail':'Origin rejected'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if not settings.local_http:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    async def bounded_json(request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>2*1024*1024:
                raise HTTPException(413, 'Import limit: 2 MiB JSON / 1 MiB CSV')
        try:
            import json
            return json.loads(data)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400,'Invalid JSON') from None

    def administrator(request: Request):
        token = request.cookies.get(cookie,'')
        session = sessions.get(hashlib.sha256(token.encode()).hexdigest())
        if not session or session['expires']<time.time():
            raise HTTPException(401,'Administrator login required')
        if request.method not in {'GET','HEAD'} and not hmac.compare_digest(request.headers.get('x-csrf-token',''), session['csrf']):
            raise HTTPException(403,'CSRF rejected')
        return session

    @app.post('/api/login')
    async def login(request: Request, response: Response):
        ip = request.client.host
        now = time.time()
        recent = [t for t in failures.get(ip,[]) if now-t<600]
        if len(recent)>=8:
            raise HTTPException(429,'Try again later')
        body = await bounded_json(request)
        if not isinstance(body,dict) or set(body)!={'password'} or not isinstance(body['password'],str):
            raise HTTPException(400,'Invalid credentials')
        if not hmac.compare_digest(hashlib.sha256(body['password'].encode()).digest(), hashlib.sha256(settings.password.encode()).digest()):
            if len(failures)>10000:
                failures.clear()
            failures[ip] = recent+[now]
            raise HTTPException(401,'Invalid credentials')
        if len(sessions)>1000:
            sessions.clear()
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[hashlib.sha256(token.encode()).hexdigest()] = {'csrf':csrf,'expires':now+3600,'role':'admin'}
        response.set_cookie(cookie, token, max_age=3600, httponly=True, secure=not settings.local_http, samesite='strict', path='/')
        return {'csrf':csrf,'role':'admin'}

    @app.get('/api/session')
    def session(user=Depends(administrator)):
        return {'csrf':user['csrf'],'role':user['role']}

    @app.post('/api/logout')
    def logout(request: Request, response: Response, user=Depends(administrator)):
        sessions.pop(hashlib.sha256(request.cookies[cookie].encode()).hexdigest(), None)
        response.delete_cookie(cookie, path='/')
        return {'ok':True}

    def query(request):
        allowed = {'start','until','game','source','campaign','creative','first_from','currency','account_timezone','level'}
        raw = dict(request.query_params)
        if set(raw)-allowed or 'start' not in raw or 'until' not in raw:
            raise HTTPException(400,'Invalid filters')
        try:
            if raw.get('game'):
                raw['game'] = int(raw['game'])
                if not 0<raw['game']<2**63:
                    raise ValueError()
            return store.query(**raw)
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            raise HTTPException(400,'Invalid date, timezone or filter') from None

    @app.get('/api/dashboard')
    def dashboard(request: Request, user=Depends(administrator)):
        return query(request)

    @app.post('/api/import/meta')
    async def import_meta(request: Request, user=Depends(administrator)):
        try:
            body = await bounded_json(request)
            if not isinstance(body,dict) or set(body)!={'csv','currency','account_timezone','level'}:
                raise ValueError()
            if not all(isinstance(v,str) for v in body.values()):
                raise ValueError()
            text = body.pop('csv')
            return store.import_ads(text, **body)
        except (ValueError, TypeError, KeyError, ZoneInfoNotFoundError):
            raise HTTPException(400,'CSV rejected: check template, daily rows, IDs, timezone, currency and granularity') from None

    @app.post('/api/import/telegram')
    async def import_telegram(request: Request, user=Depends(administrator)):
        try:
            return store.import_snapshot(await bounded_json(request))
        except (ValueError, TypeError, KeyError, ValidationError, ZoneInfoNotFoundError):
            raise HTTPException(400,'Snapshot rejected: invalid schema, stream or history regression') from None

    @app.get('/api/meta-template.csv')
    def template(user=Depends(administrator)):
        return Response(','.join(CSV_COLUMNS)+'\n', media_type='text/csv', headers={'Content-Disposition':'attachment; filename=meta-template.csv'})

    @app.get('/api/campaigns.csv')
    def export(request: Request, user=Depends(administrator)):
        rows = query(request)['campaigns']
        columns = ['campaign_id','campaign_name','adset_id','adset_name','ad_id','ad_name','spend','impressions','reach','frequency','cpm','ctr','cpc','link_clicks','bot_starts','registrations','cpl','players']
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            clean = {}
            for key in columns:
                value = row.get(key)
                value = '' if value is None else str(value)
                # Spreadsheet formula injection, including leading whitespace.
                clean[key] = "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
            writer.writerow(clean)
        return Response('\ufeff'+output.getvalue(), media_type='text/csv', headers={'Content-Disposition':'attachment; filename=campaigns.csv'})

    dist = Path(__file__).parent/'frontend'/'dist'
    if dist.exists():
        app.mount('/assets', StaticFiles(directory=dist/'assets'), name='assets')

        @app.get('/')
        def index():
            return FileResponse(dist/'index.html')
    return app
