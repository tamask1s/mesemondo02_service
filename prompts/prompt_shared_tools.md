# A VPS-en már elérhető fejlesztői eszközök
- User: `graphyt2`; új SSH/login Bash alatt a `~/.local/bin` és az NVM bin könyvtára a PATH része; meglévő terminálban `exec bash -l` frissíti a környezetet.
- Meglévő rendszer-Python: `/usr/bin/python3` (3.8.10); a Synsigra ezt használja, ne cseréld le.
- `python`, `pip`, `uv`, `uvx` közösen elérhető a `~/.local/bin` alatt; az eszközkörnyezet `~/.local/share/python-tools`, nem a Mesemondó repóban van.
- A `python` és `pip` ehhez az eszközkörnyezethez tartozik; projektfüggőségekhez saját `.venv` kell, ne ide telepítsd a service csomagjait.
- Újabb Python igénye esetén előbb `uv python list --only-installed`; szükség esetén egyszer `uv python install 3.12`, majd `uv venv --python 3.12 .venv`; a letöltött interpreter felhasználói szinten újrahasználható.
- Csomagok telepítése pl. `uv pip install --python .venv/bin/python -r requirements.txt`; rögzített függőségeket használj. A 3.8-as Python nem feltétlenül elég a választott új FastAPI-verzióhoz.
- Node v24.21.0 + npm az NVM alatt, Codex 0.155.1; gcc, cmake, git és curl már rendelkezésre áll. Induláskor `command -v` / `--version` alapján ellenőrizz, ne telepíts mindent újra.
- Az npm/apt letöltési cache ki lett ürítve; projektfájlok, build-ek és élő service-adatok megmaradtak. A repo `.tools` könyvtárát másik munkamenet használhatja, ne töröld automatikusan.
- Az azonos user azonos telepített eszközöket ér el, de a Codex sandbox hálózati/írási engedélyei sessionfüggők; jogosultsági hibára ne újratelepítéssel reagálj.
