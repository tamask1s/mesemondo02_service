# Ellenőrzési jegyzőkönyv

Dátum: 2026-09-22. Profil: elkülönített dev, közös TEST-ONLY fixture-kulcsok,
Python 3.12.14, PostgreSQL 16.15, FFmpeg 4.2.7. Függőségek: `requirements.lock`.

Végső teszteredmény: **27 passed**, 2 függőségi deprecációs figyelmeztetés, 63,51 s.
Az exportált OpenAPI az alkalmazás aktuális sémájával egyezik.

## Lefuttatva

- PostgreSQL-migráció és kétmesés tesztkatalógus létrehozása.
- Teljes MP3-dekódolás és frame-szintű 32 kHz / mono / CBR 64 kbit/s ellenőrzés.
- Közös challenge/aláírás/JWS fixture-ök, rossz aláírás, eltérő eszköz/hash,
  duplikált JSON, tiltott algoritmus és ismeretlen/külső kulcs elutasítása.
- Párhuzamos nonce: egy sikeres session; replay/lejárat/hibás kulcs elutasítva.
- Másik eszköz rendelése, entitlementje, delivery-je és jegye nem hozzáférhető.
- Párhuzamos rendelés és webhook; HMAC, összeg, kereskedő, eseményidempotencia.
- Böngészős teszt-checkout GET/POST, Origin-ellenőrzés, lejárt checkout.
- Friss session melletti idempotens ismétlés, új tartalomverzió új delivery-kulccsal.
- Teljes GET, kezdőoffsetes/suffix Range, Content-Length/Content-Range/hash,
  hibás Range, session/jegy külön lejárata, megkezdett stream befejezése lejárat után.
- Recovery-forgatás, elveszett válasz, lejárt és forgatással érvénytelenített replay.
- Tokenes és recovery-s csere, párhuzamos ismétlés, forrásvisszavonás,
  új cél-session melletti replay, injektált hibánál teljes tranzakció-visszagörgetés.
- Titokmentes hibaválasz/log, méret/rate limitek, átirányítás nélküli API.
- Admin licenckiállítás csak meglévő entitlementhez, 0600 kimeneti fájllal.
- Szintetikus, szabályos ESP32-S3 image Secure Boot v2 aláírásának ellenőrzése,
  firmware-import/letöltés, hibás és fixture-bináris elutasítása.
- **Valódi localhost TCP/HTTP + PostgreSQL**: eszközbizonyítás → checkout-oldal →
  HTTP-n hitelesített teszt-webhook → jogosultság → aláírt delivery → Range/hash →
  recovery → csere → idempotens replay és régi session visszavonása.
- Mentés/visszaállítás új PostgreSQL DB-be: 2 tartalomverzió és 4 fájl, minden hash/méret egyezik.
- Nginx snippet `nginx -t`: sikeres, elkülönített ideiglenes konfigurációval;
  nincs éles telepítés vagy reload.
- Synsigra `/`, `/syn_sig_ra/healthz`, `/syn_sig_ra/readyz`: mind HTTP 200.

A Starlette/httpx és anyio tesztadapter két deprecációs figyelmeztetést ad;
a valódi HTTP-integráció ettől külön, httpx + uvicorn hálózati úton fut.

## Hang-előkészítés

| Mese | Eredeti fájl | Fejezethang | Ideiglenes címhang |
|---|---:|---:|---:|
| A szállást kérő róka | 10 172 797 B | 3 390 912 B | 40 320 B |
| Az égig érő paszuly | 9 337 715 B | 3 112 704 B | 40 320 B |

A két fejezet együtt kb. 66,7%-kal kisebb. A címhang a megadott első 5 másodperc;
MP3-frame kerekítés miatt az ellenőrzött kódolt idő 5040 ms. A teljes mese megmarad
a fejezetben. A részletes dev riport `/var/lib/mesemondo-dev/audio-report.json`.
A hash-nevű fájlok `/var/lib/mesemondo-dev/runtime/content/` alatt vannak.

## Nem lefuttatott, külön elfogadást igénylő részek

- Valódi Flutter Windows app és fizikai ESP/USB/BLE együttműködés.
- Eszközön INSTALL_COMMIT, offline újratelepítés, hangszórós meghallgatás.
- Valódi kiadói firmware, készüléken OTA boot/önellenőrzés/rollback.
- Éles fizetési provider és valódi pénzmozgás.
- Production provisioning/kulcsok, publikus HTTPS Mesemondó-telepítés.

A szintetikus firmware-teszt nem készüléken futó firmware és nem bootbizonyíték.
Az API és a szoftveres teszt eredménye nem jelenti a tényleges app/eszköz konformanciáját.

A tesztekhez indított saját PostgreSQL leállítva az átadáskor; a DB és a konvertált
hangok megmaradnak. Éles Mesemondó backend vagy systemd unit nem indult el.

## 2026-09-23: optimalizálás és engedélyezett publikus dev telepítés

- **30 passed**, 2 változatlan függőségi deprecációs figyelmeztetés, 61,52 s.
  Takarékos PostgreSQL-beállításokkal; három új próba a memóriahatékony fájlolvasást
  és a csonka MP3-frame-ek elutasítását ellenőrzi.
- Új 002-es migráció, takarítási indexek; 1 backend worker, szál-/CPU-/RAM-korlátok.
- Valódi nyilvános HTTPS/nginx: új regisztrált dev emulátor → challenge/aláírás →
  session → katalógus → teszt-checkout jóváhagyása → mindkét entitlement →
  manifest/licenc-aláírás és kötés → 4 fájl teljes hash/mérete és Range: sikeres.
  A checkout szimulált, pénzmozgás nélkül. Az app-emulátoron mindkét mese elérhető.
- Saját API és DB systemd unitok futnak és bootkor indulnak; cleanup timer aktív.
  A külön fejlesztési DB-t ismét leállítottuk.
- Tényleges Flutter EXE és fizikai eszköz továbbra sincs kipróbálva.
- Átadás előtti végső ellenőrzés: Mesemondó healthz és readyz 200;
  Synsigra főoldal, healthz és readyz 200. Emulátor ZIP 6 fájl, 9417 bájt,
  0600 jogosultság; privát kulcs és futási adatok nem kerültek a repóba.
