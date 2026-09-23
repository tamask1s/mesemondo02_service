# Mesemondó: a Synsigrától független service és deploy
- A közös nginx már elő van készítve: a HTTPS vhost betölti az `/etc/nginx/timeonion-services/*.conf` fájlokat; a Synsigra deploy/rollback kizárólag a saját `synsigra.conf` fájlját kezeli.
- A Mesemondó kizárólag a `mesemondo.conf` snippetet kezelje: exact `/mesemondo` és `^~ /mesemondo/`; ne írja felül a közös vhostot, a snippets könyvtárat vagy a `synsigra.conf`-ot.
- Külső cím: `https://www.timeonion.com/mesemondo/`, API: `/mesemondo/api/v1/`; a nem-www domain átirányít, ezért a kliens közvetlenül a www HTTPS-címet használja.
- A proxy távolítsa el a `/mesemondo` prefixet a belső `/api/v1/` API előtt; a backend root_path, OpenAPI és generált letöltési URL-ek a külső prefixet használják, API-redirect nélkül.
- A prompt01.md fix `/api/v1/` klienselvárását ellenőrizd: az esetleges kliensmódosítást jelezd, globális `/api/v1` route-ot ne hozz létre; Authorization, Range és a letöltési jegyek naplóvédelme maradjon helyes.
- Saját systemd service, felhasználó, DB, tárhely és szabad localhost-port kell; az Apache `127.0.0.1:8080`, Synsigra fájljai és service-ei érintetlenek, a Mesemondó ne a Synsigra frontend könyvtárába kerüljön.
- Proxy módosítás/rollback előtt közös lock: `exec 9>/etc/nginx/timeonion-services/.deploy.lock; flock -x 9`; tartsd a saját snippet mentésétől a `nginx -t`, graceful reload és esetleges saját rollback végéig; a lock fájlt ne töröld/cseréld.
- Kódfrissítéskor csak a Mesemondó backend induljon újra; változatlan proxyhoz nginx reload sem kell, Synsigra deploy soha; infrastruktúra-módosítás után ellenőrizd a Synsigra főoldalt, healthz/readyz végpontokat is.
- Részletes szerződés: `../signal_synth_saas/doc/INDEPENDENT_SERVICES.md`; a prompt01.md szerint most telepítési leírás és konfiguráció készüljön, éles Mesemondó telepítés külön jóváhagyással.
