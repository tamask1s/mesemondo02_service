# Közös szerződés — lokális protokoll v2 / HTTP API v1

Ez az interfészek egyetlen normatív leírása; a termékviselkedés a [SYSTEM.md](SYSTEM.md)-ben van. Implementáció előtt ebből készüljenek közös gépi sémák és fixture-ök a `contracts/` alatt, nem három külön protokoll. Inkompatibilis változtatás új főverzió, nem csendes átértelmezés.

## 1. Lokális szállítás

USB: self-powered CDC-ACM, nem MSC és nem PC-s töltőport. VBUS-figyelés GPIO9-en a HARDWARE szerint; az USB-deszkriptor self-powered jelölése és VBUS-áramigénye a tényleges, csak érzékelésre használt adatportnak feleljen meg, ne töltési profilnak. Egy alkalmazási adatcsatorna; debug-log nem keverhető rá. Soros baud rate CDC-n nem határozza meg az USB sebességét. Felderítés a HELLO-val, nem kizárólag COM-szám/VID/PID alapján; éles VID/PID használati jog külön kiadási feltétel.

BLE: szolgáltatás `4d4d0200-7300-4e00-8a00-6d6573650001`; RX `4d4d0200-7300-4e00-8a00-6d6573650002` (write-with-response), TX `4d4d0200-7300-4e00-8a00-6d6573650003` (indicate). Egy karakterisztikaírás/jelzés legfeljebb az egyeztetett ATT MTU−3 bájt; a lenti stream-keret töredezhet, a fogadó újra összeállítja. Egy kapcsolat és egy kérés folyamatban, visszanyomás; kapcsolatbontáskor fél keret eldobandó.

Mindkét úton: **egy UTF-8 JSON-objektum + LF (`0A`) üzenetenként**, bináris hosszprefix nélkül, [NDJSON](https://github.com/ndjson/ndjson-spec) keretezéssel. Küldés egyetlen sorban; fogadás LF és CRLF lezárással is. A JSON hossza 1…32768 **bájt**, a lezárás nélkül; a korlátot már pufferelés közben érvényesíteni kell. Nincs BOM, lezáró nulla vagy dupla JSON-stringbe csomagolás. Szövegen belüli sortörés escape-elve (`\n`, `\r`) szerepel, valódi CR/LF nem lehet a JSON-ban; nincs többsoros pretty-print az átvitelen. Ne feltételezzünk egy üzenetet egyetlen USB-readben/BLE-írásban: bájtokat gyűjtünk LF-ig, a magyar UTF-8 karakter is töredezhet. A korábbi bináris keretezés nem támogatott, nincs automatikus protokollkeverés.

Üres sor, túlméret, hibás UTF-8/JSON, duplikált JSON-kulcs vagy 10 s-ig inaktív fél üzenet: kapcsolatbontás és a puffer eldobása. JSON a [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259) szerint: idézőjeles kulcsok, nincs komment, záró vessző, NaN/Infinity vagy párosítatlan Unicode surrogate. UUID kisbetűs kötőjeles; SHA-256 kisbetűs 64 hex; bináris mezők base64url, padding nélkül. Egész szám 0…2^53−1; fájl legfeljebb 2 GiB, negatív/túlcsorduló offset tiltott.

Kérés (a `params` név–érték párokat tartalmazó objektum, nem tömb; paraméter nélkül `{}`):

```json
{"v":2,"id":1,"command":"LIBRARY_LIST","params":{"cursor":null,"limit":50}}
```

Sikeres válasz, ugyanazzal az `id` és `command` értékkel:

```json
{"v":2,"id":1,"command":"LIBRARY_LIST","ok":true,"result":{"items":[{"content_id":"c8b28724-1c67-4a88-a122-f4ba751d75e9","version":1,"title":"A kiskakas gyémánt félkrajcárja","position_ms":0,"completed":false}],"next_cursor":null}}
```

Ugyanerre a kérésre sikertelen esetben például:

```json
{"v":2,"id":1,"command":"LIBRARY_LIST","ok":false,"error":{"code":"NO_SD","message":"Nincs behelyezett SD-kártya."}}
```

Fix borítékmezők: kérésben `v`, `id`, `command`, `params`; válaszban `v`, `id`, `command`, `ok` és pontosan az egyik: `result` vagy `error`. `ok=true` mellett `result` objektum (adat nélküli siker `{}`), `ok=false` mellett `error` objektum kötelező. A parancs nem dinamikus JSON-kulcs: így minden parancs siker-/hibaválasza ugyanazzal a kóddal és sémával kezelhető. `command` formátuma `[A-Z][A-Z0-9_]{0,47}`, ismeretlen parancs `UNSUPPORTED_COMMAND`. Hibás paraméter/többletmező `INVALID_ARGUMENT`; sérült boríték, amelyből érvényes `v`/`id`/`command` sem olvasható, kapcsolatbontás. Nem támogatott, egész `v` esetén a v2 borítékot értő fél `UNSUPPORTED_VERSION` hibát ad `v:2`-vel és visszaadott `id`/`command` mezőkkel; régi bináris üzenethez ez nem ígéret.

Az `id` pozitív egész, kapcsolaton belül növekvő; **USB-n és BLE-n is egy kérés van folyamatban**, egy kéréshez egy válasz. A fogadó a választ `id` **és** `command` szerint párosítja; eltéréskor nem használja fel és bont. Ismételt kérés új `id`-t kap: az idempotenciát a művelet/átvitel azonosítói adják, nem ez a sorszám. A válasz határideje a teljes kérés elküldésétől indul: alapból 10 s, hash/commit/OTA ellenőrzésnél 120 s; timeout után kapcsolatbontás, így késői válasz nem kerülhet új kéréshez. Hosszabb ellenőrzésre a handler rövid `BUSY` választ adhat, és ugyanazon idempotens művelet ismétlése a futó ellenőrzés eredményét adja, nem indít másikat. Állapotlekérdezés polling; nincs külön eseményformátum. Lapozott válasz a kért limitnél kevesebb elemet is adhat, hogy a teljes JSON 32768 bájton belül maradjon.

| command | params | result / hatás |
|---|---|---|
| HELLO | üres | `device_id`, `hardware_id="mm02-s3n16r8-r1"`, `firmware_version`, `security_profile` (`dev`/`production`), `protocol_versions:[2]`, `capabilities`, `max_chunk_bytes=12288`, `management_window_open` |
| SESSION_OPEN | üres | `session_id` UUID; csak fizikai ablakban, az adott kapcsolathoz kötve |
| STATUS | üres | mód, content_id/chapter_index/position_ms vagy null, `supply_mv`, `usb_present` (ESP adat-USB VBUS jelenléte, nem BQ-töltés), `sd_free_bytes`, `transfer_state`; nem állít pontos SOC-t/töltőáramot |
| AUTH_SIGN | §2 challenge mezői | `signature` base64url; csak nyitott helyi sessionben |
| LIBRARY_LIST | `cursor` null/string, `limit` 1…50 | `items:[{content_id,version,title,position_ms,completed}]`, `next_cursor` vagy null |
| INSTALL_BEGIN | `manifest_jws`, `license_jws` | ellenőrzés/helyfoglalás után `install_id` UUID; azonos csomag folytatható |
| PUT_BEGIN | `install_id`, `file_id` | `transfer_id`, `next_offset`, `prefix_sha256`; a fájl mérete/hash-e a manifestből jön |
| PUT_CHUNK | `transfer_id`, `offset`, `data` | legfeljebb 12288 dekódolt bájt; `next_offset` a ténylegesen elfogadott következő pozíció |
| PUT_STATUS | `transfer_id` | a tartósan visszaállítható `next_offset`, `prefix_sha256` |
| PUT_END | `transfer_id` | méret és teljes SHA-256 egyezés, `verified:true` |
| INSTALL_COMMIT | `install_id` | csak minden fájl/manifest/licenc ellenőrzése után könyvtáraktiválás; könyvjelző megtartásának migrációja verzióváltáskor |
| INSTALL_ABORT | `install_id` | csak staging törlése; aktív verzióhoz nem nyúl |
| CONTENT_DELETE | `content_id` | aktív lejátszás leállítása, helyi példány törlése; backendjog nem változik |
| SETTINGS_GET | üres | `volume_cap_percent` 0…100, `led_brightness_percent` 0…100 |
| SETTINGS_SET | az előző két mező közül legalább egy | értékellenőrzés és tartós mentés; a 100% a bemért biztonságos plafon, nem erősítő-full-scale |
| UPDATE_BEGIN | `manifest_jws` (§3 firmware) | `install_id`; további adatküldés ugyanazon PUT műveletekkel |
| UPDATE_COMMIT | `install_id` | aláírás/cél/verzió ellenőrzés és inaktív slot véglegesítése; ACK után újraindítás |

HELLO/STATUS olvasható helyi engedély nélkül; minden más művelet SESSION_OPEN után, kivéve maga SESSION_OPEN. A session szerveres hitelesítéstől független helyi engedély; az engedélyezett fizikai csatlakozás nem helyettesít tartalomlicencet. BLE-n ezen felül titkosított bondolt kapcsolat kell; dev profil sem kerülheti meg észrevétlenül az éles licencellenőrzést.

Megszakítás után új helyi session, majd ugyanazon manifesttel INSTALL_BEGIN/UPDATE_BEGIN és PUT_BEGIN/STATUS. A kliens összeveti a helyi fájl prefix-hashét a válasszal; eltéréskor staging újrakezdés. Folyamatos kapcsolatban ACK fogadott adatot jelölhet, újracsatlakozáskor a tartós offset kisebb is lehet. Korábbi, teljesen eltárolt chunk ismétlése azonos bájtokkal idempotens; eltérő adat/rés/átfedő tartomány `OFFSET_MISMATCH`. Törlés, BEGIN és COMMIT ismétlése ne hozzon létre duplikációt. Általános timeout után nem ismétlünk vakon nem idempotens műveletet.

Hibakódok: `UNSUPPORTED_VERSION`, `UNSUPPORTED_COMMAND`, `INVALID_ARGUMENT`, `NOT_AUTHORIZED`, `BUSY`, `NO_SD`, `NO_SPACE`, `NOT_FOUND`, `OFFSET_MISMATCH`, `HASH_MISMATCH`, `INVALID_SIGNATURE`, `WRONG_DEVICE`, `WRONG_HARDWARE`, `LOW_POWER`, `IO_ERROR`, `INTERNAL`. A megjelenített üzenet nem tartalmaz titkot vagy szerver-stacktrace-t. A kódok, nem a lokalizált szövegek vezérlik az appot.

## 2. Backendhitelesítés — pontos aláírandó bájtok

Challenge: `device_id`, `challenge_id` UUID, `nonce` 32 véletlen bájt base64url alakban, `expires_at` UTC Unix másodperc, `audience`=`mm02-dev` vagy `mm02-prod`. TTL 120 s. A készülék saját ID-jával és a buildhez rögzített audience-szel ellenőriz, az alábbi UTF-8/ASCII szöveget **maga** állítja össze, LF (`0A`) sorvégekkel, a végén is egy LF-fel:

```text
MM02-AUTH-1
{audience}
{device_id}
{challenge_id}
{nonce}
{expires_at}
```

Csak e célra és e sémából készít aláírást; nem adunk általános „sign arbitrary bytes” API-t. Algoritmus RSA-3072 PKCS#1 v1.5 + SHA-256; aláírás 384 bájt, hálózati/big-endian formában. Az ESP DS periféria natív operandusformátumát a gyártói PSA/Mbed TLS illesztés kezeli, saját paddinget tilos írni. Backend a tárolt challenge pontos mezőivel, megbízható órával ellenőriz; lejárt/eltérő/egyszer már felhasznált challenge nem érvényes. Sikeres fogyasztás + sessionkiadás atomikus. Eszköznek nem kell ehhez pontos órával rendelkeznie.

Session: 32 véletlen bájtos opaque bearer token, backendben csak hash, 5 perc TTL, device_id és megengedett célok hozzárendelve; nincs örök refresh token. Dev és production külön kulcs-/adatkészlet, éles service dev identitást elutasít. Publikus kulcs: PEM SubjectPublicKeyInfo, e=65537. Ismeretlen device_id-val nincs önregisztráció.

## 3. Aláírt csomagok

JWS Compact Serialization, rögzített `alg=RS256`, ismert `kid`, `typ=MM02-MANIFEST` / `MM02-LICENSE` / `MM02-FIRMWARE`. `none`, algoritmusváltás, külső `jku`/`x5u` és ismeretlen kulcs tiltott. A verifikáló a kapott JWS eredeti signing inputját ellenőrzi, nem újraszerializált JSON-t; ezután szigorú sémaellenőrzés. JSON duplikált kulcs tiltott. `manifest_sha256` mindig a JWS dekódolt payloadjának **eredeti UTF-8 bájtjaira** vonatkozik. JWS legfeljebb 12 KiB, egy manifest legfeljebb 32 fájl; nagyobb könyv több content_id vagy későbbi protokollverzió.

- **Manifest payload:** `v:1`, `kind:"content"`, `content_id` UUID, `version` pozitív egész, `title` (max. 160 karakter), `language:"hu"`, `codec:"mp3"`, `sample_rate_hz:32000`, `bitrate_kbps:64`, `files:[{file_id:UUID,role:"title"|"chapter",chapter_index:null|0..N-1,size_bytes,sha256,duration_ms}]`. Pontosan egy title, folytonos fejezetindexek, egyedi file_id-k. Útvonalat a kliens nem adhat; az ESP az ID-kből képez saját biztonságos neveket.
- **Licenc payload:** `v:1`, `kind:"license"`, `device_id`, `content_id`, `content_version`, `manifest_sha256`, `grant_id` UUID, `issued_at` UTC Unix másodperc. Nincs lejárat; nem követelünk offline szerverhívást. Minden kapcsolatot és az aláírást telepítéskor/bootkori könyvtárellenőrzéskor ellenőrizni kell.
- **Firmware manifest payload:** `v:1`, `kind:"firmware"`, `hardware_id`, `version` SemVer, `secure_version` nemnegatív egész, `min_protocol:2`, `files:[{file_id,size_bytes,sha256}]` pontosan egy aláírt ESP app image-dzsel. Külön firmware-kiadói kulcs, nem eszköz- vagy licenckulcs. Secure Boot aláírást is ellenőrizni kell az image-ben, a manifest önmagában nem elég.

Gyári firmware-ben engedélyezett kiadói public key-k; új kulcs csak régi, megbízható firmware-frissítéssel vehető fel. Licenc/katalógus privát kulcs kizárólag a backend titoktárában; firmware-aláíró privát kulcs kiadói/CI titoktárban, nem szükséges az online service-re másolni. A JWS standard a csomag-aláírásé; nem saját titkosítás.

## 4. HTTP API az nginx mögött

Prefix `/api/v1`, JSON UTF-8, HTTPS. Ez külön HTTP API, nem a lokális NDJSON parancsboríték; a lokális v2 nem módosítja a §2 aláírandó bájtjait, a §3 csomagok `v:1` sémáját vagy az API verzióját. Hibaválasz: `{"error":{"code":"...","message":"..."},"request_id":"..."}`. Autentikált végpontok: `Authorization: Bearer ...`; minden objektum eszközjogosultságát szerveroldalon ellenőrizzük, a kérésbeli ID nem jogosultság. Lapozás cursorral, alap 20/max. 100. Időpont Unix másodperc. Módosító üzleti műveleteknél `Idempotency-Key` UUID: azonos kulcs+azonos kérés azonos eredmény; eltérő tartalom 409. A service OpenAPI lesz a részletes gépi HTTP-séma, e táblával egyezően.

| Metódus / relatív út | Feladat |
|---|---|
| POST `/auth/challenges` | `{device_id}` → §2 challenge; IP/eszköz rate limit, pl. 5/perc/eszköz |
| POST `/auth/sessions` | `{challenge_id,signature}` → `{access_token,expires_at,device_id}`; ismételt hitelesítési hiba limitálva |
| GET `/catalog` | nyilvános cím/leírás/ár pénznemmel; pénz egész minor-unit, nem float |
| GET `/devices/me/entitlements` | hitelesített eszköz jogosultságai |
| POST `/contents/{content_id}/delivery` | jogosultságellenőrzés → `manifest_jws`, `license_jws`, `files:[{file_id,url,expires_at}]`; 5 perces, fájlhoz+eszközhöz kötött opaque letöltőjegyek |
| GET `/downloads/{ticket}` | streaming GET/HTTP Range; ticket és eszköz-visszavonás ellenőrzése, nincs listázható publikus könyvtár; app ticketet nem logol |
| POST `/orders` | `{content_ids:[...]}` → rendelésazonosító és checkout URL; szerverárazás, session device_id |
| GET `/orders/{order_id}` | csak az adott eszköz rendelése; visszatérési URL nem fizetési bizonyíték |
| POST `/payments/webhooks/{provider}` | provider-hitelesítés az eredeti body-n, deduplikált esemény; rendelés/kereskedő/összeg/pénznem/végleges fizetett státusz egyezése után entitlement |
| GET `/firmware/latest?hardware_id=...` | engedélyezett signed manifest és image-letöltés; célhardver/session ellenőrzés |
| POST `/devices/me/recovery-key` | egyszeri kiadás vagy kifejezett forgatás `{rotate:boolean}`; új titok egyszeri válasz, régi visszavonva; idempotencia visszajátszása sem logolhat titkot |
| POST `/transfers` | a cél eszköz sessionjével: `{source_device_id,source_access_token}` VAGY `{source_device_id,recovery_key}`; cél a sessionből, nem szabadon megadva; tranzakciós összevonás és forrás-visszavonás |

A recovery-kulcs újrakiadása/forgatása friss, legfeljebb 120 s-os eszközhitelesítést és explicit appmegerősítést igényel. Idempotens titok-válasz rövid ideig titkosítva tárolható; tartósan csak hash maradhat. Átvitelnél a régi online token szintén friss, legfeljebb 120 s-os legyen. Elveszett titok és halott forrás esetén nem publikus API kerülőút, hanem admin ügyintézés. Minden csere és provisioning admin művelet ellenőrizhető auditot kap, titok nélkül.

Admin/provisioning és tartalomfeltöltés külön, nem publikus végpont/CLI adminjoggal. Adatmodell minimum: devices (id/public_key/status/security_profile), entitlements egyedi(device_id,content_id), content_versions, files, orders/order_items, payment_events egyedi(provider,event_id), challenges, sessions, recovery_hashes, transfer_audit. Tranzakciós/egyedi kulcsos védelem a párhuzamos fizetés/csere ellen. Session-, challenge- és ticketlejáratot takarítani kell.

HTTP Range és stream akkor is működjön, ha nginx szolgálja ki az adatot: kizárólag belső `internal` hely/X-Accel-Redirect vagy alkalmazáson át, ugyanazzal az engedélyellenőrzéssel. Rate/body/timeout korlátok útvonalanként; webhook nyers body érintetlen. A letöltés kezdetén érvényes ticket megkezdett streamje befejezhető; új Range kérés lejárt tickethez új delivery-t igényel.

## 5. Közös konformanciatesztek

A firmware-fejlesztő készítse el elsőként a nyelvfüggetlen `contracts/local-v2.schema.json`, `contracts/packages-v1.schema.json` és `contracts/fixtures/` alapot; app/service addig adapteres mockkal haladjon. Fixture: kérés/siker/hiba visszaadott commanddal; eltérő id/command és ismeretlen parancs; HELLO töredezve/összefűzve; LF/CRLF, magyar UTF-8 bájthatáron darabolva, escape-elt sortörés; üres sor, 32768-as határ és 32769 bájt elutasítása, sorlezárás nélküli túlméret/időtúllépés, duplikált kulcs, NaN/Infinity és régi bináris keret elutasítása; üres/csonka chunk, offsetütközés, megszakítás utáni tartós prefix. Külön, jól megjelölt **teszt** RSA-kulccsal közös challenge/signature és manifest/license jó/rossz minták; éles kulcsot soha nem teszünk ide. Minden fejlesztő ugyanazt a fixture-készletet futtassa, és szerződésmódosítást előbb itt egyeztessen.
