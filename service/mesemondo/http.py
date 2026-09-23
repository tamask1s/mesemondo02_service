"""Bounded request parsing and secret-free exception handling."""
import asyncio
import logging
import time
from uuid import uuid4
from starlette.responses import JSONResponse
from .crypto import strict_json

class Failure(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message

def error(request_id, status, code, message):
    return JSONResponse({'error':{'code':code,'message':message}, 'request_id':request_id}, status_code=status, headers={'Cache-Control':'no-store','X-Request-ID':request_id})

class Guard:
    def __init__(self, app, database):
        self.app, self.database = app, database

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        scope.setdefault('state', {})['request_id'] = request_id
        started = False
        async def safe_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
                message['headers'] = [(k,v) for k,v in message['headers'] if k.lower() not in (b'cache-control',b'x-request-id')]
                message['headers'] += [(b'cache-control', b'no-store'), (b'x-request-id',request_id.encode()), (b'x-content-type-options',b'nosniff'), (b'referrer-policy',b'no-referrer')]
            await send(message)
        try:
            if len(scope.get('path','')) > 2048 or sum(len(k)+len(v) for k,v in scope['headers']) > 8192 or len(scope.get('query_string',b'')) > 2048:
                raise Failure(431,'INVALID_ARGUMENT','Túl hosszú kérésfejléc.')
            ip = scope.get('client', ('unknown',0))[0]
            # A global/IP limit bounds every route, including unknown paths and malformed requests.
            if not await asyncio.to_thread(self.database.rate, 'ip:'+ip, 300, int(time.time())):
                raise Failure(429,'BUSY','Túl sok kérés. Próbáld újra később.')
            path = scope.get('path','')
            groups = (('/auth/',40),('/downloads/',120),('/payments/',120),('/transfers',10),
                      ('/recovery-key',10),('/test-checkout/',30),('/orders',60),
                      ('/catalog',120),('/entitlements',120),('/delivery',60),('/firmware/',60))
            for group, limit in groups:
                if group in path:
                    if not await asyncio.to_thread(self.database.rate, 'route:'+group+':'+ip, limit, int(time.time())):
                        raise Failure(429,'BUSY','Túl sok kérés ezen a végponton.')
                    break
            body = bytearray()
            async with asyncio.timeout(15):
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        return
                    body.extend(message.get('body',b''))
                    if len(body) > 65536:
                        raise Failure(413,'INVALID_ARGUMENT','Túl nagy kérés.')
                    if not message.get('more_body',False):
                        break
            headers = dict(scope['headers'])
            if body and 'application/json' in headers.get(b'content-type',b'').decode('latin1'):
                try:
                    strict_json(body.decode('utf-8'))
                except (ValueError, UnicodeError, RecursionError):
                    raise Failure(422,'INVALID_ARGUMENT','Hibás JSON.')
            consumed = False
            async def replay_receive():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {'type':'http.request','body':bytes(body),'more_body':False}
                return await receive()
            await self.app(scope, replay_receive, safe_send)
        except Failure as e:
            if not started:
                await error(request_id,e.status,e.code,e.message)(scope, receive, send)
        except TimeoutError:
            if not started:
                await error(request_id,408,'INVALID_ARGUMENT','Kérés időtúllépés.')(scope,receive,send)
        except Exception as e:
            # Never log URLs, body, tokens, configuration or exception messages/tracebacks.
            logging.getLogger('mesemondo').error('request_id=%s error_type=%s',request_id,type(e).__name__)
            if not started:
                await error(request_id,500,'INTERNAL','Belső hiba.')(scope,receive,send)
