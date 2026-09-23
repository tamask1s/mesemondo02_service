import socket
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
import uvicorn
from mesemondo.api import create_app
from mesemondo.crypto import packed,digest
from conftest import auth,headers


def test_real_http_postgresql_acceptance(env):
    b,_,devices,cid,_,_=env
    app=create_app(b.settings,b)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,access_log=False,log_level='critical',proxy_headers=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.05)
        assert server.started
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=10,follow_redirects=False) as c:
            source=auth(c,devices[0])
            order=c.post('/api/v1/orders',json={'content_ids':[cid]},headers=headers(source,str(uuid4()))).json()
            assert c.get(urlsplit(order['checkout_url']).path).status_code==200
            # Simulated external test provider delivers an authenticated webhook over real HTTP.
            event=packed(dict(event_id=str(uuid4()),order_id=order['order_id'],merchant=b.settings.merchant,amount_minor=10000,currency='HUF',status='paid'))
            ts=str(b.clock())
            wh=c.post('/api/v1/payments/webhooks/test',content=event,headers={'X-MM02-Timestamp':ts,'X-MM02-Signature':b.provider.signature(event,ts),'Content-Type':'application/json'})
            assert wh.status_code==200,wh.text
            assert c.get('/api/v1/devices/me/entitlements',headers=headers(source)).json()['items'][0]['content_id']==cid
            d=c.post('/api/v1/contents/'+cid+'/delivery',headers=headers(source,str(uuid4()))).json()
            manifest,_=b.signer.verify(d['manifest_jws'],'MM02-MANIFEST')
            f=d['files'][0];path=urlsplit(f['url']).path
            data=c.get(path,headers=headers(source));assert data.status_code==200
            assert digest(data.content)==next(x['sha256'] for x in manifest['files'] if x['file_id']==f['file_id'])
            resumed=c.get(path,headers={**headers(source),'Range':'bytes=17-'})
            assert resumed.status_code==206 and resumed.content==data.content[17:]
            recovery=c.post('/api/v1/devices/me/recovery-key',json={'rotate':False},headers=headers(source,str(uuid4()))).json()['recovery_key']
            target=auth(c,devices[1]);key=str(uuid4());body={'source_device_id':devices[0][0],'recovery_key':recovery}
            transfer=c.post('/api/v1/transfers',json=body,headers=headers(target,key))
            assert transfer.status_code==200,transfer.text
            assert c.post('/api/v1/transfers',json=body,headers=headers(target,key)).json()==transfer.json()
            assert c.get(path,headers=headers(source)).status_code==401
    finally:
        server.should_exit=True
        thread.join(10)
        sock.close()
        assert not thread.is_alive()
