# Üzemeltetés és helyreállítás

## Könyvtárak és jogosultságok

A repó forrás és szerződések tárolója. Saját runtime példa:

| Cél | Éles példa | Fejlesztés ezen a gépen |
|---|---|---|
| kód | `/opt/mesemondo/releases/<release>` | ez a repó |
| interpreter/venv | `/opt/mesemondo/venv` | `/opt/mesemondo-tools/venv` |
| DB | saját PostgreSQL DB és role | `/var/lib/mesemondo-dev/postgres` |
| tartalom | `/var/lib/mesemondo/content` | `/var/lib/mesemondo-dev/runtime/content` |
| config/titkok | `/etc/mesemondo` | `/var/lib/mesemondo-dev/runtime` |
| teszt/átmeneti fájlok | külső eldobható könyvtár | `/var/lib/mesemondo-dev/pytest` |

A service saját `mesemondo` userrel fusson. Privát kulcsok/config 0600, könyvtárak
0700 vagy célzott 0750. A webfolyamatnak a tartalomhoz csak olvasási jog kell;
az import megbízható admin művelet. Külön adatbázis és role, csak Unix socket/loopback,
se DB, se backend ne legyen publikus. Dev és production külön adatbázist, storage-t,
kulcsokat és konfigurációt használjon; a DB profilőr is tiltja a keverést.

A PostgreSQL-fejlesztői eszköz fordított 16.15-ös kiadás, SHA-256 ellenőrzött
hivatalos forrásból, repón kívül. Nem hoztunk létre automatikusan induló systemd
DB-service-t. A forrás/build a `/opt/mesemondo-tools/build` alatt van. A közös
`.tools/` könyvtár már a munka előtt létezett, nem módosítottuk/töröltük.

## Telepített dev tesztpéldány (2026-09-23)

A felhasználó külön kérésére telepítve: `/opt/mesemondo/current`,
`/etc/mesemondo/config.json`, `/var/lib/mesemondo/content`, saját `mesemondo` user,
saját `mesemondo-db` DB-user. Külön `mesemondo-postgresql.service` kezeli a
`/var/lib/mesemondo/postgres` adatbázist; csak a `/run/mesemondo-postgresql` Unix
socketen érhető el, nincs TCP listener. A `mesemondo.service` egy processzel fut a
127.0.0.1:8092 címen. A cleanup timer aktív. Mindhárom saját unit bootkor indul.
A venv a repón kívüli telepített tools-venv-re mutat; az alkalmazás és a DB unitjai
külön CPU-/memóriakorlátot kapnak. Részletek: [erőforrások](RESOURCE_REVIEW.md).

A `mesemondo.conf` snippet a közös lock alatt lett telepítve és nginx-teszttel
ellenőrizve; a többi konfiguráció változatlan. A snapshot és az ellenőrzőösszegek:
`/var/lib/mesemondo/proxy-backup-20260923/`. A normál `systemctl reload nginx`
aszinkron: az ellenőrző szkript rövid ideig újrapróbálja a readiness kérést.
A profil **dev**, nincs éles provider. Az emulátor privát kulcsa nem kerül a
szerverkonfigurációba vagy a webes tárhelyre.

## Éles telepítés – külön engedély után

Az `ops/mesemondo.service`, a cleanup unit/timer és az nginx snippet **minták**;
ezek takarékos változatai a fenti dev példányban telepítve vannak. Production indulás előtt saját
kulcsok, firmware trust-egyeztetés, DB-role, backup és fizetési provider szükséges.
Provider nélkül a nem fizetési funkciók működhetnek; `/orders` 503-at ad.

1. Hozd létre a saját usert, könyvtárakat, DB-t, role-t és a production configot.
   Külön venv-be telepíts a hash-rögzített lockból. Ne írj a rendszer-Pythonba,
   `/opt/signal_synth*`, `/var/lib/syn_sig_ra`, Apache vagy Synsigra fájljaiba.
2. A release tartalmazza a `service/`, `contracts/` könyvtárakat és a dokumentumokat.
   Éles runtime-ba a fixture privát kulcsok helyett csak a szükséges közös sémák
   kerüljenek; a production kulcsellenőrzés test-kid-ket/profilkeverést elutasít.
3. `admin migrate`; saját backend induljon `127.0.0.1:8092`-n, előtte `ss -ltn`
   alapján ellenőrizd, hogy szabad. A példa proxy és systemd portja egyezzen.
4. Belső readiness, majd az alábbi lock alatt kizárólag a `mesemondo.conf` telepítése.
5. Ellenőrizd a külső API-t és a Synsigra végpontjait:
   `/`, `/syn_sig_ra/healthz`, `/syn_sig_ra/readyz`.
   A Mesemondó API `/mesemondo/api/v1/healthz` és `/readyz`.
6. Engedélyezd a Mesemondó saját cleanup timerét; a tokenek lejáratát az API akkor
   is érvényesíti, ha a takarító még nem futott.

Proxyváltoztatáskor a meglévő közös lockot kell használni. Root admin-shellben,
a saját snippet mentése **előtt**:

```bash
exec 9>/etc/nginx/timeonion-services/.deploy.lock
flock -x 9
```

Ezután mentsd kizárólag a meglévő `mesemondo.conf`-ot a nginx include-globján kívülre,
jegyezd fel azt is, ha még nem létezett, és telepítsd a kész új snippetet.
Futtass `nginx -t`, majd siker esetén `systemctl reload nginx.service`-t.
Hiba esetén a lock megtartása mellett csak a saját snippetet állítsd vissza
(vagy első telepítésnél távolítsd el); újabb `nginx -t` és graceful reload után
engedhető el a lock. A lock fájlt soha ne töröld/cseréld. A közös vhostot,
`timeonion-services` könyvtárat és `synsigra.conf`-ot nem szabad felülírni.

Változatlan proxy melletti kódfrissítésnél csak `mesemondo.service` induljon újra;
nginx reload és Synsigra deploy nem kell. Rollback a saját előző release-re mutasson;
DB-migrációnál előzetes kompatibilitásvizsgálat vagy saját backup-visszaállítás kell.
Automatikus destruktív down-migráció nincs.

## Titokmentes naplózás

Uvicorn access log tiltva. Az alkalmazás hibánál csak request_id-t és kivételtípust
naplóz; nincs traceback, body, Authorization, checkout URL vagy letöltőjegy.
Az nginx Mesemondó locationjeiben access log tiltva, error log eldobva, mert az
nginx hibasorok is tartalmazhatnak teljes URL-t. A DB-ben csak session/ticket/recovery
hash-ek, valamint rövid idejű titkosított replay van. A globális PostgreSQL statement-
naplózást ne engedélyezd ehhez a role-hoz; SQL-paraméterek ne menjenek hibakövetőbe.
A provider-integráció ugyanezt a naplózási szabályt tartsa be.

## Mentés és visszaállítás

Mentéshez egyező kiadású `pg_dump`/`pg_restore` használható. A mentési cél a repón
kívüli, hozzáférés-védett és titkosított tároló legyen. A titkok/config ugyanúgy
szükségesek a visszaállításhoz, mint a DB és a hash-nevű tartalomfájlok.

Konzisztens egyszerű MVP-mentés: állítsd le **csak** a Mesemondó backendet és a saját
cleanup timert; az admin importokat szüneteltesd. Példa saját DB Unix socketes
hitelesítésével, jogosult admin userként:

```bash
umask 077
pg_dump -Fc -Z0 -d mesemondo -f /EXTERNAL/backup/database.dump
tar -C /var/lib/mesemondo -cpf /EXTERNAL/backup/content.tar content
tar -C /etc -cpf /EXTERNAL/backup/config-and-secrets.tar mesemondo
# A release azonosítóját, a migrációkat és a requirements.lock-ot is mentsd.
```

A `-Z0` a fejlesztői, zlib nélkül fordított PostgreSQL-lel is működik. A fájlokat
még a szolgáltatás újraindítása előtt másold a védett mentési célra. Ne csak a
repo Git-mentésére hagyatkozz: a futási adatok szándékosan nem Git-fájlok.

Visszaállítás először új, saját DB-be és külön tárhelyre:

```bash
createdb -O mesemondo mesemondo_restore
pg_restore --exit-on-error --single-transaction --no-owner \
  -d mesemondo_restore /EXTERNAL/backup/database.dump
# A content és config archívumot új, külön célkönyvtárba bontsd ki;
# az eredeti DB/tárhely addig maradjon meg.
```

Ellenőrizd a `files.sha256`/méret mezőket a visszaállított fájlokkal, a kulcsok
és profil egyezését, majd readiness és teljes hitelesítés/delivery/Range próba.
Ezután saját service-configgal válts az új DB/tárhelyre. A régi és új Mesemondó
példány egyszerre ne írja ugyanazt a DB-t. A Synsigra DB-jét és unitjait sem a mentés,
sem a helyreállítás nem érinti. Elveszett signing key vagy replay key esetén nincs
biztonságos automatikus helyettesítés; előbbi firmware trust-migrációt is igényelhet.

## Felhasznált műszaki források

- [FastAPI: proxy és root_path](https://fastapi.tiangolo.com/advanced/behind-a-proxy/)
- [PostgreSQL hivatalos forráskiadások](https://www.postgresql.org/ftp/source/)
- [Espressif espsecure / Secure Boot aláírásellenőrzés](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/espsecure/index.html)
