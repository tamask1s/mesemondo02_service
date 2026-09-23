import dataclasses
import json
import os
import time
from pathlib import Path
from uuid import uuid4
import psycopg
import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from mesemondo.admin import register, import_content
from mesemondo.api import create_app
from mesemondo.business import Backend
from mesemondo.config import Settings, ROOT
from mesemondo.crypto import b64, auth_bytes
from mesemondo.db import Database
from mesemondo.media import normalize

@pytest.fixture(scope='session')
def environment(tmp_path_factory):
    settings=Settings.load()
    if settings.profile!='dev':
        raise ValueError('Tests require an isolated dev configuration')
    name='mm02_test_'+uuid4().hex
    with psycopg.connect(settings.database_url,autocommit=True) as c:
        c.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(name)))
    dsn=psycopg.conninfo.make_conninfo(settings.database_url,dbname=name)
    directory=tmp_path_factory.mktemp('data')
    settings=dataclasses.replace(settings,database_url=dsn,storage=directory/'content')
    Database(settings).migrate()
    sound=directory/'sound.mp3'
    normalize(ROOT/'contracts/fixtures/mono-32000-64k.mp3',sound)
    yield settings,sound
    with psycopg.connect(Settings.load().database_url,autocommit=True) as c:
        c.execute(psycopg.sql.SQL('DROP DATABASE {} WITH (FORCE)').format(psycopg.sql.Identifier(name)))

@pytest.fixture
def env(environment):
    settings,sound=environment
    b=Backend(settings)
    b.now=int(time.time())
    b.clock=lambda:b.now
    with b.db.transaction() as c:
        tables=c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('schema_migrations','backend_profile')").fetchall()
        c.execute(psycopg.sql.SQL('TRUNCATE {} RESTART IDENTITY CASCADE').format(psycopg.sql.SQL(',').join(psycopg.sql.Identifier(x['tablename']) for x in tables)))
    devices=[]
    for _ in range(3):
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        did=str(uuid4())
        pem=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        register(b,did,pem,'dev')
        devices.append((did,key))
    content_id='a0000000-0000-4000-8000-000000000000'
    manifest=import_content(b,content_id,1,'Tesztmese','Lejátszható teszthang',10000,sound,[sound])
    app=create_app(settings,b)
    with TestClient(app,base_url='https://www.timeonion.com/mesemondo') as client:
        yield b,client,devices,content_id,manifest,sound


def auth(client,device):
    did,key=device
    r=client.post('/api/v1/auth/challenges',json={'device_id':did})
    assert r.status_code==200,r.text
    challenge=r.json()
    signature=b64(key.sign(auth_bytes(challenge),padding.PKCS1v15(),hashes.SHA256()))
    r=client.post('/api/v1/auth/sessions',json={'challenge_id':challenge['challenge_id'],'signature':signature})
    assert r.status_code==200,r.text
    return r.json()['access_token']

def headers(token,key=None):
    d={'Authorization':'Bearer '+token}
    if key:d['Idempotency-Key']=key
    return d

def buy(env,device_index=0):
    b,c,devices,cid,_,_=env
    token=auth(c,devices[device_index])
    r=c.post('/api/v1/orders',json={'content_ids':[cid]},headers=headers(token,str(uuid4())))
    assert r.status_code==200,r.text
    order=r.json()
    r=c.get(order['checkout_url']);assert r.status_code==200,r.text
    r=c.post(order['checkout_url'],headers={'Origin':'https://www.timeonion.com'})
    assert r.status_code==200,r.text
    return token,order

def delivery(env,token,key=None):
    b,c,_,cid,_,_=env
    return c.post('/api/v1/contents/'+cid+'/delivery',headers=headers(token,key or str(uuid4())))
