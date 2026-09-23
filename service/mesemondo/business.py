import hashlib
import hmac
import secrets
import time
from uuid import uuid4
from cryptography.fernet import Fernet
from .crypto import Signer, digest, packed, strict_json, verify_auth
from .db import Database
from .http import Failure
from .payments import TestProvider


def uid():
    return str(uuid4())

def fail(status=403, code='NOT_AUTHORIZED', message='A művelet nem engedélyezett.'):
    raise Failure(status,code,message)

class Backend:
    def __init__(self, settings, clock=None):
        self.settings = settings.validate()
        self.db = Database(settings)
        self.signer = Signer(settings)
        self.clock = clock or (lambda: int(time.time()))
        self.replay_key = settings.replay_key.read_bytes().strip()
        self.cipher = Fernet(self.replay_key)
        self.provider = TestProvider(settings.webhook_key.read_bytes()) if settings.test_payments else None

    def device(self, c, device_id, lock=True):
        row = c.execute('SELECT * FROM devices WHERE id=%s' + (' FOR UPDATE' if lock else ''), (device_id,)).fetchone()
        if not row or row['status'] != 'active' or row['security_profile'] != self.settings.profile:
            fail(401)
        return row

    def auth(self, c, token, lock=True, fresh=False):
        if not token or len(token) != 43:
            fail(401)
        row = c.execute('SELECT * FROM sessions WHERE token_hash=%s', (digest(token),)).fetchone()
        if not row:
            fail(401)
        dev = self.device(c, row['device_id'], lock)
        # Recheck after acquiring the device lock: a concurrent transfer may revoke it.
        row = c.execute('SELECT * FROM sessions WHERE token_hash=%s', (digest(token),)).fetchone()
        if not row or row['expires_at'] <= self.clock() or (fresh and self.clock()-row['issued_at'] > 120):
            fail(401)
        return dev

    def audit(self,c,action,device_id=None,object_id=None):
        c.execute('INSERT INTO audit(action,device_id,object_id,created_at) VALUES (%s,%s,%s,%s)', (action,device_id,object_id,self.clock()))

    def idempotent(self,c,dev,operation,key,body,action,ttl=300):
        fingerprint = hmac.new(self.replay_key, packed(body), hashlib.sha256).hexdigest()
        row = c.execute('SELECT * FROM idempotency WHERE device_id=%s AND operation=%s AND key=%s',(dev['id'],operation,key)).fetchone()
        if row:
            if not hmac.compare_digest(row['request_hash'],fingerprint):
                fail(409,'INVALID_ARGUMENT','Az idempotenciakulcs másik kéréshez tartozik.')
            if row['replay_until'] <= self.clock() or not row['encrypted_result']:
                fail(409,'NOT_AUTHORIZED','A visszajátszási időablak lejárt. Új művelet vagy recovery-forgatás szükséges.')
            return strict_json(self.cipher.decrypt(row['encrypted_result'].encode()))
        result = action()
        c.execute('INSERT INTO idempotency VALUES (%s,%s,%s,%s,%s,%s)',(dev['id'],operation,key,fingerprint,self.cipher.encrypt(packed(result)).decode(),self.clock()+ttl))
        return result

    def challenge(self, device_id):
        if not self.db.rate('challenge:'+device_id,5,self.clock()):
            fail(429,'BUSY','Túl sok hitelesítési kérés.')
        with self.db.transaction() as c:
            self.device(c,device_id)
            result = dict(device_id=device_id,challenge_id=uid(),nonce=secrets.token_urlsafe(32),expires_at=self.clock()+120,audience=self.settings.audience)
            c.execute('INSERT INTO challenges(id,device_id,nonce,expires_at) VALUES (%s,%s,%s,%s)', (result['challenge_id'],device_id,result['nonce'],result['expires_at']))
            return result

    def session(self, challenge_id, signature):
        with self.db.transaction() as c:
            row = c.execute('SELECT * FROM challenges WHERE id=%s',(challenge_id,)).fetchone()
            if not row:
                fail(401)
            if not self.db.rate('signature:'+str(row['device_id']),10,self.clock()):
                fail(429,'BUSY','Túl sok hitelesítési próbálkozás.')
            dev = self.device(c,row['device_id'])
            row = c.execute('SELECT * FROM challenges WHERE id=%s FOR UPDATE',(challenge_id,)).fetchone()
            if row['consumed'] or row['expires_at'] <= self.clock():
                fail(401)
            challenge = dict(device_id=str(dev['id']),challenge_id=challenge_id,nonce=row['nonce'],expires_at=row['expires_at'],audience=self.settings.audience)
            try:
                verify_auth(dev['public_key'],challenge,signature)
            except Exception:
                fail(401,'INVALID_SIGNATURE','Érvénytelen eszközaláírás.')
            token = secrets.token_urlsafe(32)
            c.execute('UPDATE challenges SET consumed=true WHERE id=%s',(challenge_id,))
            c.execute('INSERT INTO sessions VALUES (%s,%s,%s,%s)',(digest(token),dev['id'],self.clock(),self.clock()+300))
            return dict(access_token=token,device_id=str(dev['id']),expires_at=self.clock()+300)

    def ticket(self,c,dev,file_id,content_id=None):
        token = secrets.token_urlsafe(32)
        until = self.clock()+300
        c.execute('INSERT INTO tickets VALUES (%s,%s,%s,%s,%s)',(digest(token),dev['id'],file_id,content_id,until))
        return dict(file_id=str(file_id),url=self.settings.public_base+'downloads/'+token,expires_at=until)

    def delivery(self, token, content_id, key):
        with self.db.transaction() as c:
            dev = self.auth(c,token)
            entitlement = c.execute('SELECT * FROM entitlements WHERE device_id=%s AND content_id=%s',(dev['id'],content_id)).fetchone()
            if not entitlement:
                fail()
            def action():
                row = c.execute('SELECT * FROM content_versions WHERE content_id=%s ORDER BY version DESC LIMIT 1',(content_id,)).fetchone()
                if not row:
                    fail(404,'NOT_FOUND','Nincs kiadott tartalom.')
                license = dict(v=1,kind='license',device_id=str(dev['id']),content_id=content_id,content_version=row['version'],manifest_sha256=row['manifest_sha256'],grant_id=str(entitlement['grant_id']),issued_at=self.clock())
                files = c.execute('SELECT file_id FROM content_files WHERE content_id=%s AND version=%s ORDER BY file_id',(content_id,row['version'])).fetchall()
                return dict(manifest_jws=row['manifest_jws'],license_jws=self.signer.sign(license,'MM02-LICENSE'),files=[self.ticket(c,dev,f['file_id'],content_id) for f in files])
            return self.idempotent(c,dev,'delivery:'+content_id,key,{},action)

    def order(self,token,key,body):
        if not self.provider:
            fail(503,'BUSY','Fizetési szolgáltató nincs beállítva.')
        ids = body['content_ids']
        if len(ids) != len(set(ids)):
            fail(422,'INVALID_ARGUMENT','Ismételt tartalomazonosító.')
        with self.db.transaction() as c:
            dev = self.auth(c,token)
            def action():
                rows = c.execute('SELECT * FROM contents WHERE id=ANY(%s::uuid[]) ORDER BY id FOR SHARE',(ids,)).fetchall()
                if len(rows) != len(ids):
                    fail(404,'NOT_FOUND','Ismeretlen tartalom.')
                order_id, checkout = uid(), secrets.token_urlsafe(32)
                total = sum(x['price_minor'] for x in rows)
                if total > 9007199254740991:
                    fail(422,'INVALID_ARGUMENT','Túl nagy összeg.')
                c.execute('INSERT INTO orders VALUES (%s,%s,\'pending\',%s,\'HUF\',%s,%s,%s,%s)',(order_id,dev['id'],total,self.provider.name,self.settings.merchant,self.clock()+900,digest(checkout)))
                for row in rows:
                    c.execute('INSERT INTO order_items VALUES (%s,%s,%s)',(order_id,row['id'],row['price_minor']))
                return dict(order_id=order_id,checkout_url=self.settings.public_base+'test-checkout/'+checkout)
            return self.idempotent(c,dev,'order',key,body,action,ttl=86400*90)

    def payment(self,body,timestamp,signature):
        if not self.provider:
            fail(404,'NOT_FOUND','Ismeretlen szolgáltató.')
        try:
            event = self.provider.verify(body,timestamp,signature,self.clock())
        except Exception:
            fail(401)
        with self.db.transaction() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(self.provider.name+event.event_id,))
            previous = c.execute('SELECT * FROM payment_events WHERE provider=%s AND event_id=%s',(self.provider.name,event.event_id)).fetchone()
            if previous:
                if previous['body_hash'] != digest(body):
                    fail(409,'INVALID_ARGUMENT','Eltérő ismételt fizetési esemény.')
                return {'accepted':True}
            order = c.execute('SELECT * FROM orders WHERE id=%s',(event.order_id,)).fetchone()
            if not order:
                fail(404,'NOT_FOUND','Ismeretlen rendelés.')
            # All business writers acquire the device lock before order/event locks.
            dev = self.device(c,order['device_id'])
            order = c.execute('SELECT * FROM orders WHERE id=%s FOR UPDATE',(event.order_id,)).fetchone()
            if (event.merchant,event.amount_minor,event.currency) != (order['merchant'],order['total_minor'],order['currency']) or order['provider'] != self.provider.name:
                fail(400,'INVALID_ARGUMENT','A fizetési adatok nem egyeznek.')
            if order['status'] != 'pending':
                if order['status'] != event.status:
                    fail(409,'INVALID_ARGUMENT','A rendelés már lezárult.')
            elif order['expires_at'] <= self.clock():
                fail(409,'NOT_AUTHORIZED','A tesztrendelés lejárt.')
            else:
                c.execute('UPDATE orders SET status=%s WHERE id=%s',(event.status,order['id']))
                if event.status == 'paid':
                    for item in c.execute('SELECT content_id FROM order_items WHERE order_id=%s',(order['id'],)).fetchall():
                        c.execute('INSERT INTO entitlements VALUES (%s,%s,%s,%s) ON CONFLICT(device_id,content_id) DO NOTHING',(dev['id'],item['content_id'],uid(),self.clock()))
            c.execute('INSERT INTO payment_events VALUES (%s,%s,%s,%s)',(self.provider.name,event.event_id,digest(body),order['id']))
            self.audit(c,'payment.'+event.status,dev['id'],order['id'])
            return {'accepted':True}

    def rotate(self,c,dev):
        c.execute("UPDATE idempotency SET encrypted_result=NULL WHERE device_id=%s AND operation IN ('recovery','transfer')",(dev['id'],))
        recovery = secrets.token_urlsafe(32)
        c.execute('INSERT INTO recovery_hashes VALUES (%s,%s,%s) ON CONFLICT(device_id) DO UPDATE SET token_hash=EXCLUDED.token_hash,issued_at=EXCLUDED.issued_at',(dev['id'],digest(recovery),self.clock()))
        self.audit(c,'recovery.rotate',dev['id'])
        return {'recovery_key':recovery}

    def recovery(self,token,key,body):
        with self.db.transaction() as c:
            dev = self.auth(c,token,fresh=True)
            def action():
                if not body['rotate'] and c.execute('SELECT 1 FROM recovery_hashes WHERE device_id=%s',(dev['id'],)).fetchone():
                    fail(409,'INVALID_ARGUMENT','Már van recovery-kulcs. Kifejezett forgatás szükséges.')
                return self.rotate(c,dev)
            return self.idempotent(c,dev,'recovery',key,body,action)

    def transfer(self,token,key,body):
        if bool(body.get('source_access_token')) == bool(body.get('recovery_key')):
            fail(422,'INVALID_ARGUMENT','Pontosan egy forrásbizonyíték szükséges.')
        with self.db.transaction() as c:
            target = self.auth(c,token,lock=False)
            source_id = body['source_device_id']
            if source_id == str(target['id']):
                fail(422,'INVALID_ARGUMENT','A két eszköz nem lehet azonos.')
            c.execute('SELECT id FROM devices WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE',([source_id,str(target['id'])],)).fetchall()
            target = self.auth(c,token)
            def action():
                source = self.device(c,source_id)
                if body.get('source_access_token'):
                    proof = self.auth(c,body['source_access_token'],fresh=True)
                    if proof['id'] != source['id']:
                        fail()
                else:
                    recovery = c.execute('SELECT token_hash FROM recovery_hashes WHERE device_id=%s',(source_id,)).fetchone()
                    if not recovery or not hmac.compare_digest(recovery['token_hash'],digest(body['recovery_key'])):
                        fail()
                for row in c.execute('SELECT * FROM entitlements WHERE device_id=%s',(source_id,)).fetchall():
                    c.execute('INSERT INTO entitlements VALUES (%s,%s,%s,%s) ON CONFLICT(device_id,content_id) DO NOTHING',(target['id'],row['content_id'],uid(),self.clock()))
                c.execute('DELETE FROM entitlements WHERE device_id=%s',(source_id,))
                c.execute("UPDATE devices SET status='revoked' WHERE id=%s",(source_id,))
                for table in ('sessions','tickets','recovery_hashes'):
                    c.execute(f'DELETE FROM {table} WHERE device_id=%s',(source_id,))
                c.execute('UPDATE idempotency SET encrypted_result=NULL WHERE device_id=%s',(source_id,))
                c.execute("UPDATE orders SET status='cancelled' WHERE device_id=%s AND status='pending'",(source_id,))
                c.execute('INSERT INTO transfer_audit VALUES (%s,%s,%s,%s)',(uid(),source_id,target['id'],self.clock()))
                self.audit(c,'transfer',target['id'],source_id)
                return self.rotate(c,target)
            # Replay comes BEFORE source auth: success already revoked its token/recovery key.
            return self.idempotent(c,target,'transfer',key,body,action)
