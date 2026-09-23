# Mesemondó02 — működés és rendszerterv

## 1. Határ és felépítés

Önálló gyermek-meselejátszó: ESP32-S3 N16R8, panelre épített microSD, MAX98357A, egy 18650; donor doboz/hangszóró/kapcsoló/négy gomb és egy hangerőpotméter. A bekötés kizárólag [HARDWARE.md](HARDWARE.md) és a hozzá tartozó rajz szerint. Nincs kamera, kijelző, külön secure element vagy külső SD-panel.

`Service (HTTPS, nginx) ↔ Flutter Windows app ↔ USB CDC / később telefon BLE ↔ ESP ↔ microSD + hangszóró`

Az app–ESP kérés/válasz soronként egy JSON-objektum, visszaadott parancsnévvel és kérésazonosítóval; a pontos formátum kizárólag a [PROTOCOL.md](PROTOCOL.md) lokális v2 szerződésében szerepel. A HTTP API ettől különálló.

Az ESP az SD kizárólagos gazdája; USB mass storage nincs. A PC/telefon kezelő és adatközvetítő, nem jogosultsági döntéshozó. Nincs normál felhasználói fiók, Wi-Fi-beállítás vagy kötelező internet a lejátszáshoz. A rádió első körben BLE; Classic Bluetooth és Bluetooth-hangszóró/A2DP mód nincs.

Két külön port: a BQ USB-C csak töltésre, az ESP USB-OTG adatra és fejlesztői programozásra. Az ESP adat-USB-je nem táplálja/tölti a készüléket; használatához S1 bekapcsolva és megfelelő rendszertáp szükséges. A bekötés és a VBUS-osztó méretezése kizárólag a [HARDWARE.md](HARDWARE.md) része.

## 2. Helyi működés — ez az egyetlen UI-specifikáció

| Kezelőszerv | Normál mód, lejátszás vagy szünet | Meseválasztó |
|---|---|---|
| M röviden | Pozíció/előző állapot megőrzése, szünet, belépés; aktuális cím bemondása | Kilépés változtatás nélkül, korábbi lejátszási/szünet állapot helyreállítása |
| + / − röviden | Következő/előző fejezet eleje; szünetállapot megmarad | Következő/előző mese címe, körbeforduló lista |
| + / − hosszan | Tekerés a tartás idején; elengedéskor az előző lejátszási/szünet állapot | Nincs ismétlés/gyorsléptetés; elengedéskor egyetlen címléptetés |
| PLAY röviden | Lejátszás/szünet | Kiválasztott mese folytatása mentett helyről; új vagy befejezett mese az elejéről |
| Potméter | Hangerő, bal végállás néma | Ugyanaz a bemondásokra is |

Gombszűrés 25 ms, hosszú nyomás 650 ms. Rövid művelet elengedéskor; normál módban hosszú nyomás után nincs rövid művelet. Tekerés: 10 másodperces lépés 300 ms-onként, csak az aktuális mesén belül, fejezethatáron át is; tartás alatt némítás. Fejezetléptetés a mese két végén nem ugrik másik mesére, rövid visszajelzés adható. M/PLAY hosszú nyomás önmagában nem új funkció.

A cím egyszer hangzik el, nincs automatikus címkör; újabb navigáció megszakítja az előző bemondást. A névsor a helyi telepített könyvtár stabil sorrendje. A választó 30 s tétlenség után megszakad, és **szünetben** tér vissza az előző meséhez. A kiválasztás nem veszti el a korábbi könyvjelzőt.

M+PLAY együtt 3 s: 120 s kezelési/párosítási ablak hangjelzéssel; az egyedi gombműveleteket elnyomja. Ez engedi új USB-kezelési munkamenet nyitását/BLE-bond felvételét. Már engedélyezett kapcsolat legfeljebb 15 perc tétlenségig él; aktív átvitel életben tartja. Egyidejűleg egy írómunkamenet, USB előnyben, nincs két konkurens feltöltés. Nem teszünk rejtett törlést/resetet hosszú gombnyomásra.

Bekapcsolás: ellenőrzött SD-könyvtár, utolsó mese címe, szünet; nincs váratlan automatikus hangos indulás. Könyvjelző mesénként, szünetkor/fejezetváltáskor és legfeljebb 15 s-onként, kopáskímélő/kettős ellenőrzött rekorddal. S1 kemény kikapcsolás, nincs garantált végső mentés; legfeljebb kb. 15 s pozícióvesztés elfogadott. Befejezéskor rövid jelzés, szünet, következő indítás ugyanazon mese elejéről. Nincs SD/üres tár/hibás fájl esetén flashből rövid magyar hibaüzenet, nem végtelen újraindulás.

Hangerő: ADC-kalibrálás és szűrés, perceptuális digitális skála, rövid rámpák a kattogás ellen. A fizikailag bemért maximális hangerőt az app nem emelheti; szülői korlát csak csökkentheti. Első bemérés nagyon alacsony digitális jelszinttel. Boot/reset, szünet, alvás és hiba esetén erősítőnémítás; engedélyezés csak az audioindítás részeként. Potméterhiba esetén néma állapot. A GPIO-polaritás és a modulmódosítás a HARDWARE.md szerint kötelező.

LED: szünetben halvány, lejátszáskor folyamatos zöld; választó kék; kezelési ablak kék villogás; átvitel lila; figyelmeztetés/hiba piros. Ne világítson feleslegesen erősen; a BQ saját LED-je csak a saját töltésállapotát jelzi. Nincs pontos százalékos töltöttség: az ADC csak terhelési tápot mér. Induló küszöbök: 3,35 V alatt 10 s-ig figyelmeztetés; 3,15 V alatt 3 s-ig mentés/némítás/alvás, 3,45 V felett visszaengedés. Ez az adat-USB jelenlététől függetlenül érvényes: az nem töltésjel. Ezek bemérendő értékek, nem helyettesítik a cellavédelmet; a felhasználót kikapcsolásra is kérjük.

## 3. Tartalom és offline tárolás

Első formátum: mono MP3, 32 kHz, CBR 64 kbit/s; külön `title` hangfájl és fejezetenként egy fájl. Egy óra kb. 28,8 MB. A backend előállításkor normalizál és ellenőriz, a firmware támogatott MP3-dekódert használ. CBR ellenére nem vak bájtoffsettel léptetünk: frame-szinkron/seek-index és dekóder-reset szükséges. I²S mindkét csatornáján ugyanaz a monó jel.

microSD első cél: 8–32 GB SDHC, FAT32, 1 bites SDMMC; több-/eltérő fájlrendszer nem MVP. 16 MB belső flash: bootloader, partíciótábla, NVS/identitás, két egyenként kb. 4 MB OTA-slot, flashbeli rendszerhangok és tartalék. Pontos partíciótábla a tényleges buildméret után; 8 MB PSRAM puffer/dekódermemória, nem tartós tár.

Telepítési egység: aláírt manifest + eszközhöz kötött aláírt licenc + a manifestben felsorolt fájlok. A protokoll írja le a bájtszintű formátumot. Átvitelnél ideiglenes terület, fájlméret/hash-ellenőrzés, végül komplett tartalom aktiválása. Ne bízzunk a FAT-átnevezés önmagában vett áramszünet-biztonságában: kettős, generációs/CRC-s könyvtárindex, flush, bootkori egyeztetés; a régi érvényes verzió az új véglegesítéséig megmarad. A teljes staging-helyet előre ellenőrizni kell.

Átvitel alatt a lejátszás szünetel; megszakadt feltöltés folytatható, a már érvényes mesék tovább használhatók. Formázás és tömeges törlés nincs automatikusan. Tartalomtörlés az appban külön megerősítéses művelet, nem vonja vissza a vásárlást.

**Tudatos MVP-korlát:** a hangfájlok az SD-n nincsenek titkosítva. A licencet a készülék ellenőrzi, a letöltést a szerver engedélyezi, de az SD-ről kimásolt MP3 máshol lejátszható. Ez jogosultságkezelés, nem másolásvédett DRM; későbbi titkosításhoz új csomagverzió kell.

## 4. Identitás, jogosultság, csere

Egyedi véletlen UUID `device_id` és RSA-3072 kulcspár. MAC-cím vagy publikus sorozatszám nem titok és nem tulajdonigazolás. Aláírás: szabványos RSASSA-PKCS1-v1_5/SHA-256 (`RS256`), szabványos kriptokönyvtárral; nincs saját padding vagy kriptográfia.

Éles ESP-n a DS periféria a titkosított RSA-paramétereket használja, eFuse-ban olvasásvédett `HMAC_DOWN_DIGITAL_SIGNATURE` kulccsal. Secure Boot v2 + egyedi Flash Encryption release-mode kulcs + titkosított érzékeny NVS; debug/letöltési utak éles policy szerint lezárva. Ez az ESP nyújtotta védelem, nem dedikált secure element fizikai támadásállósága. Fejlesztői build külön tesztidentitással, éles jogosultság nélkül; szoftveres privát kulcs csak ebben a profilban engedett.

Provisioning: megbízható gyártói eszköz létrehozza a kulcsot/ID-t, elkészíti az Espressif DS blobot, a publikus kulcsot admin jogosultsággal a backendbe regisztrálja, majd aláírási próbát végez. A privát kulcs átmeneti példánya nem kerül repóba/logba/mentésbe. eFuse-égetés külön, kifejezetten jóváhagyott művelet, előtte száraz futás és kulcshely-terv; DS, flash- és NVS-védelem nem osztozhat véletlenül ugyanazon eFuse-kulcshelyen. MCU-törlés/reset nem regisztrálhat új, éles készüléket önkiszolgáló módon.

Kapcsolódás: fizikai kezelési ablak → app kér challenge-et → ESP aláír → backend egyszer használatos nonce-ot és az ismert public key-t ellenőriz → rövid, csak az adott készülékre szóló session. Az app nem választhat másik device_id-t egy már hitelesített sessionben. A szerver tartós igazsága: `device_id → content_id` jogosultságok; a készülék az aláírt licenceket internet és megbízható valós idejű óra nélkül ellenőrzi, lejárat nélküli offline használatra.

Vásárlás: appból böngészős checkout; a rendelés device_id-hez kötött. Jogosultságot kizárólag hitelesített, idempotensen feldolgozott fizetési webhook/szerveroldali egyeztetés ad, nem a böngésző visszatérési URL-je. Konkrét fizetési szolgáltató még nincs kiválasztva: kezdetben tesztadapter, éles fizetés külön bekötés után.

Csere: az első megbízható átadáskor egy 256 bites helyreállítási titkot kell kiadni és a tulajdonossal külön elmentetni; backend csak hashét tárolja. Működő régi készüléknél friss eszközhitelesítés + az új eszköz hitelesítése; hibás réginél helyreállítási titok vagy ellenőrzött ügyfélszolgálati eljárás + új eszközhitelesítés szükséges. Átvitel egy tranzakcióban: jogosultságok összevonása, régi eszköz online visszavonása, régi sessionök törlése, új licencek és új helyreállítási titok. A régi készülék már letöltött, örökre offline meséit távolról **nem lehet garantáltan visszavonni**. Fiók nélkül, titok/bizonylat/eszköz nélkül a tulajdonjog nem állítható helyre biztosan.

## 5. App és service felelősségek

Flutter Windows 10/11 x64, első kötelező út USB CDC-ACM/COM. Eszközfelderítés, fizikai engedélyezés jelzése, katalógus/jogosultságok, vásárlásindítás, folytatható letöltés/feltöltés, helyi tárhely és törlés, firmware-frissítés, korlátozott beállítások, helyreállítási titok export, cserevarázsló. Offline app: helyi könyvtár/állapot megtekintése és korábban letöltött, ehhez az eszközhöz licencelt csomag telepítése. Új vásárlás/hitelesítés/új licenc internetes művelet. Nem kell felhős fiókbejelentkezés.

Transport interfész mögött legyen az USB és BLE. A firmware BLE-vel is támogassa a beállítást és darabolt fájlfeltöltést; a Windows első átadásának nem feltétele a BLE UI, a telefonos Flutter kliens későbbi munka. BLE LE Secure Connections/bonding + fizikai párosítási ablak; kijelző nélkül Just Works nem nyújt erős MITM-védelmet. Aláírt tartalom és backendhitelesítés ettől függetlenül szükséges. Wi-Fi alapból kikapcsolva. Jelszó, kártyaadat, device private key nem kerül az appba; session memóriában, tartós recovery titok csak Windows DPAPI-val védve vagy kifejezett exporttal.

Service-javaslat: Python/FastAPI + PostgreSQL, egyszerű helyi tartalomfájltár; nginx TLS-végpont és reverse proxy a csak loopbacken/belső hálón hallgató alkalmazás előtt. Tartalom csak ellenőrzött, rövid életű jogosultsággal; nincs publikus asset-könyvtár. Nginx konfigurációs részletet adunk, nem írjuk felül a meglévő szerverkonfigurációt. Külön admin/provisioning hozzáférés, adatbázis-migrációk, titokkezelés és DB+tartalom-visszaállítási eljárás. Személyes adat csak a vásárláshoz/ügyintézéshez szükséges mértékben; eszközazonosító nem automatikusan anonim.

## 6. Firmware-frissítés és hibabiztonság

Az app csak közvetít: firmware-célhardver, verzió, méret/hash és gyártói aláírás ellenőrzése az ESP-n is. Két OTA-slot, csak az inaktív írása; áramkimaradás a működő példányt nem törölheti. Új image csak boot-önellenőrzés után legyen érvényes; hibánál rollback. Biztonsági verzió/eFuse anti-rollback csak sikeres validálás után, előre megtervezett verziólépcsővel. Bootloader/partíciótábla távoli átírása nem MVP.

Fejlesztés alatt ugyanazon USB-OTG aljzaton BOOT+RESET/ROM letöltés és futó firmware CDC használható, időben elkülönítve. Éles biztonsági lezárás után ROM USB-helyreállítást **nem ígérünk**: az Espressif szerint Secure Boot/Flash Encryption letiltja a ROM USB-OTG letöltési útját. A saját, aláírást ellenőrző firmware-frissítés a normál út; belső UART szerviz lehetőség csak a választott éles policy által engedetten. Sikertelen mindkét image esetére gyártói szerviz/cserefolyamat szükséges.

## 7. Átadási feltételek

1. H1–H4 hardverkapuk tényleges bemérése; addig csak feltételes prototípusterv.
2. USB CDC + SD + I²S + gombok/potméter együttes működése; BLE-n ugyanaz a protokoll, megszakítás utáni folytatás.
3. Közös protokollfixture-ök: firmware/app/service azonos challenge-bájtokkal és aláírással; rossz eszköz, hash, licenc, replay és nem engedélyezett művelet elutasítása.
4. Offline lejátszás, telt/hiányzó SD, írás közbeni áramvesztés, újracsatlakozás, frissítés/rollback és cserefolyamat tesztelve. Tönkretehető teszt-SD/tartalék készülék, nem felhasználói adat.
5. Éles provisioning, fizetési adapter, recovery-export és tényleges gyermekbiztonsági/forgalmazási ellenőrzés külön release-kapuk, nem következnek a szoftvertesztek sikeréből.

Forrás: [ESP DS és szabványos PSA aláírás](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/ds.html), [ESP biztonsági munkafolyamat](https://docs.espressif.com/projects/esp-idf/en/release-v5.5/esp32s3/security/security-features-enablement-workflows.html), [USB ROM korlát](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/dfu.html), [Flutter Windows](https://docs.flutter.dev/platform-integration/windows/building), [nginx proxy](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).
