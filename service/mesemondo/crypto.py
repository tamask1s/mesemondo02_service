import base64
import hashlib
import json
import re
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from jsonschema import Draft202012Validator
from .config import ROOT

SCHEMAS = json.loads((ROOT / 'contracts/packages-v1.schema.json').read_text())['$defs']
CHALLENGE = json.loads((ROOT / 'contracts/local-v2.schema.json').read_text())['$defs']['challenge']
VALIDATORS = {kind: Draft202012Validator(schema) for kind, schema in SCHEMAS.items()}
CHALLENGE_VALIDATOR = Draft202012Validator(CHALLENGE)

def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')

def unb64(s):
    if not isinstance(s, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', s):
        raise ValueError('Invalid base64url')
    out = base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
    if b64(out) != s:
        raise ValueError('Noncanonical base64url')
    return out

def digest(data):
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()

def strict_json(data):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('Duplicate JSON key')
            result[k] = v
        return result
    def bad(_):
        raise ValueError('Invalid JSON number')
    obj = json.loads(data, object_pairs_hook=pairs, parse_constant=bad, parse_float=bad)
    json.dumps(obj, ensure_ascii=False, allow_nan=False).encode('utf-8')
    return obj

def packed(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()

def public_key(pem):
    key = serialization.load_pem_public_key(pem.encode() if isinstance(pem, str) else pem)
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size != 3072 or key.public_numbers().e != 65537:
        raise ValueError('RSA-3072/e=65537 required')
    if b'BEGIN PUBLIC KEY' not in (pem.encode() if isinstance(pem, str) else pem):
        raise ValueError('SubjectPublicKeyInfo required')
    return key

def fingerprint(key):
    return digest(key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))

# Public test-key fingerprints remain denied even when fixtures are not deployed.
TEST_FINGERPRINTS = {
    '12adcc2c5e595c04424c380fc7487b71f4db13ae6d10d02733c3ad5258b768d2',
    '700d106498cfbe5845e6a954f05c1d8b15d1affb89aad89202b55ad2d1c0e3b0',
    'b335a8e1decde926ea6968495cc7d79242fa9c69ec0f42dd1f58114a5e5e5744',
    '56713545d5410f0eec9e612d7d7f889284e80f7403f57247bf48d3a11a2ea77c',
}

def reject_fixture_key(key):
    if fingerprint(key) in TEST_FINGERPRINTS:
        raise ValueError('Fixture key forbidden in production')

def auth_bytes(challenge):
    CHALLENGE_VALIDATOR.validate(challenge)
    if len(unb64(challenge['nonce'])) != 32:
        raise ValueError('Invalid nonce')
    return ('MM02-AUTH-1\n' + '\n'.join(str(challenge[k]) for k in ('audience','device_id','challenge_id','nonce','expires_at')) + '\n').encode()

def verify_auth(pem, challenge, signature):
    raw = unb64(signature)
    if len(raw) != 384:
        raise ValueError('Invalid signature size')
    public_key(pem).verify(raw, auth_bytes(challenge), padding.PKCS1v15(), hashes.SHA256())

def validate_package(obj, kind):
    VALIDATORS[kind].validate(obj)
    if kind == 'content':
        files = obj['files']
        titles = [f for f in files if f['role'] == 'title']
        chapters = [f for f in files if f['role'] == 'chapter']
        if len(titles) != 1 or titles[0]['chapter_index'] is not None or sorted(f['chapter_index'] for f in chapters) != list(range(len(chapters))) or len({f['file_id'] for f in files}) != len(files):
            raise ValueError('Invalid title/chapters/file IDs')

class Signer:
    def __init__(self, settings):
        self.settings = settings
        self.trust = strict_json(settings.trusted_keys.read_bytes())
        self.private = {}
        for typ, kid, path in (('MM02-MANIFEST', settings.manifest_kid, settings.manifest_key), ('MM02-LICENSE', settings.license_kid, settings.license_key)):
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            pub = key.public_key()
            if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != 3072 or pub.public_numbers().e != 65537:
                raise ValueError('Invalid signing key')
            entry = self.trust[kid]
            if entry['type'] != typ or entry['profile'] != settings.profile or fingerprint(public_key(entry['pem'])) != fingerprint(pub):
                raise ValueError('Signing key/trust mismatch')
            self.private[typ] = (kid, key)
        fingerprints = []
        for kid, entry in self.trust.items():
            if set(entry) != {'pem','profile','type'} or entry['profile'] != settings.profile or entry['type'] not in ('MM02-MANIFEST','MM02-LICENSE','MM02-FIRMWARE'):
                raise ValueError('Invalid trust entry')
            pub = public_key(entry['pem'])
            if settings.profile == 'production':
                reject_fixture_key(pub)
                if kid.lower().startswith(('test','dev')):
                    raise ValueError('Test kid forbidden in production')
            fingerprints.append(fingerprint(pub))
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError('Signing purposes must use separate keys')

    def sign(self, payload, typ):
        kind = {'MM02-MANIFEST':'content','MM02-LICENSE':'license'}[typ]
        validate_package(payload, kind)
        kid, key = self.private[typ]
        data = f'{b64(packed(dict(alg="RS256",kid=kid,typ=typ)))}.{b64(packed(payload))}'
        token = data + '.' + b64(key.sign(data.encode(), padding.PKCS1v15(), hashes.SHA256()))
        if len(token) > 12288:
            raise ValueError('JWS exceeds 12 KiB')
        return token

    def verify(self, token, typ):
        return verify_jws(token, typ, self.trust, self.settings.profile)

def verify_jws(token, typ, trust, profile):
    if len(token) > 12288:
        raise ValueError('JWS too large')
    h, p, s = token.split('.')
    header = strict_json(unb64(h))
    VALIDATORS['header'].validate(header)
    entry = trust[header['kid']]
    if header['typ'] != typ or entry['type'] != typ or entry['profile'] != profile:
        raise ValueError('Wrong signing purpose/profile')
    public_key(entry['pem']).verify(unb64(s), (h+'.'+p).encode(), padding.PKCS1v15(), hashes.SHA256())
    raw = unb64(p)
    obj = strict_json(raw)
    validate_package(obj, {'MM02-MANIFEST':'content','MM02-LICENSE':'license','MM02-FIRMWARE':'firmware'}[typ])
    return obj, digest(raw)

def verify_license_binding(manifest, manifest_hash, license, device_id):
    if (license['device_id'], license['content_id'], license['content_version'], license['manifest_sha256']) != (device_id, manifest['content_id'], manifest['version'], manifest_hash):
        raise ValueError('License binding mismatch')
