import html
import re
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import asyncio
import anyio
from typing import Annotated
from uuid import UUID as UUIDType
from urllib.parse import urlsplit
from fastapi import FastAPI, Depends, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.exceptions import HTTPException
from starlette.responses import HTMLResponse, StreamingResponse
from . import models as m
from .business import Backend, fail
from .config import Settings
from .crypto import digest, packed
from .http import Guard, Failure, error

bearer = HTTPBearer(auto_error=False)

def token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None or credentials.scheme.lower() != 'bearer':
        fail(401)
    return credentials.credentials

Token = Annotated[str, Depends(token)]
Key = Annotated[m.UUID, Header(alias='Idempotency-Key')]


def cursor_id(cursor):
    if cursor is None:
        return '00000000-0000-0000-0000-000000000000'
    try:
        if str(UUIDType(cursor)) != cursor:
            raise ValueError()
    except ValueError:
        fail(422,'INVALID_ARGUMENT','Hibás lapozókurzor.')
    return cursor


def create_app(settings=None, backend=None):
    settings = settings or Settings.load()
    b = backend or Backend(settings)
    @asynccontextmanager
    async def lifespan(app):
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 4
        # Guard database checks use asyncio.to_thread; bound that executor too.
        executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='mm02-guard')
        asyncio.get_running_loop().set_default_executor(executor)
        try:
            b.db.check_profile()
            yield
        finally:
            limiter.total_tokens = previous
            executor.shutdown(wait=True)
    errors = {n:{'model':m.Error} for n in (400,401,403,404,405,408,409,410,413,416,422,429,431,500,503)}
    app = FastAPI(title='Mesemondó02',version='1.0.0',root_path=settings.root_path,redirect_slashes=False,
                  servers=[{'url':settings.root_path or '/'}],lifespan=lifespan,responses=errors,
                  docs_url=None,redoc_url=None,openapi_url='/api/v1/openapi.json')
    app.state.backend = b
    app.add_middleware(Guard,database=b.db)

    @app.exception_handler(Failure)
    async def failure(request,exc):
        return error(request.state.request_id,exc.status,exc.code,exc.message)
    @app.exception_handler(RequestValidationError)
    async def invalid(request,exc):
        return error(request.state.request_id,422,'INVALID_ARGUMENT','Érvénytelen kérésparaméter.')
    @app.exception_handler(HTTPException)
    async def http_error(request,exc):
        return error(request.state.request_id,exc.status_code,'NOT_FOUND' if exc.status_code==404 else 'INVALID_ARGUMENT','Az útvonal vagy a metódus nem érhető el.')

    @app.get('/api/v1/healthz',response_model=m.Health)
    def health():
        return {'status':'ok'}
    @app.get('/api/v1/readyz',response_model=m.Health)
    def ready():
        b.db.check_profile()
        return {'status':'ready'}
    @app.post('/api/v1/auth/challenges',response_model=m.Challenge)
    def challenge(body:m.ChallengeRequest):
        return b.challenge(body.device_id)
    @app.post('/api/v1/auth/sessions',response_model=m.Session)
    def session(body:m.SessionRequest):
        return b.session(body.challenge_id,body.signature)

    @app.get('/api/v1/catalog',response_model=m.Catalog)
    def catalog(limit:Annotated[int,Query(ge=1,le=100)]=20,cursor:Annotated[str|None,Query(max_length=36)]=None):
        after = cursor_id(cursor)
        with b.db.transaction() as c:
            rows = c.execute('SELECT id AS content_id,title,description,price_minor,currency FROM contents WHERE id>%s ORDER BY id LIMIT %s',(after,limit+1)).fetchall()
            more = len(rows)>limit
            rows = rows[:limit]
            for row in rows:
                row['content_id'] = str(row['content_id'])
            return dict(items=rows,next_cursor=rows[-1]['content_id'] if more else None)

    @app.get('/api/v1/devices/me/entitlements',response_model=m.Entitlements)
    def entitlements(access:Token,limit:Annotated[int,Query(ge=1,le=100)]=20,cursor:Annotated[str|None,Query(max_length=36)]=None):
        after = cursor_id(cursor)
        with b.db.transaction() as c:
            dev = b.auth(c,access)
            rows = c.execute('SELECT content_id,grant_id,issued_at FROM entitlements WHERE device_id=%s AND content_id>%s ORDER BY content_id LIMIT %s',(dev['id'],after,limit+1)).fetchall()
            more = len(rows)>limit
            rows = rows[:limit]
            for row in rows:
                row['content_id'],row['grant_id'] = str(row['content_id']),str(row['grant_id'])
            return dict(items=rows,next_cursor=rows[-1]['content_id'] if more else None)

    @app.post('/api/v1/contents/{content_id}/delivery',response_model=m.Delivery)
    def delivery(content_id:m.UUID,access:Token,key:Key):
        return b.delivery(access,content_id,key)

    @app.get('/api/v1/downloads/{ticket}',response_class=StreamingResponse,
             responses={200:{'description':'Immutable bytes','content':{'application/octet-stream':{}}},206:{'description':'Single byte range','content':{'application/octet-stream':{}},'headers':{'Content-Range':{'schema':{'type':'string'}}}}})
    def download(ticket:m.Secret,access:Token,request:Request,range_header:Annotated[str|None,Header(alias='Range',max_length=128)]=None):
        with b.db.transaction() as c:
            dev = b.auth(c,access)
            row = c.execute('SELECT t.*,f.sha256,f.size_bytes,f.media_type FROM tickets t JOIN files f ON f.id=t.file_id WHERE token_hash=%s AND device_id=%s',(digest(ticket),dev['id'])).fetchone()
            if not row:
                fail(403)
            if row['expires_at'] <= b.clock():
                fail(410,'NOT_AUTHORIZED','A letöltőjegy lejárt. Új delivery szükséges.')
            if row['content_id'] and not c.execute('SELECT 1 FROM entitlements WHERE device_id=%s AND content_id=%s',(dev['id'],row['content_id'])).fetchone():
                fail()
            size = row['size_bytes']
            start,end,status = 0,size-1,200
            if range_header:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)',range_header)
                valid = bool(match and any(match.groups()))
                if valid:
                    first,last = match.groups()
                    if first:
                        start = int(first)
                        end = min(int(last),size-1) if last else size-1
                    else:
                        suffix = int(last)
                        valid = suffix>0
                        start,end = max(0,size-suffix),size-1
                    valid = valid and 0<=start<=end<size
                if not valid:
                    response = error(request.state.request_id,416,'INVALID_ARGUMENT','Érvénytelen bájttartomány.')
                    response.headers['Content-Range'] = f'bytes */{size}'
                    return response
                status = 206
            path = settings.storage / row['sha256']
            f = path.open('rb')
            if path.stat().st_size != size:
                f.close()
                fail(500,'IO_ERROR','A tartalomfájl nem érhető el.')
            f.seek(start)
        def chunks():
            try:
                remaining = end-start+1
                while remaining:
                    data = f.read(min(65536,remaining))
                    if not data:
                        raise OSError('Unexpected EOF')
                    remaining -= len(data)
                    yield data
            finally:
                f.close()
        headers={'Content-Length':str(end-start+1),'Accept-Ranges':'bytes','ETag':'"'+row['sha256']+'"'}
        if status==206:
            headers['Content-Range']=f'bytes {start}-{end}/{size}'
        return StreamingResponse(chunks(),status_code=status,media_type=row['media_type'],headers=headers)

    @app.post('/api/v1/orders',response_model=m.OrderCreated)
    def order(body:m.OrderRequest,access:Token,key:Key):
        return b.order(access,key,body.model_dump())
    @app.get('/api/v1/orders/{order_id}',response_model=m.OrderStatus)
    def order_status(order_id:m.UUID,access:Token):
        with b.db.transaction() as c:
            dev = b.auth(c,access)
            row = c.execute('SELECT * FROM orders WHERE id=%s AND device_id=%s FOR UPDATE',(order_id,dev['id'])).fetchone()
            if not row:
                fail(404,'NOT_FOUND','Ismeretlen rendelés.')
            if row['status']=='pending' and row['expires_at']<=b.clock():
                row['status']='cancelled'
                c.execute("UPDATE orders SET status='cancelled' WHERE id=%s",(order_id,))
            return dict(order_id=order_id,status=row['status'],expires_at=row['expires_at'])

    @app.post('/api/v1/payments/webhooks/{provider}',response_model=m.Accepted,
              openapi_extra={'requestBody':{'required':True,'content':{'application/json':{'schema':m.PaymentEvent.model_json_schema()}}}})
    async def webhook(provider:str,request:Request,
                      timestamp:Annotated[str,Header(alias='X-MM02-Timestamp',max_length=20)],
                      signature:Annotated[str,Header(alias='X-MM02-Signature',max_length=64)]):
        if provider != 'test' or not b.provider:
            fail(404,'NOT_FOUND','Ismeretlen szolgáltató.')
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(b.payment,await request.body(),timestamp,signature)

    def checkout_row(checkout):
        if not b.provider:
            fail(404,'NOT_FOUND','A tesztfizetés nincs engedélyezve.')
        with b.db.transaction() as c:
            row = c.execute('SELECT * FROM orders WHERE checkout_hash=%s',(digest(checkout),)).fetchone()
            if not row:
                fail(404,'NOT_FOUND','Ismeretlen checkout.')
            b.device(c,row['device_id'])
            if row['status'] not in ('pending','paid') or row['expires_at']<=b.clock():
                fail(410,'NOT_AUTHORIZED','A checkout lejárt vagy lezárult.')
            return row

    @app.get('/api/v1/test-checkout/{checkout}',response_class=HTMLResponse)
    def checkout_get(checkout:m.Secret):
        row = checkout_row(checkout)
        action = html.escape(settings.public_base+'test-checkout/'+checkout,quote=True)
        return HTMLResponse(f'<!doctype html><html lang="hu"><meta charset="utf-8"><title>Mesemondó tesztfizetés</title><h1>Tesztfizetés</h1><p>Valódi pénzmozgás nincs. Összeg: {row["total_minor"]//100}.{row["total_minor"]%100:02d} Ft.</p><form method="post" action="{action}"><button>Tesztvásárlás jóváhagyása</button></form></html>',headers={'Content-Security-Policy':"default-src 'none'; form-action 'self'; frame-ancestors 'none'"})

    @app.post('/api/v1/test-checkout/{checkout}',response_class=HTMLResponse)
    def checkout_post(checkout:m.Secret,origin:Annotated[str,Header(max_length=256)]):
        u = urlsplit(settings.public_base)
        if origin != u.scheme+'://'+u.netloc:
            fail()
        row = checkout_row(checkout)
        if row['status']=='paid':
            return HTMLResponse('<p>A tesztvásárlás már sikeres. Visszatérhetsz az alkalmazásba.</p>')
        # Test-provider adapter emits an authenticated event through the same verifier as HTTP webhooks.
        body = packed(dict(event_id=str(row['id']),order_id=str(row['id']),merchant=row['merchant'],amount_minor=row['total_minor'],currency=row['currency'],status='paid'))
        ts = str(b.clock())
        b.payment(body,ts,b.provider.signature(body,ts))
        return HTMLResponse('<p>Sikeres tesztvásárlás. Visszatérhetsz az alkalmazásba.</p>')

    @app.post('/api/v1/devices/me/recovery-key',response_model=m.Recovery)
    def recovery(body:m.RecoveryRequest,access:Token,key:Key):
        return b.recovery(access,key,body.model_dump())
    @app.post('/api/v1/transfers',response_model=m.Recovery)
    def transfer(body:m.TransferRequest,access:Token,key:Key):
        return b.transfer(access,key,body.model_dump(exclude_none=True))

    @app.get('/api/v1/firmware/latest',response_model=m.FirmwareDelivery)
    def firmware(access:Token,hardware_id:Annotated[str,Query(min_length=1,max_length=64)]):
        with b.db.transaction() as c:
            dev = b.auth(c,access)
            if dev['hardware_id'] != hardware_id:
                fail(403,'WRONG_HARDWARE','Eltérő célhardver.')
            row = c.execute('SELECT * FROM firmware_releases WHERE hardware_id=%s ORDER BY published_order DESC LIMIT 1',(hardware_id,)).fetchone()
            if not row:
                fail(404,'NOT_FOUND','Nincs ellenőrzött firmware-kiadás.')
            return dict(manifest_jws=row['manifest_jws'],files=[b.ticket(c,dev,row['file_id'])])
    return app
