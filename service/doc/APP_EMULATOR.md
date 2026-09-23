# Appfejlesztői átadás – nyilvános dev tesztpéldány

A backend 2026-09-23 óta fut:

- `API_BASE`: `https://www.timeonion.com/mesemondo/api/v1/`
- `BACKEND_PROFILE`: `dev`
- Böngészős állapotellenőrzés: `https://www.timeonion.com/mesemondo/api/v1/readyz`
- Katalógus: `https://www.timeonion.com/mesemondo/api/v1/catalog`
- OpenAPI: `https://www.timeonion.com/mesemondo/api/v1/openapi.json`
- A prefix önmagában (`.../api/v1`) nem végpont: ott a 404 normális.

Az apphoz készített csomag a szerveren, **a repón kívül**:

`/var/lib/mesemondo-dev/app-emulator.zip`

Kibontott példány: `/var/lib/mesemondo-dev/app-emulator/`.
Ez a fájl NEM publikus webes letöltés; SSH/SFTP-vel vagy a munkaterület fájllinkjén
keresztül adható át a fejlesztőnek. Privát tesztkulcsot tartalmaz, ne tedd Gitbe.

Regisztrált emulátor: `34d4cd25-58f4-44c6-8ee5-020f79d9fc1e`, `dev` profil,
`mm02-dev` audience, `mm02-s3n16r8-r1` hardverazonosító.
A szerver csak a publikus kulcsot tárolja. A kulcs nem Synsigra-kulcs és nem éles
Mesemondó-eszközkulcs. Új igazi készüléknek új regisztráció kell.

## Az app fejlesztőjének

A normál HTTP-klienst használd a fenti valódi API-hoz. Csak az eszköz/USB réteget
emuláld: ne memóriabeli backend-adaptert használj, ne égesd be az ID-t a normál appba.
Az emulátor a mellékelt `device.json` és `device-private.pem` fájlokból induljon.
A normál app ezt HELLO-n át olvassa.

A csomag `config.local.json` fájlja a hárommezős fordításkori appkonfiguráció.
A `TRUSTED_KEYS` helyesen escape-elt JSON-string. Ez a csomagok JWS-aláírásának
ellenőrzésére szolgáló szerveroldali publikus kulcsokat tartalmazza; ezek nem azonosak
az emulátor eszközkulcsával. A fordításba kell bevinni, pl. a támogatott Flutter
belépési pontnál `--dart-define-from-file=config.local.json`; az EXE mellé másolás
nem elég. Az app forrása nincs ezen a szerveren, így az EXE újrafordítása az app
fejlesztőjének feladata.

Az emulált HELLO válasz mezői (lokális v2 borítékban):

```json
{"device_id":"34d4cd25-58f4-44c6-8ee5-020f79d9fc1e","hardware_id":"mm02-s3n16r8-r1","firmware_version":"0.0.1-dev","security_profile":"dev","protocol_versions":[2],"capabilities":[],"max_chunk_bytes":12288,"management_window_open":true}
```

`SESSION_OPEN`: új UUID a lokális sessionhez. `AUTH_SIGN` a kapott challenge-et
ellenőrizze (saját device_id, `audience=mm02-dev`), majd állítsa össze pontosan:

```text
MM02-AUTH-1\n
{audience}\n
{device_id}\n
{challenge_id}\n
{nonce}\n
{expires_at}\n
```

A fenti `\n` mindegyike egy LF bájt, az utolsó sor végén is. Nincs üres köztes sor,
CRLF, JSON-aláírás vagy extra whitespace. Az `expires_at` egész Unix-másodperc
decimális alakja. RSA-3072, PKCS#1 v1.5, SHA-256; 384 bájtos aláírásból padding
nélküli base64url lesz. AUTH_SIGN lokális `result`: `{"signature":"..."}`.
A HTTP sessionkérés külön JSON: `{challenge_id,signature}`.

A csomag `emulator_http_check.py` fájlja működő Python-példa az aláírásra és a valódi
HTTPS-hívásokra. `cryptography` és `httpx` szükséges hozzá. A szerveren a meglévő
külső venv-vel futtatható, új telepítés nélkül:

```bash
/opt/mesemondo-tools/venv/bin/python -B \
  /var/lib/mesemondo-dev/app-emulator/emulator_http_check.py \
  /var/lib/mesemondo-dev/app-emulator
```

Opcionális `--test-checkout`: kizárólag a belső tesztfizetési oldalon jóváhagyja a
két mesét, ellenőrzi a jogosultságokat, JWS-t, fájlhash-t és Range-letöltést.
Valódi pénzmozgás nincs. A kiadott emulátoron ezt már lefuttattuk, így mindkét
meséhez van tesztjogosultsága, és az appból rögtön próbálható a letöltés.
Új tesztrendelés ettől még létrehozható, a webhook nem hoz létre dupla jogot.

A `PUT_*`/`INSTALL_COMMIT` emulálás az appfejlesztő feladata, ha az app teljes USB
telepítési folyamatát is teszteli. Az emulátor állapotát és fogadott fájlokat tartósan
kezelje a közös lokális v2 szerződés szerint. Fizikai eszközön történő telepítést,
lejátszást vagy OTA-bootot ez a teszt nem igazol.
