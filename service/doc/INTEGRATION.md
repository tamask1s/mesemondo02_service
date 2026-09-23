# Integrációs szerződés és nyitott ellenőrzések

## Időablakok, újrapróbálás

- Challenge 120 s, egyszer használható; sikeres fogyasztás és session egy tranzakció.
- Session 300 s, csak hash tárolva; nincs refresh token. 401: app új eszközbizonyítást kér.
- Fájljegy 300 s, session és jegy **külön** ellenőrzött minden új GET/Range kérésnél.
  A már engedélyezett stream befejezhető lejárat után is. Az új Range lejárt sessionnel
  401, friss sessionnel de lejárt jeggyel 410 `NOT_AUTHORIZED`.
- Delivery: UUID Idempotency-Key, eszköz + tartalom + művelet alapján, sessionváltástól
  függetlenül. Ugyanazzal a kulccsal 300 s-ig pontosan ugyanaz a manifest/licenc/jegy.
  Lejárt visszajátszás 409 `NOT_AUTHORIZED`; friss letöltőjegyhez **új** delivery-kulcs.
  Új tartalomverziót új telepítési művelettel/új kulccsal kap a kliens. Korábbi kulcs
  nem változtat verziót a háttérben. Eltérő kérés ugyanazzal a kulccsal 409 `INVALID_ARGUMENT`.
- Rendelési idempotencia 90 nap, checkout 900 s. Lejárt rendelés `cancelled`;
  új vásárláshoz új kulcs. Régi kulccsal nem hosszabbítjuk meg a checkoutot.
- Recovery/csere titkosított válasz 300 s, tartósan csak a recovery titok hash-e.
  Az időablakot újrajátszás nem hosszabbítja meg. Takarító percenként törli a lejárt
  ciphertextet, az API a határidő pillanatától tiltja a visszajátszást.
  Az idempotencia-tombstone megmarad, hogy a lejárt kérés ne hajtódjon végre újra.
- Elveszett recovery-válasz: az ablakban ugyanaz a kulcs/kérés; utána friss eszköz-
  hitelesítés + explicit `rotate:true` + új idempotenciakulcs. Ha a cél eszköz is
  elérhetetlen és a titok sincs meg, admin ügyintézés kell.
- Sikeres csere elveszett válaszát a **cél** új sessionjével is lehet ismételni,
  ugyanazzal a kéréssel és kulccsal, a forrás már visszavont bizonyítékával.
  Az ablak után a célon recovery-forgatás a helyes eljárás, nem második eszközcsere.
- Új recovery-forgatás a korábbi recovery/csere titokválaszok visszajátszását is lezárja.
  Offline régi licencek távoli visszavonását nem ígérjük.

## Kliensoldali ellenőrzések

A meglévő Dart-kód nem része ennek a repónak, ezért a következők konkrét integrációs
teendők, nem készre jelentett appfunkciók:

1. Fogadja el az `API_BASE=https://www.timeonion.com/mesemondo/api/v1/` címet.
   Ha pontos gyökérbeli `/api/v1/` útvonalra szűkít, azt appoldalon módosítani kell;
   a Synsigra elé globális `/api/v1` route nem kerülhet.
2. Letöltésnél őrizze az Authorization fejlécet és az origin/prefix egyezését,
   ne kövessen redirectet. 206-nál ellenőrizze a kezdőoffsetet, végül a teljes hash-t.
3. Letöltés közbeni 401 után friss eszközbizonyítás; 410 vagy lejárt delivery-
   idempotencia 409 után új delivery-kulcs szükséges. Tartalomverzió-váltáskor
   új manifest fájljait ne fűzze a régi verzió részfájljaihoz.
4. A 409/410 megkülönböztetését és a felhasznált közös hibakódokat (`NOT_AUTHORIZED`,
   `INVALID_ARGUMENT`, `BUSY`, stb.) ellenőrizni kell. Új hibakód vagy rendelésállapot
   nem került be; a megjelenített szöveg nem kliensoldali állapotgép.
5. Lejárt checkout `cancelled`; új rendelési kulcs kell. A checkout visszatérése után
   hitelesített rendelés/jogosultság-lekérdezés igazolja a fizetést.
6. Recovery mentésének hibáját kezelje a fenti újrajátszás/forgatás szerint; a titok
   ne kerüljön app-, nginx-, hibakövető vagy provider-logba.
7. Az app és a firmware tényleges megbízható kulcsai egyezzenek. Az átadott dev
   konfiguráció a közös fixture-kulcsokat tartalmazza, nem éles bizalmi gyökeret.
8. Valódi app/USB: telepítés és commit, offline újratelepítés, megszakított feltöltés,
   későbbi tartalomverzió, OTA utáni boot/rollback visszaellenőrzése nyitott.

Helyi HTTPS-hez Windows által megbízható teszttanúsítvány kell. TLS-ellenőrzés
kikapcsolása nem része a megoldásnak. Valódi kiadói firmware és éles kulcsok nincsenek
megadva; a production példa ezt `MISSING-*` értékekkel jelzi és nem indul így el.
