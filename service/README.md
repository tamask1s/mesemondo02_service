# Mesemondó service

FastAPI + PostgreSQL backend a közös `PROTOCOL.md` szerződéshez. A kód `service/`,
a futtatókörnyezet, adatbázis, konvertált hangok és titkok **a repón kívül** vannak.
2026-09-23-tól a felhasználó kérésére **nyilvános dev tesztpéldány fut** saját
systemd unitokkal és nginx-részlettel. Éles fizetés nincs; a Synsigra konfigurációja
változatlan. [Appemulátor-csomag és bekötés](doc/APP_EMULATOR.md).

Gyors ellenőrzés böngészőből:
<https://www.timeonion.com/mesemondo/api/v1/readyz> → `{"status":"ready"}`.
A repó gyökeréből: `bash service/scripts/status.sh`.
A `/mesemondo/api/v1` önmagában nem létező végpont.
A telepített service: `systemctl status mesemondo.service mesemondo-postgresql.service`.
A fejlesztési adatbázis leállítva marad, amíg külön teszt nem igényli.

## Indítás a most előkészített fejlesztési környezetben

A telepített eszközök: `/usr/bin/ffmpeg`, `/usr/bin/ffprobe`,
`/opt/mesemondo-tools/venv` (Python 3.12),
`/opt/mesemondo-tools/postgresql-16` (PostgreSQL 16.15).
A rendszer `/usr/bin/python3` és a Synsigra környezete változatlan.
A Python-csomagok pontos verziója és hash-e a `requirements.lock` fájlban van.

A repó gyökeréből:

```bash
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=service
export MM02_CONFIG=/var/lib/mesemondo-dev/runtime/config.json
/opt/mesemondo-tools/postgresql-16/bin/pg_ctl \
  -D /var/lib/mesemondo-dev/postgres -l /var/lib/mesemondo-dev/postgres.log \
  -o "-k /var/lib/mesemondo-dev/socket -h '' -p 55432" start
/opt/mesemondo-tools/venv/bin/python -m mesemondo.admin migrate
/opt/mesemondo-tools/venv/bin/uvicorn mesemondo.api:create_app --factory \
  --host 127.0.0.1 --port 8092 --no-access-log --no-proxy-headers
```

A PostgreSQL-indítást csak leállított adatbázisnál futtasd. A teszt-DB kizárólag
0700 jogosultságú könyvtárban levő Unix socketet használ, nincs TCP-listener.
A backend fenti parancsa belső HTTP; a Windows apphoz külön, megbízható HTTPS
proxy kell. A nyilvános tesztpéldányt külön systemd unit szolgálja ki; ha az már fut,
ne indíts rá kézi backendet a 8092-es porton. Helyi teszthez válassz másik szabad portot.
Leállítás: a backendnél Ctrl-C, a DB-nél `pg_ctl -D ... -m fast stop`.

Új környezetnél rendszerszintű FFmpeg és PostgreSQL 16+ szükséges; a csomagokat
külön, repón kívüli venv-be telepítsd:

```bash
uv pip sync --link-mode copy --python /opt/mesemondo-tools/venv/bin/python service/requirements.lock
# Saját, üres DB, külső 0700 runtime könyvtár; kizárólag dev tesztkulcsok:
python -m mesemondo.admin setup-dev --directory /EXTERNAL/runtime \
  --database-url 'postgresql:///mesemondo_dev?host=/EXTERNAL/socket&port=55432'
# Állítsd az MM02_CONFIG-ot az így kapott külső config.json-ra.
python -m mesemondo.admin migrate
python -m mesemondo.admin seed
```

A `python` rövidítést a további példákban a külön venv Pythonjára kell cserélni.
A `setup-dev` nem ír felül meglévő kulcsot/konfigurációt; production használata
nem engedélyezett. A migrációk tranzakciósak, alkalmazott fájl hash-e rögzített;
a korábbi migrációt nem szabad utólag szerkeszteni.

## Katalógus és admin

A két induló mese: **A szállást kérő róka** és **Az égig érő paszuly**.
Mesénként egy teljes fejezet, külön ideiglenes címhang a felvétel első 5 másodpercéből.
Az eredeti `media/*.mp3` változatlan maradt. A seed csak dev profilban fut;
a 100 Ft-os ár **tesztár**, nincs valódi terhelés vagy kiosztott induló jogosultság.
A konvertált fájlok a külső konfiguráció `storage` könyvtárában, SHA-256 néven vannak.
A `seed` újraindítható, már kiadott tartalmat nem ír felül.

Formátum: mono MP3, 32 kHz, CBR 64 kbit/s, kétmenetes −23 LUFS/−2 dBTP
normalizálás. Minden frame paraméterét, a teljes dekódolhatóságot, méretet és hash-t
ellenőrizzük. Ez a szerződés szerinti formátumot igazolja; fizikai lejátszási próba
még nincs. A firmware hardveres hangerőkorlátját nem helyettesíti.

```bash
python -m mesemondo.admin register --device-id DEVICE_UUID \
  --public-key /EXTERNAL/device-public.pem --profile dev
python -m mesemondo.admin normalize --input /EXTERNAL/new-title.wav \
  --output /EXTERNAL/title-v2.mp3
python -m mesemondo.admin import-content --content-id CONTENT_UUID --version 2 \
  --title 'A szállást kérő róka' --description 'Javított címhang' --price-minor 10000 \
  --title-file /EXTERNAL/title-v2.mp3 --chapter /EXTERNAL/chapter.mp3
python -m mesemondo.admin import-firmware --manifest /EXTERNAL/release.jws \
  --image /EXTERNAL/signed-app.bin
python -m mesemondo.admin issue-license --device-id DEVICE_UUID \
  --content-id CONTENT_UUID --version 1 --output /EXTERNAL/license.jws
python -m mesemondo.admin cleanup
```

Az `issue-license` csak meglévő eszközjogosultsághoz ad licencet, nem oszt új jogot;
a kimenet repón kívüli, 0600 fájl. A `--chapter` ismételhető. A regisztráció kizárólag új, admin által ellenőrzött
eszközkulcsot fogad, felülírást nem végez; nincs eFuse-művelet. A normalizálás nem
ír felül fájlt. A tartalom új verziója új manifestet/fájlazonosítókat kap; a korábbi
verzió és az arra kiadott delivery változatlan. Az online service-nek nincs
firmware-aláíró privát kulcsa. Firmware-importhoz a megbízható JWS-kulcs mellett
külön konfigurált Secure Boot v2 public key és érvényes ESP32-S3 image kell.
A közös `.bin` fixture nem kiadható firmware.

## API, app és fizetés

Az exportált [OpenAPI](openapi.json) a részletes HTTP-séma; belső prefix `/api/v1`,
külső prefix `/mesemondo/api/v1`. Nincs API-átirányítás vagy `data` burkoló.
A [config.local.json](config.local.json) hárommezős, fordításkori **dev**
appkonfiguráció, kizárólag a közös publikus tesztkulcsokkal. A valós firmware
trusted-key készletét és a prefix elfogadását közös integrációban kell ellenőrizni.
Az EXE mellé másolás nem érvényesíti a buildkonfigurációt.

```bash
python -m mesemondo.admin export-openapi --output service/openapi.json
python -m mesemondo.admin export-app-config --output /EXTERNAL/config.local.json
```

A tesztadapterhez külön `test_payments=true` kell dev profilban. A checkout oldal
POST-os jóváhagyása hitelesített teszteseményt juttat a webhook-feldolgozóba.
Külső adapter HTTP-n a `POST /payments/webhooks/test` végpontot hívhatja:
`X-MM02-Timestamp` Unix-másodperc, `X-MM02-Signature` = hex HMAC-SHA256 a
`timestamp + '.' + eredeti_body` bájtokon. Az ablak ±300 s; a kulcs a külső
`webhook_key` fájl nyers bájtja. Eseményséma az OpenAPI-ban.
A checkout 15 perces, a böngésző Origin-jének a konfigurált HTTPS originnek kell
megfelelnie. A visszatérési URL és a GET nem ad jogosultságot.
Éles fizetési provider nincs beállítva: production checkout 503, tesztfizetés tiltva.

## Tesztelés

```bash
export MM02_TEST_TMP=/var/lib/mesemondo-dev/pytest
bash service/scripts/test.sh
```

A teszt saját ideiglenes PostgreSQL-adatbázist hoz létre és töröl; ezért a dev
DB-felhasználónak CREATEDB jog kell. Production DB-n ne futtasd. A teszteszköz-
aláíró kizárólag a tesztekben él. A `tests/test_http.py` valódi localhost TCP/HTTP
és PostgreSQL együttműködését teszteli, nem memóriabeli HTTP-adaptert.
A tesztkönyvtárba csak eldobható fájlok kerüljenek: pytest induláskor takarítja.

Részletes korlátok: [integráció](doc/INTEGRATION.md),
[telepítés és mentés](doc/OPERATIONS.md), [ellenőrzési eredmények](doc/VALIDATION.md).

Erőforrások: [1 GB-os VPS mérései és beállításai](doc/RESOURCE_REVIEW.md).
