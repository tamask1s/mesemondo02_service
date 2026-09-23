"""Explicit dev-only HTTPS check using an external emulator bundle. No token logging.

python emulator_http_check.py /EXTERNAL/app-emulator [--test-checkout]
The optional checkout is a zero-money test operation granting the bundle's device
access to the test catalog. Never use this helper with a production profile.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def unb64(value):
    return base64.urlsafe_b64decode(value+'='*(-len(value)%4))


def run(directory, checkout=False):
    device=json.loads((directory/'device.json').read_text())
    config=json.loads((directory/'config.local.json').read_text())
    if device['security_profile']!='dev' or config['BACKEND_PROFILE']!='dev':
        raise ValueError('This helper is only for dev emulation')
    base=config['API_BASE']
    if not base.startswith('https://') or not base.endswith('/api/v1/'):
        raise ValueError('HTTPS API base required')
    trust=json.loads(config['TRUSTED_KEYS'])
    private=serialization.load_pem_private_key((directory/'device-private.pem').read_bytes(),password=None)
    def checked(response):
        if response.status_code!=200:
            raise RuntimeError(f'HTTP {response.status_code}; sensitive response omitted')
        return response
    def verify(token,typ):
        h,p,s=token.split('.')
        header=json.loads(unb64(h));entry=trust[header['kid']]
        if header['alg']!='RS256' or header['typ']!=typ or entry['type']!=typ or entry['profile']!='dev':
            raise ValueError('Wrong signing key/purpose/profile')
        serialization.load_pem_public_key(entry['pem'].encode()).verify(unb64(s),(h+'.'+p).encode(),padding.PKCS1v15(),hashes.SHA256())
        raw=unb64(p)
        return json.loads(raw),hashlib.sha256(raw).hexdigest()
    with httpx.Client(timeout=30,follow_redirects=False) as client:
        checked(client.get(base+'readyz'))
        challenge=checked(client.post(base+'auth/challenges',json={'device_id':device['device_id']})).json()
        if challenge['device_id']!=device['device_id'] or challenge['audience']!='mm02-dev':
            raise ValueError('Challenge device/audience mismatch')
        data=('MM02-AUTH-1\n'+'\n'.join(str(challenge[k]) for k in ('audience','device_id','challenge_id','nonce','expires_at'))+'\n').encode('utf-8')
        signature=b64(private.sign(data,padding.PKCS1v15(),hashes.SHA256()))
        session=checked(client.post(base+'auth/sessions',json={'challenge_id':challenge['challenge_id'],'signature':signature})).json()
        auth={'Authorization':'Bearer '+session['access_token']}
        catalog=checked(client.get(base+'catalog')).json()
        print('HTTPS readiness, device proof and catalog: OK')
        if not checkout:
            return
        ids=[item['content_id'] for item in catalog['items']]
        if not ids:
            raise ValueError('Empty catalog')
        order=checked(client.post(base+'orders',headers={**auth,'Idempotency-Key':str(uuid4())},json={'content_ids':ids})).json()
        url=order['checkout_url']
        if not url.startswith(base+'test-checkout/'):
            raise ValueError('Not an internal test checkout; refusing')
        checked(client.get(url))
        parsed=urlsplit(base)
        checked(client.post(url,headers={'Origin':parsed.scheme+'://'+parsed.netloc}))
        state=checked(client.get(base+'orders/'+order['order_id'],headers=auth)).json()
        if state['status']!='paid':
            raise ValueError('Test order not paid')
        entitled=checked(client.get(base+'devices/me/entitlements',headers=auth)).json()
        if not set(ids).issubset({item['content_id'] for item in entitled['items']}):
            raise ValueError('Missing entitlements')
        total=0
        for cid in ids:
            delivery=checked(client.post(base+'contents/'+cid+'/delivery',headers={**auth,'Idempotency-Key':str(uuid4())})).json()
            manifest,mh=verify(delivery['manifest_jws'],'MM02-MANIFEST')
            license,_=verify(delivery['license_jws'],'MM02-LICENSE')
            if (license['device_id'],license['content_id'],license['content_version'],license['manifest_sha256'])!=(device['device_id'],cid,manifest['version'],mh):
                raise ValueError('License binding mismatch')
            for f in delivery['files']:
                if not f['url'].startswith(base+'downloads/'):
                    raise ValueError('Cross-origin/prefix download')
                metadata=next(x for x in manifest['files'] if x['file_id']==f['file_id'])
                digest=hashlib.sha256();length=0
                with client.stream('GET',f['url'],headers=auth) as response:
                    checked(response)
                    for block in response.iter_bytes():digest.update(block);length+=len(block)
                if digest.hexdigest()!=metadata['sha256'] or length!=metadata['size_bytes']:
                    raise ValueError('Downloaded file hash/size mismatch')
                # Short range uses very little memory even for long recordings.
                ranged=client.get(f['url'],headers={**auth,'Range':'bytes=17-48'})
                if ranged.status_code!=206 or ranged.headers.get('content-range')!=f'bytes 17-48/{length}' or len(ranged.content)!=32:
                    raise ValueError('Range mismatch')
                total+=1
        print(f'Test checkout, entitlements, JWS, {total} file hashes and Range: OK')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--test-checkout',action='store_true')
    args=parser.parse_args()
    run(args.directory,args.test_checkout)
