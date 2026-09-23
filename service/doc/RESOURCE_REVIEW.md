# Kis VPS erőforrásvizsgálat – 2026-09-23

A tényleges szervert a sandboxon kívül mértük: a sandbox `/proc` nézete nem a VPS
memóriakeretét mutatja. Konténer limit: 999 997 440 bájt (kb. 953 MiB), CPU-kvóta
1,9 magnyi idő. Swap nincs.

A felhasználó által leállított Codex-folyamatok után: load 0,17 / 0,11 / 0,03,
305 MiB használt memória, 439 MiB elérhető. Nem volt aktív memórianyomás.
A `memory.events` összesített számlálója `oom=1`, `oom_kill=1`, `max=5584`:
korábban volt limitütközés és memóriahiányos folyamatkilövés. Időpont és folyamat
nem állapítható meg ezekből; az elérhető kernelnapló nem adott hozzá eseményt.
Ez nem bizonyítja, hogy minden kapcsolati akadás oka memóriahiány volt.

Egy futó Codex kb. 150 MiB RSS-t, indítófolyamata 32 MiB-t használt.
A `/dev/shm/codex-graphyt2` 210 MiB RAM-alapú átmeneti tárhelyet foglalt.
Az aktív munkamenet fájljait/folyamatait nem töröltük vagy állítottuk le.
A napi fejlesztésnél ezen a gépen egyetlen Codex-munkamenettel érdemes dolgozni;
paralel build vagy több tesztkör nem futott.

## Mesemondó – megvalósítva

- Egy Uvicorn-folyamat kettő helyett, 12 egyidejű kapcsolat, 32 backlog.
- Legfeljebb 4 szinkron handler szál és 2 rate-limit szál, a korábbi implicit
  nagyobb threadpoolok helyett.
- API systemd: `Nice=10`, `CPUQuota=50%`, `MemoryHigh=128M`, `MemoryMax=192M`.
- Saját PostgreSQL: 32 MiB shared_buffers a 128 helyett, 16 kapcsolat a 100 helyett,
  1 MiB work_mem, 16 MiB maintenance_work_mem, 8 MiB autovacuum_work_mem;
  párhuzamos lekérdezések/JIT tiltva. Tartóssági garanciák (fsync stb.) megmaradtak.
- DB systemd: `CPUQuota=30%`, `MemoryHigh=96M`, `MemoryMax=160M`.
- Hanghash és MP3-frame ellenőrzés folyamatos fájlolvasással; nem a teljes mese
  kerül RAM-ba. FFmpeg egy szállal, alacsony prioritással fut.
- Cleanup nem tölti be és ellenőrzi újra a privát RSA-kulcsokat. Lejárt
  ciphertextet csak egyszer nulláz; új részleges/lejárati indexek csökkentik
  a takarítás táblabejárásait. A percenkénti titoktakarítás megmaradt.
- A fejlesztési PostgreSQL a tesztek után leállt. Csak a telepített saját DB fut.

Az első telepítés utáni systemd-mérés: API kb. 49 MiB, DB kb. 22,5 MiB
(`MemoryCurrent`, nem terhelési csúcs). A limitek felső korlátok, nem előre lefoglalt
memória. Túlterheléskor a lassítás/elutasítás jobb, mint a teljes VPS kifogyása;
az appnak időtúllépést/idempotens újrapróbálást továbbra is kezelnie kell.

## Synsigra – mérések és javaslatok, módosítás nélkül

- A `syn_sig_ra_worker` nyugalmi PSS-e kb. 1,25 MiB: maga az állandó worker kicsi.
  A systemd unit viszont **MemoryMax=5G** értéket tartalmaz az 1 GB-os VPS-en,
  CPU-kvóta nélkül. Ez a korlát nem előzi meg a teljes konténer kifogyását.
  A fejlesztő mérje meg egy valódi generálási feladat csúcsmemóriáját, majd ahhoz
  állítson alacsonyabb korlátot és egyetlen generáló feladatot. Kiinduló vizsgálati
  tartomány 192–256 MiB, Nice=10, CPUQuota=30–50%; ezek nem kipróbált beállítások,
  a feladatok akár több memóriát is igényelhetnek. A worker mostani 1 MB-ja nem
  mutatja meg a gyermekfolyamatok csúcsterhelését.
- Apache prefork, 9 gyermekfolyamat: egyenként kb. 7,4–7,7 MiB PSS, összesen a
  szülővel kb. **68 MiB**. Ez az Apache a személyes oldalt is szolgálja, ezért nem
  csak a Synsigra alkalmazáskódjának költsége. Az `httpd-mpm.conf` include kommentelt,
  az abban látott 150-es MaxClients érték nem tekinthető aktív beállításnak.
  Kevés forgalomnál a fejlesztő mérlegelheti a `StartServers 2`, `MinSpareServers 2`,
  `MaxSpareServers 3`, `MaxClients 12–16` beállításokat, saját terhelési teszttel.
  9 helyett 3 nyugalmi gyermek kb. **45 MiB** megtakarítást jelenthet. Ez becslés,
  a CGI-k, forgalom és KeepAlive módosíthatják a tényleges eredményt.
- Nginx master + két worker összesen kb. 6 MiB PSS: itt kicsi a megtakarítás.
- A tartós journal kb. 943 MiB **lemezt** foglal; ez nem 943 MiB RAM.
  A journald memóriafogyasztása kb. 35 MiB. Retenciót külön üzemeltetési döntéssel
  lehet csökkenteni; a korábbi naplókat nem töröltük.

A Synsigra worker, Apache és közös nginx vhost konfigurációja ellenőrzőösszeg szerint
változatlan. Csak az engedélyezett `mesemondo.conf` került a közös nginxbe, lockolt
szintaxisellenőrzéssel és graceful reloaddal.

Források a beállítások értelmezéséhez:
[PostgreSQL 16 erőforráskorlátok](https://www.postgresql.org/docs/16/runtime-config-resource.html),
[Apache 2.2 prefork](https://httpd.apache.org/docs/2.2/mod/prefork.html).

Végső mérés a nyilvános HTTPS-próba után, 06:25 UTC: API 52 178 944 B,
DB 24 096 768 B, együtt **72,7 MiB** systemd MemoryCurrent. Egyik saját unit sem
indult újra hibából. 361 MiB memória elérhető, load 0,35 / 0,30 / 0,21.
Mesemondó healthz és readyz HTTP 200 (~0,06 s), Synsigra főoldal/healthz/readyz
szintén HTTP 200. Ezek pillanatfelvételek, nem csúcsterhelési kapacitásmérések.
