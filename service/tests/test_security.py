import dataclasses
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from mesemondo.config import ROOT
from mesemondo.crypto import auth_bytes,b64,unb64,verify_auth,verify_jws,verify_license_binding,strict_json
from mesemondo.admin import register
from mesemondo.business import Backend
from mesemondo.db import Database
from conftest import auth,headers,buy,delivery


def test_shared_security_fixtures(environment):
    s,_=environment
    fixture=json.loads((ROOT/'contracts/fixtures/security.json').read_text())
    assert auth_bytes(fixture['challenge'])==unb64(fixture['auth_bytes_base64url'])
    verify_auth((ROOT/'contracts/fixtures/TEST-ONLY-device-public.pem').read_text(),fixture['challenge'],fixture['signature'])
    b=Backend(s)
    manifest,mh=b.signer.verify(fixture['manifest_jws'],'MM02-MANIFEST')
    lic,_=b.signer.verify(fixture['license_jws'],'MM02-LICENSE')
    verify_license_binding(manifest,mh,lic,fixture['device_id'])
    b.signer.verify(fixture['firmware_jws'],'MM02-FIRMWARE')
    for name in ('bad_signature_jws','duplicate_payload_jws'):
        with pytest.raises(Exception):b.signer.verify(fixture[name],'MM02-LICENSE')
    for name in ('wrong_device_license_jws','wrong_hash_license_jws'):
        lic,_=b.signer.verify(fixture[name],'MM02-LICENSE')
        with pytest.raises(ValueError):verify_license_binding(manifest,mh,lic,fixture['device_id'])
    for header in ({'alg':'none','kid':'test-content-1','typ':'MM02-MANIFEST'}, {'alg':'RS256','kid':'unknown','typ':'MM02-MANIFEST'}, {'alg':'RS256','kid':'test-content-1','typ':'MM02-MANIFEST','jku':'https://evil.invalid'}):
        _,p,sig=fixture['manifest_jws'].split('.')
        with pytest.raises(Exception):b.signer.verify(b64(json.dumps(header).encode())+'.'+p+'.'+sig,'MM02-MANIFEST')


def test_parallel_nonce_single_consumer(env):
    b,c,devices,_,_,_=env
    challenge=c.post('/api/v1/auth/challenges',json={'device_id':devices[0][0]}).json()
    signature=b64(devices[0][1].sign(auth_bytes(challenge),padding.PKCS1v15(),hashes.SHA256()))
    body={'challenge_id':challenge['challenge_id'],'signature':signature}
    with ThreadPoolExecutor(4) as pool:
        results=list(pool.map(lambda _:c.post('/api/v1/auth/sessions',json=body).status_code,range(4)))
    assert sorted(results)==[200,401,401,401]


def test_invalid_auth_and_profile(env):
    b,c,devices,_,_,_=env
    assert c.post('/api/v1/auth/challenges',json={'device_id':str(uuid4())}).status_code==401
    challenge=c.post('/api/v1/auth/challenges',json={'device_id':devices[0][0]}).json()
    sig=b64(devices[1][1].sign(auth_bytes(challenge),padding.PKCS1v15(),hashes.SHA256()))
    assert c.post('/api/v1/auth/sessions',json={'challenge_id':challenge['challenge_id'],'signature':sig}).status_code==401
    b.now+=120
    sig=b64(devices[0][1].sign(auth_bytes(challenge),padding.PKCS1v15(),hashes.SHA256()))
    assert c.post('/api/v1/auth/sessions',json={'challenge_id':challenge['challenge_id'],'signature':sig}).status_code==401
    with b.db.transaction() as db:db.execute("UPDATE devices SET security_profile='production' WHERE id=%s",(devices[0][0],))
    assert c.post('/api/v1/auth/challenges',json={'device_id':devices[0][0]}).status_code==401
    with pytest.raises(ValueError):Database(dataclasses.replace(b.settings,profile='production',test_payments=False)).check_profile()
    with pytest.raises(ValueError):Backend(dataclasses.replace(b.settings,profile='production',test_payments=False))


def test_ownership_and_expiry(env):
    b,c,devices,cid,_,_=env
    owner,order=buy(env)
    other=auth(c,devices[1])
    assert delivery(env,other).status_code==403
    assert c.get('/api/v1/orders/'+order['order_id'],headers=headers(other)).status_code==404
    d=delivery(env,owner).json()
    assert c.get(d['files'][0]['url'],headers=headers(other)).status_code==403
    assert c.get(d['files'][0]['url']).status_code==401
    b.now+=300
    assert c.get('/api/v1/devices/me/entitlements',headers=headers(owner)).status_code==401


@pytest.mark.parametrize('path,body',[
 ('/api/v1/auth/challenges',b'{"device_id":"x","device_id":"y"}'),
 ('/api/v1/orders',b'{"content_ids":NaN}'),
 ('/api/v1/auth/challenges',b'{"device_id":"\\ud800"}'),
 ('/api/v1/auth/challenges',b'{}'),
])
def test_validation_envelope(env,path,body):
    _,c,_,_,_,_=env
    r=c.post(path,content=body,headers={'Content-Type':'application/json'})
    assert r.status_code in (401,422)
    assert set(r.json())=={'error','request_id'}
    assert 'input' not in r.text


def test_limits_and_redirect_free(env):
    b,c,devices,_,_,_=env
    for _ in range(5):assert c.post('/api/v1/auth/challenges',json={'device_id':devices[0][0]}).status_code==200
    assert c.post('/api/v1/auth/challenges',json={'device_id':devices[0][0]}).status_code==429
    assert c.post('/api/v1/auth/challenges',content=b'x'*65537).status_code==413
    r=c.get('/api/v1/catalog/',follow_redirects=False)
    assert r.status_code==404 and 'request_id' in r.json()
    assert c.get('/api/v1/catalog?limit=101').status_code==422
    assert c.get('/api/v1/catalog?cursor=invalid').status_code==422
    assert c.get('/not-found').status_code==404
    assert c.get('/api/v1/catalog',headers={'X-Large':'x'*9000}).status_code==431
    with b.db.transaction() as db:db.execute('UPDATE rate_limits SET count=301')
    assert c.get('/api/v1/catalog').status_code==429


def test_database_stores_hashes_and_logs_no_secrets(env,caplog,monkeypatch):
    b,c,devices,cid,_,_=env
    token,_=buy(env)
    d=delivery(env,token).json()
    ticket=d['files'][0]['url'].rsplit('/',1)[-1]
    with b.db.transaction() as db:
        assert db.execute('SELECT token_hash FROM sessions').fetchone()['token_hash']!=token
        assert db.execute('SELECT token_hash FROM tickets LIMIT 1').fetchone()['token_hash']!=ticket
    def broken(*args,**kwargs):raise RuntimeError(token+' '+ticket)
    monkeypatch.setattr(b,'delivery',broken)
    r=delivery(env,token)
    assert r.status_code==500
    assert token not in caplog.text and ticket not in caplog.text
    assert token not in r.text and ticket not in r.text


def test_pagination_and_immutable_version(env):
    from mesemondo.admin import import_content
    b,c,devices,cid,_,sound=env
    import_content(b,'b0000000-0000-4000-8000-000000000000',1,'Második','Teszt',10000,sound,[sound])
    first=c.get('/api/v1/catalog?limit=1').json()
    assert len(first['items'])==1 and first['next_cursor']
    second=c.get('/api/v1/catalog',params={'limit':1,'cursor':first['next_cursor']}).json()
    assert second['items'][0]['content_id']!=first['items'][0]['content_id'] and second['next_cursor'] is None
    with pytest.raises(ValueError):import_content(b,cid,1,'Felülírás','Tiltott',10000,sound,[sound])
