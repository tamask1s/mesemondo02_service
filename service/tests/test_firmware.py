import contextlib
import dataclasses
import io
from uuid import uuid4
import pytest
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import rsa,padding
import espsecure
from esptool.bin_image import ESP32S3FirmwareImage,ImageSegment
from mesemondo.admin import import_firmware
from mesemondo.config import ROOT
from mesemondo.crypto import b64,packed,digest
from conftest import auth,headers


def test_verified_firmware_import_and_delivery(env,tmp_path):
    b,c,devices,_,_,_=env
    boot_key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    publisher=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    private=tmp_path/'boot-private.pem';public=tmp_path/'boot-public.pem'
    private.write_bytes(boot_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    public.write_bytes(boot_key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    b.settings=dataclasses.replace(b.settings,secure_boot_public_key=public)
    b.signer.trust['test-generated-firmware']={'pem':publisher.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode(),'profile':'dev','type':'MM02-FIRMWARE'}
    # Synthetic, structurally valid ESP image. This is NEVER a boot/OTA acceptance test.
    image=ESP32S3FirmwareImage()
    image.entrypoint=0x40370000
    image.chip_id=9
    descriptor=bytearray(256)
    descriptor[0:4]=(0xabcd5432).to_bytes(4,'little')
    descriptor[4:8]=(1).to_bytes(4,'little')
    descriptor[16:21]=b'1.0.0'
    image.segments=[ImageSegment(0x3c000020,bytes(descriptor))]
    unsigned=tmp_path/'unsigned.bin';signed=tmp_path/'signed.bin'
    unsigned.write_bytes(image.save(None))
    with private.open('rb') as key, unsigned.open('rb') as data, contextlib.redirect_stdout(io.StringIO()):
        espsecure.sign_data(version='2',keyfile=[key],output=str(signed),append_signatures=False,hsm=False,hsm_config=None,pub_key=None,signature=None,datafile=data)
    payload=dict(v=1,kind='firmware',hardware_id='mm02-s3n16r8-r1',version='1.0.0',secure_version=1,min_protocol=2,files=[dict(file_id=str(uuid4()),size_bytes=signed.stat().st_size,sha256=digest(signed.read_bytes()))])
    data=b64(packed(dict(alg='RS256',kid='test-generated-firmware',typ='MM02-FIRMWARE')))+'.'+b64(packed(payload))
    manifest=tmp_path/'manifest.jws'
    manifest.write_text(data+'.'+b64(publisher.sign(data.encode(),padding.PKCS1v15(),hashes.SHA256())))
    import_firmware(b,manifest,signed)
    token=auth(c,devices[0])
    r=c.get('/api/v1/firmware/latest?hardware_id=mm02-s3n16r8-r1',headers=headers(token))
    assert r.status_code==200,r.text
    assert 'license_jws' not in r.json()
    f=r.json()['files'][0]
    assert c.get(f['url'],headers=headers(token)).content==signed.read_bytes()
    assert c.get('/api/v1/firmware/latest?hardware_id=wrong',headers=headers(token)).status_code==403
    broken=tmp_path/'broken.bin';broken.write_bytes(signed.read_bytes()[:-1]+b'!')
    with pytest.raises(ValueError):import_firmware(b,manifest,broken)
    with pytest.raises(Exception):import_firmware(b,manifest,unsigned)


def test_fixture_binary_never_imported_as_firmware(env,tmp_path):
    import json
    b,c,devices,_,_,_=env
    fixture=json.loads((ROOT/'contracts/fixtures/security.json').read_text())
    manifest=tmp_path/'fixture.jws';manifest.write_text(fixture['firmware_jws'])
    with pytest.raises(Exception):import_firmware(b,manifest,ROOT/'contracts/fixtures/10000000-0000-4000-8000-000000000000.bin')
    token=auth(c,devices[0])
    assert c.get('/api/v1/firmware/latest?hardware_id=mm02-s3n16r8-r1',headers=headers(token)).status_code==404
