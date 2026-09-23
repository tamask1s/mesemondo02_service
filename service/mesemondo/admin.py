import argparse
import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from uuid import UUID
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from .business import Backend, uid
from .config import Settings, ROOT
from .crypto import digest, public_key, reject_fixture_key
from .db import Database
from .media import normalize, probe, store_blob


def register(b, device_id, pem, profile, hardware_id='mm02-s3n16r8-r1'):
    if str(UUID(device_id))!=device_id or profile!=b.settings.profile:
        raise ValueError('Device ID/profile mismatch')
    key=public_key(pem)
    pem=key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    if profile=='production':
        reject_fixture_key(key)
    with b.db.transaction() as c:
        c.execute('INSERT INTO devices(id,public_key,security_profile,hardware_id,created_at) VALUES (%s,%s,%s,%s,%s)',(device_id,pem,profile,hardware_id,b.clock()))
        b.audit(c,'admin.register',device_id)


def import_content(b, content_id, version, title, description, price_minor, title_file, chapters):
    if str(UUID(content_id))!=content_id or not 0<=price_minor<=9007199254740991:
        raise ValueError('Invalid content ID or price')
    files=[]
    for index,path in enumerate([title_file,*chapters]):
        meta=probe(path)
        checksum=store_blob(path,b.settings.storage)
        if checksum!=meta['sha256']:
            raise ValueError('Input changed during import')
        files.append(dict(file_id=uid(),role='title' if index==0 else 'chapter',chapter_index=None if index==0 else index-1,**meta))
    manifest=dict(v=1,kind='content',content_id=content_id,version=version,title=title,language='hu',codec='mp3',sample_rate_hz=32000,bitrate_kbps=64,files=files)
    jws=b.signer.sign(manifest,'MM02-MANIFEST')
    _,payload_hash=b.signer.verify(jws,'MM02-MANIFEST')
    with b.db.transaction() as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('content:'+content_id,))
        existing=c.execute('SELECT max(version) AS version FROM content_versions WHERE content_id=%s',(content_id,)).fetchone()['version']
        if existing is not None and version<=existing:
            raise ValueError('Content versions are immutable and must increase')
        c.execute('INSERT INTO contents VALUES (%s,%s,%s,%s,\'HUF\') ON CONFLICT(id) DO UPDATE SET title=EXCLUDED.title,description=EXCLUDED.description,price_minor=EXCLUDED.price_minor',(content_id,title,description,price_minor))
        c.execute('INSERT INTO content_versions VALUES (%s,%s,%s,%s)',(content_id,version,jws,payload_hash))
        for f in files:
            c.execute('INSERT INTO files VALUES (%s,%s,%s,\'audio/mpeg\')',(f['file_id'],f['sha256'],f['size_bytes']))
            c.execute('INSERT INTO content_files VALUES (%s,%s,%s)',(content_id,version,f['file_id']))
        b.audit(c,'admin.content.import',object_id=content_id)
    return manifest


def issue_license(b, device_id, content_id, version, output):
    output=output.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError('Device-specific output must be outside the repository')
    with b.db.transaction() as c:
        dev=b.device(c,device_id)
        entitlement=c.execute('SELECT grant_id FROM entitlements WHERE device_id=%s AND content_id=%s',(device_id,content_id)).fetchone()
        row=c.execute('SELECT manifest_sha256 FROM content_versions WHERE content_id=%s AND version=%s',(content_id,version)).fetchone()
        if not entitlement or not row:
            raise ValueError('An existing entitlement and content version are required')
        token=b.signer.sign(dict(v=1,kind='license',device_id=str(dev['id']),content_id=content_id,content_version=version,manifest_sha256=row['manifest_sha256'],grant_id=str(entitlement['grant_id']),issued_at=b.clock()),'MM02-LICENSE')
        # Audit commit precedes output: a failed write never creates an unaudited license.
        b.audit(c,'admin.license.issue',device_id,content_id)
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write(token+'\n')


def seed(b):
    if b.settings.profile!='dev':
        raise ValueError('Test catalog forbidden in production')
    catalog=json.loads((ROOT/'service/seed/catalog.json').read_text())
    report=[]
    b.settings.storage.mkdir(parents=True,exist_ok=True)
    for item in catalog['items']:
        with b.db.transaction() as c:
            if c.execute('SELECT 1 FROM content_versions WHERE content_id=%s',(item['content_id'],)).fetchone():
                continue
        source=ROOT/'media'/item['source']
        with tempfile.TemporaryDirectory(prefix='prepare-',dir=b.settings.storage.parent) as temp:
            chapter,title=Path(temp)/'chapter.mp3',Path(temp)/'title.mp3'
            normalize(source,chapter)
            normalize(source,title,item['title_seconds'])
            manifest=import_content(b,item['content_id'],1,item['title'],item['description'],item['price_minor'],title,[chapter])
        report.append({'title':item['title'],'source_bytes':source.stat().st_size,'files':manifest['files']})
    return report


def import_firmware(b,manifest_path,image):
    token=manifest_path.read_text().strip()
    manifest,_=b.signer.verify(token,'MM02-FIRMWARE')
    if manifest['hardware_id']!='mm02-s3n16r8-r1':
        raise ValueError('Wrong hardware')
    f=manifest['files'][0]
    if image.stat().st_size!=f['size_bytes'] or digest(image.read_bytes())!=f['sha256']:
        raise ValueError('Firmware size/hash mismatch')
    if b.settings.secure_boot_public_key is None:
        raise ValueError('Trusted Secure Boot public key is required; a JWS alone is insufficient')
    # Espressif implementation validates the image's RSA-PSS Secure Boot v2 signature.
    import espsecure
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        with b.settings.secure_boot_public_key.open('rb') as keyfile, image.open('rb') as datafile:
            espsecure.verify_signature(version='2',hsm=False,hsm_config=None,keyfile=keyfile,datafile=datafile)
    from esptool.bin_image import LoadFirmwareImage
    parsed=LoadFirmwareImage('esp32s3',str(image))
    if parsed.checksum!=parsed.calculate_checksum() or not parsed.append_digest or parsed.stored_digest!=parsed.calc_digest:
        raise ValueError('Invalid ESP image checksum/digest')
    # ESP app descriptor is at 24-byte image header + 8-byte segment header.
    raw=image.read_bytes()
    if len(raw)<288 or raw[0]!=0xe9 or int.from_bytes(raw[12:14],'little')!=9 or int.from_bytes(raw[32:36],'little')!=0xabcd5432:
        raise ValueError('Not an ESP32-S3 application image')
    if int.from_bytes(raw[36:40],'little')!=manifest['secure_version'] or raw[48:80].split(b'\0')[0].decode()!=manifest['version']:
        raise ValueError('Image descriptor differs from manifest')
    store_blob(image,b.settings.storage)
    with b.db.transaction() as c:
        c.execute('SELECT pg_advisory_xact_lock(72002002)')
        previous=c.execute('SELECT secure_version FROM firmware_releases WHERE hardware_id=%s ORDER BY secure_version DESC LIMIT 1',(manifest['hardware_id'],)).fetchone()
        if previous and manifest['secure_version']<previous['secure_version']:
            raise ValueError('Secure version rollback forbidden')
        c.execute('INSERT INTO files VALUES (%s,%s,%s,\'application/octet-stream\')',(f['file_id'],f['sha256'],f['size_bytes']))
        release_id=uid()
        c.execute('INSERT INTO firmware_releases(id,hardware_id,version,secure_version,manifest_jws,file_id,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',(release_id,manifest['hardware_id'],manifest['version'],manifest['secure_version'],token,f['file_id'],b.clock()))
        b.audit(c,'admin.firmware.import',object_id=release_id)


def setup_dev(directory,database_url):
    directory=directory.resolve()
    if directory.is_relative_to(ROOT):
        raise ValueError('Dev runtime must be outside the repository')
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    config_path=directory/'config.json'
    if config_path.exists():
        raise ValueError('Config already exists; refusing to replace keys')
    secrets_dir=directory/'secrets'
    secrets_dir.mkdir(mode=0o700,exist_ok=True)
    trusted={}
    for purpose,typ in (('content','MM02-MANIFEST'),('license','MM02-LICENSE'),('firmware','MM02-FIRMWARE')):
        fixture=ROOT/'contracts/fixtures'/f'TEST-ONLY-{purpose}-public.pem'
        trusted['test-'+purpose+'-1']={'pem':fixture.read_text(),'profile':'dev','type':typ}
        if purpose!='firmware':
            private=secrets_dir/(purpose+'.pem')
            private.write_bytes((fixture.parent/f'TEST-ONLY-{purpose}-private.pem').read_bytes())
            private.chmod(0o600)
    (directory/'trusted-keys.json').write_text(json.dumps(trusted,indent=2))
    (secrets_dir/'replay.key').write_bytes(Fernet.generate_key())
    (secrets_dir/'webhook.key').write_bytes(os.urandom(32))
    for p in secrets_dir.iterdir():
        p.chmod(0o600)
    config={'profile':'dev','database_url':database_url,'storage':str(directory/'content'),'public_base':'https://www.timeonion.com/mesemondo/api/v1/','manifest_key':str(secrets_dir/'content.pem'),'license_key':str(secrets_dir/'license.pem'),'manifest_kid':'test-content-1','license_kid':'test-license-1','trusted_keys':str(directory/'trusted-keys.json'),'replay_key':str(secrets_dir/'replay.key'),'webhook_key':str(secrets_dir/'webhook.key'),'test_payments':True}
    config_path.write_text(json.dumps(config,indent=2))
    config_path.chmod(0o600)
    return config_path


def main():
    parser=argparse.ArgumentParser(description='Trusted server-side administration; no device provisioning or eFuse writes')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('setup-dev'); p.add_argument('--directory',type=Path,required=True); p.add_argument('--database-url',required=True)
    for name in ('migrate','cleanup','seed','export-openapi','export-app-config'):
        p=sub.add_parser(name)
        if name.startswith('export-'): p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('register');p.add_argument('--device-id',required=True);p.add_argument('--public-key',type=Path,required=True);p.add_argument('--profile',choices=['dev','production'],required=True)
    p=sub.add_parser('normalize');p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=float)
    p=sub.add_parser('import-content');p.add_argument('--content-id',required=True);p.add_argument('--version',type=int,required=True);p.add_argument('--title',required=True);p.add_argument('--description',required=True);p.add_argument('--price-minor',type=int,required=True);p.add_argument('--title-file',type=Path,required=True);p.add_argument('--chapter',type=Path,action='append',required=True)
    p=sub.add_parser('issue-license');p.add_argument('--device-id',required=True);p.add_argument('--content-id',required=True);p.add_argument('--version',type=int,required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('import-firmware');p.add_argument('--manifest',type=Path,required=True);p.add_argument('--image',type=Path,required=True)
    a=parser.parse_args()
    if a.command=='setup-dev':
        print(setup_dev(a.directory,a.database_url));return
    if a.command=='normalize':
        print(json.dumps(normalize(a.input,a.output,a.seconds)));return
    settings=Settings.load()
    if a.command=='migrate':
        Database(settings).migrate();return
    if a.command=='cleanup':
        Database(settings).cleanup();return
    b=Backend(settings)
    if a.command=='register':register(b,a.device_id,a.public_key.read_text(),a.profile)
    elif a.command=='seed':print(json.dumps(seed(b),ensure_ascii=False,indent=2))
    elif a.command=='issue-license':issue_license(b,a.device_id,a.content_id,a.version,a.output)
    elif a.command=='import-content':import_content(b,a.content_id,a.version,a.title,a.description,a.price_minor,a.title_file,a.chapter)
    elif a.command=='import-firmware':import_firmware(b,a.manifest,a.image)
    elif a.command=='export-openapi':
        from .api import create_app
        a.output.write_text(json.dumps(create_app(settings,b).openapi(),ensure_ascii=False,indent=2)+'\n')
    elif a.command=='export-app-config':
        a.output.write_text(json.dumps({'API_BASE':settings.public_base,'BACKEND_PROFILE':settings.profile,'TRUSTED_KEYS':json.dumps(b.signer.trust,separators=(',',':'))},ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':
    main()
