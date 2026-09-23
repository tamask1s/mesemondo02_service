# Közös, kizárólag tesztelésre szolgáló fixture-ök

A `TEST-ONLY-*.pem` kulcsok szándékosan megosztott tesztadatok. A három privát
tesztkulcs verziókezelése szükséges a reprodukálható eszköz-, manifest- és
licencaláírás-próbákhoz. Ezek nem titkos, éles kulcsok; production használatuk
tiltott, a service az ismert publikus fingerprintjeiket is elutasítja.

A `security.json` közös jó és rossz challenge/JWS mintákat tartalmaz.
A `.bin` fájlok hash-próbák bemenetei, nem telepíthető firmware-image-ek.
A `mono-32000-64k.mp3` szintetikus teszthang.

A külön generált appemulátor privát kulcsa, a szerver futási titkai és az
adatbázismentések nem tartoznak ide, és nem kerülhetnek a repóba.
