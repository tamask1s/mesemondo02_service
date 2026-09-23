import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from mesemondo.admin import import_content
from mesemondo.crypto import packed,digest
from conftest import auth,headers,buy,delivery


def event(env,order,**changes):
    b,*_=env
    data=dict(event_id=str(uuid4()),order_id=order['order_id'],merchant=b.settings.merchant,amount_minor=10000,currency='HUF',status='paid')
    data.update(changes)
    raw=packed(data); ts=str(b.clock())
    return raw,{'X-MM02-Timestamp':ts,'X-MM02-Signature':b.provider.signature(raw,ts),'Content-Type':'application/json'}

def test_checkout_webhook_entitlement_delivery(env):
    b,c,devices,cid,manifest,_=env
    token,order=buy(env)
    assert c.get('/api/v1/orders/'+order['order_id'],headers=headers(token)).json()['status']=='paid'
    assert c.get('/api/v1/devices/me/entitlements',headers=headers(token)).json()['items'][0]['content_id']==cid
    d=delivery(env,token).json()
    m,mh=b.signer.verify(d['manifest_jws'],'MM02-MANIFEST')
    lic,_=b.signer.verify(d['license_jws'],'MM02-LICENSE')
    assert lic['manifest_sha256']==mh and lic['device_id']==devices[0][0]
    for f in d['files']:
        assert f['url'].startswith('https://www.timeonion.com/mesemondo/api/v1/downloads/')
        r=c.get(f['url'],headers=headers(token));assert r.status_code==200
        mf=next(x for x in m['files'] if x['file_id']==f['file_id'])
        assert digest(r.content)==mf['sha256']
        partial=c.get(f['url'],headers={**headers(token),'Range':'bytes=37-'})
        assert partial.status_code==206 and partial.content==r.content[37:]
        assert partial.headers['content-range']==f'bytes 37-{len(r.content)-1}/{len(r.content)}'
        assert int(partial.headers['content-length'])==len(partial.content)
        for ran in ('bytes=-20','bytes=1-20','bytes=0-999999'):
            assert c.get(f['url'],headers={**headers(token),'Range':ran}).status_code==206
        for ran in ('bytes=999999-','bytes=4-2','bytes=0-1,3-4','bytes=-0','items=0-1'):
            response=c.get(f['url'],headers={**headers(token),'Range':ran})
            assert response.status_code==416 and 'request_id' in response.json()


def test_parallel_orders_webhooks_idempotency(env):
    b,c,devices,cid,_,_=env
    token=auth(c,devices[0]); key=str(uuid4())
    def make_order(_):return c.post('/api/v1/orders',json={'content_ids':[cid]},headers=headers(token,key))
    with ThreadPoolExecutor(4) as pool:responses=list(pool.map(make_order,range(4)))
    assert all(r.status_code==200 for r in responses)
    assert len({r.json()['order_id'] for r in responses})==1
    order=responses[0].json(); body,h=event(env,order)
    with ThreadPoolExecutor(4) as pool:responses=list(pool.map(lambda _:c.post('/api/v1/payments/webhooks/test',content=body,headers=h),range(4)))
    assert all(r.status_code==200 for r in responses)
    with b.db.transaction() as db:
        assert db.execute('SELECT count(*) AS n FROM payment_events').fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM entitlements').fetchone()['n']==1
    data=json.loads(body);data['amount_minor']=1
    changed=packed(data);h['X-MM02-Signature']=b.provider.signature(changed,h['X-MM02-Timestamp'])
    assert c.post('/api/v1/payments/webhooks/test',content=changed,headers=h).status_code==409
    newer=auth(c,devices[0])
    assert c.post('/api/v1/orders',json={'content_ids':[cid]},headers=headers(newer,key)).json()==order
    assert c.post('/api/v1/orders',json={'content_ids':[str(uuid4())]},headers=headers(newer,key)).status_code==409


def test_webhook_validation_and_expired_checkout(env):
    b,c,devices,cid,_,_=env
    token=auth(c,devices[0])
    order=c.post('/api/v1/orders',json={'content_ids':[cid]},headers=headers(token,str(uuid4()))).json()
    for changes in ({'amount_minor':1},{'merchant':'wrong'}):
        raw,h=event(env,order,**changes)
        assert c.post('/api/v1/payments/webhooks/test',content=raw,headers=h).status_code==400
    raw,h=event(env,order);h['X-MM02-Signature']='0'*64
    assert c.post('/api/v1/payments/webhooks/test',content=raw,headers=h).status_code==401
    assert c.post(order['checkout_url'],headers={'Origin':'https://evil.invalid'}).status_code==403
    assert not c.get('/api/v1/devices/me/entitlements',headers=headers(token)).json()['items']
    b.now+=901
    assert c.get(order['checkout_url']).status_code==410
    raw,h=event(env,order)
    assert c.post('/api/v1/payments/webhooks/test',content=raw,headers=h).status_code==409
    token=auth(c,devices[0])
    assert c.get('/api/v1/orders/'+order['order_id'],headers=headers(token)).json()['status']=='cancelled'


def test_delivery_new_version_and_expired_ticket(env):
    b,c,devices,cid,_,sound=env
    token,_=buy(env);key=str(uuid4())
    old=delivery(env,token,key).json()
    import_content(b,cid,2,'Új cím','Új kiadás',10000,sound,[sound])
    new_token=auth(c,devices[0])
    assert delivery(env,new_token,key).json()==old
    new=delivery(env,new_token).json()
    assert b.signer.verify(new['manifest_jws'],'MM02-MANIFEST')[0]['version']==2
    b.now+=300
    new_token=auth(c,devices[0])
    assert c.get(old['files'][0]['url'],headers=headers(new_token)).status_code==410
    assert delivery(env,new_token,key).status_code==409
    assert delivery(env,new_token).status_code==200


def test_recovery_rotation_and_lost_response(env):
    b,c,devices,_,_,_=env
    token=auth(c,devices[0]);key=str(uuid4());url='/api/v1/devices/me/recovery-key'
    first=c.post(url,json={'rotate':False},headers=headers(token,key)).json()
    new_token=auth(c,devices[0])
    assert c.post(url,json={'rotate':False},headers=headers(new_token,key)).json()==first
    assert c.post(url,json={'rotate':False},headers=headers(new_token,str(uuid4()))).status_code==409
    rotated=c.post(url,json={'rotate':True},headers=headers(new_token,str(uuid4()))).json()
    assert rotated!=first
    with b.db.transaction() as db:
        assert db.execute('SELECT token_hash FROM recovery_hashes WHERE device_id=%s',(devices[0][0],)).fetchone()['token_hash']==digest(rotated['recovery_key'])
        ciphertext=db.execute('SELECT encrypted_result FROM idempotency WHERE key=%s',(key,)).fetchone()['encrypted_result']
        assert ciphertext is None  # Explicit rotation invalidates old secret responses.
    b.now+=121
    assert c.post(url,json={'rotate':True},headers=headers(new_token,str(uuid4()))).status_code==401
    b.now+=180
    new_token=auth(c,devices[0])
    assert c.post(url,json={'rotate':False},headers=headers(new_token,key)).status_code==409
    assert c.post(url,json={'rotate':True},headers=headers(new_token,str(uuid4()))).status_code==200


@pytest.mark.parametrize('proof',['token','recovery'])
def test_transfer_replay_and_revocation(env,proof):
    b,c,devices,cid,_,_=env
    old,_=buy(env);d=delivery(env,old).json()
    recovery=c.post('/api/v1/devices/me/recovery-key',json={'rotate':False},headers=headers(old,str(uuid4()))).json()['recovery_key']
    target=auth(c,devices[1]);key=str(uuid4())
    body={'source_device_id':devices[0][0],**({'source_access_token':old} if proof=='token' else {'recovery_key':recovery})}
    with ThreadPoolExecutor(3) as pool:
        responses=list(pool.map(lambda _:c.post('/api/v1/transfers',json=body,headers=headers(target,key)),range(3)))
    assert all(r.status_code==200 for r in responses),[r.text for r in responses]
    assert len({r.json()['recovery_key'] for r in responses})==1
    target=auth(c,devices[1])
    assert c.post('/api/v1/transfers',json=body,headers=headers(target,key)).json()==responses[0].json()
    assert c.get('/api/v1/devices/me/entitlements',headers=headers(old)).status_code==401
    assert c.get(d['files'][0]['url'],headers=headers(old)).status_code==401
    assert c.post('/api/v1/auth/challenges',json={'device_id':devices[0][0]}).status_code==401
    assert c.get('/api/v1/devices/me/entitlements',headers=headers(target)).json()['items'][0]['content_id']==cid
    assert delivery(env,target).status_code==200
    third=auth(c,devices[2])
    assert c.post('/api/v1/transfers',json=body,headers=headers(third,key)).status_code==401
    with b.db.transaction() as db:
        assert db.execute('SELECT count(*) AS n FROM transfer_audit').fetchone()['n']==1


def test_transfer_transaction_rolls_back(env,monkeypatch):
    b,c,devices,cid,_,_=env
    old,_=buy(env);target=auth(c,devices[1])
    def broken(*args):raise RuntimeError('injected failure with sensitive data')
    monkeypatch.setattr(b,'rotate',broken)
    r=c.post('/api/v1/transfers',json={'source_device_id':devices[0][0],'source_access_token':old},headers=headers(target,str(uuid4())))
    assert r.status_code==500 and 'sensitive' not in r.text
    assert c.get('/api/v1/devices/me/entitlements',headers=headers(old)).json()['items'][0]['content_id']==cid
    assert not c.get('/api/v1/devices/me/entitlements',headers=headers(target)).json()['items']
    with b.db.transaction() as db:assert db.execute('SELECT count(*) AS n FROM transfer_audit').fetchone()['n']==0


def test_transfer_proof_freshness_and_wrong_device(env):
    b,c,devices,_,_,_=env
    old=auth(c,devices[0]);target=auth(c,devices[1]);third=auth(c,devices[2])
    assert c.post('/api/v1/transfers',json={'source_device_id':devices[0][0],'source_access_token':third},headers=headers(target,str(uuid4()))).status_code==403
    assert c.post('/api/v1/transfers',json={'source_device_id':devices[0][0]},headers=headers(target,str(uuid4()))).status_code==422
    b.now+=121
    assert c.post('/api/v1/transfers',json={'source_device_id':devices[0][0],'source_access_token':old},headers=headers(target,str(uuid4()))).status_code==401


def test_started_stream_finishes_after_session_and_ticket_expire(env,monkeypatch,tmp_path):
    b,c,devices,cid,_,sound=env
    # Many valid MP3 frames ensure more than one streamed chunk.
    longer=tmp_path/'long.mp3';longer.write_bytes(sound.read_bytes()*100)
    import_content(b,cid,2,'Hosszabb teszt','Streamteszt',10000,sound,[longer])
    token,_=buy(env)
    d=delivery(env,token).json()
    manifest,_=b.signer.verify(d['manifest_jws'],'MM02-MANIFEST')
    chapter=next(f for f in manifest['files'] if f['role']=='chapter')
    target=next(f for f in d['files'] if f['file_id']==chapter['file_id'])
    import mesemondo.api as api
    original=api.StreamingResponse
    def expire_during_stream(iterator,**kwargs):
        def wrapped():
            for index,chunk in enumerate(iterator):
                if index==1:b.now+=301
                yield chunk
        return original(wrapped(),**kwargs)
    monkeypatch.setattr(api,'StreamingResponse',expire_during_stream)
    r=c.get(target['url'],headers=headers(token))
    assert r.status_code==200 and digest(r.content)==chapter['sha256']
    assert c.get(target['url'],headers={**headers(token),'Range':'bytes=10-'}).status_code==401
    new_token=auth(c,devices[0])
    assert c.get(target['url'],headers={**headers(new_token),'Range':'bytes=10-'}).status_code==410
    assert delivery(env,new_token).status_code==200


def test_checkout_paid_webhook_replay_after_device_transfer(env):
    b,c,devices,cid,_,_=env
    source=auth(c,devices[0]);target=auth(c,devices[1])
    order=c.post('/api/v1/orders',json={'content_ids':[cid]},headers=headers(source,str(uuid4()))).json()
    raw,h=event(env,order)
    assert c.post('/api/v1/payments/webhooks/test',content=raw,headers=h).status_code==200
    assert c.post('/api/v1/transfers',json={'source_device_id':devices[0][0],'source_access_token':source},headers=headers(target,str(uuid4()))).status_code==200
    assert c.post('/api/v1/payments/webhooks/test',content=raw,headers=h).status_code==200


def test_rotation_invalidates_older_secret_replay(env):
    b,c,devices,_,_,_=env
    token=auth(c,devices[0]);key=str(uuid4());url='/api/v1/devices/me/recovery-key'
    assert c.post(url,json={'rotate':False},headers=headers(token,key)).status_code==200
    assert c.post(url,json={'rotate':True},headers=headers(token,str(uuid4()))).status_code==200
    assert c.post(url,json={'rotate':False},headers=headers(token,key)).status_code==409


def test_admin_license_requires_entitlement(env,tmp_path):
    from mesemondo.admin import issue_license
    b,c,devices,cid,_,_=env
    output=tmp_path/'license.jws'
    with pytest.raises(ValueError):issue_license(b,devices[0][0],cid,1,output)
    buy(env)
    issue_license(b,devices[0][0],cid,1,output)
    license,_=b.signer.verify(output.read_text().strip(),'MM02-LICENSE')
    assert license['device_id']==devices[0][0] and license['content_id']==cid
    assert output.stat().st_mode&0o777==0o600
