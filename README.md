# ChessNarr – AI-alapú sakk narrátor

<div align="center">
<img src="output/plots/02-1 Megnyitás repertoárom.png" width="500" height="370">
<img src="output/plots/02-2 Magnus Carlsen megnyitás repertoárja.png" width="500" height="370">
</div>

Illeszts be bármilyen PGN-t, és a pipeline automatikusan elvégzi a Stockfish-elemzést, LLM-alapú angol kommentárt generál, majd TTS-sel hangosítja — a Streamlit lejátszó szinkronizáltan mutatja a táblaállásokat a hanghoz.

---

## Funkciók

- **PGN bevitel a UI-ban** – bármilyen standard PGN elfogadott, a headerek opcionálisak
- **Stockfish elemzés** – lépésenkénti cp-értékelés, fordulópont és hibák detektálása
- **LLM narráció** – élő kommentátor stílusú angol szöveg, FEN-anchor szinkronizációval
- **TTS hangosítás** – narráció felolvasása, szinkronizálva a sakktáblával
- **Interaktív lejátszó** – a táblaállás valós időben vált a narráció hangja alapján
- **Demo mód** – `streamlit_demo.py`: csak lejátszás, elemzési pipeline nélkül
- **Bulk CLI pipeline** – nagy (akár 31 GB+) Lichess PGN fájlok párhuzamos feldolgozása

---

## Hogyan működik

```
PGN input
   ↓
Stockfish elemzés (UCI subprocess, depth 12)
   ↓
LLM narráció generálás (narrator.py – FEN-anchor szinkron)
   ↓
TTS hangosítás (MP3)
   ↓
Streamlit lejátszó (tábla + hang szinkron)
```

A `narrator.py` system promptja élő kommentátor stílust kér az LLM-től, és automatikusan újrapróbálja a kérést, ha az anchor trigger_word-ök nem egyeznek pontosan a narráció szövegével.

---

## Projekt struktúra

```
chess-pgn-analysis/
├── streamlit_app.py          # Fő Streamlit UI (pipeline + lejátszó)
├── streamlit_demo.py         # Demo verzió (csak lejátszás)
├── config.py                 # Központi konfiguráció és env változók
├── secrets.example.py        # API kulcs sablon (másold le secrets.py-ként)
├── packages.txt              # Streamlit Cloud rendszercsomagok (stockfish)
├── requirements.txt          # Python függőségek
├── notebooks/
│   ├── jatek_elemzese.ipynb  # Egyedi játszma elemzés + narráció
│   └── visualization.ipynb   # Statisztikai vizualizációk (Plotly)
└── src/
    ├── narrator.py           # LLM narráció logika (system prompt + anchor validáció)
    ├── llm_client.py         # LLM provider absztrakció
    ├── tts_client.py         # TTS provider absztrakció
    ├── run_pipeline.py       # Teljes bulk pipeline egy lépésben
    ├── pgn_to_parquet.py     # PGN → Parquet konverzió (multiprocessing)
    ├── 01_pgn_to_parquet.py  # CLI wrapper a konverzióhoz
    ├── 02_analysis.py        # DuckDB/Polars statisztikák
    ├── 03_stockfish_analysis.py  # Stockfish motor elemzés
    └── 04_tts.py             # TTS pipeline futtatása
```

---

## Gyors indítás

### 1. Függőségek

```bash
pip install -r requirements.txt
```

Stockfish:
- **Windows:** az app automatikusan letölti az első futáskor
- **Linux/macOS:** `sudo apt install stockfish` vagy `brew install stockfish`

### 2. API kulcsok

```bash
cp secrets.example.py secrets.py
```

```python
CHAT_GPT_API_KEY   = "..."   # platform.openai.com/api-keys
GEMINI_API_KEY     = "..."   # aistudio.google.com/apikey
ANTHROPIC_API_KEY  = "..."   # console.anthropic.com/settings/keys
MISTRAL_API_KEY    = "..."   # console.mistral.ai/api-keys
ELEVENLABS_API_KEY = "..."   # elevenlabs.io/app/settings/api-keys
```

Elég csak azokat kitölteni, amelyeket használni szeretnél.

### 3. Streamlit indítása

```bash
streamlit run streamlit_app.py
```

Csak lejátszáshoz (meglévő narráció fájlok):

```bash
streamlit run streamlit_demo.py
```

---

## LLM és TTS provider váltás

A `config.py`-ban (vagy env változóval) állítható:

| Változó | Lehetséges értékek | Alapértelmezett |
|---|---|---|
| `LLM_PROVIDER` | `openai` \| `gemini` \| `anthropic` \| `mistral` | `openai` |
| `LLM_MODEL` | pl. `gpt-4o`, `gemini-2.0-flash-lite`, `claude-haiku-4-5-20251001` | provider alapértelmezése |
| `TTS_PROVIDER` | `openai` \| `elevenlabs` | `openai` |
| `TTS_VOICE_OPENAI` | `alloy` \| `echo` \| `fable` \| `onyx` \| `nova` \| `shimmer` | `onyx` |
| `STOCKFISH_DEPTH` | egész szám | `18` |

---

## Lichess bulk pipeline (CLI)

Nagy PGN fájlok feldolgozásához (pl. havi Lichess dump):

```bash
# Teljes pipeline
python src/run_pipeline.py --pgn lichess_db_2024-01.pgn

# Teszteléshez: csak az első 1000 játszma
python src/run_pipeline.py --pgn sajat_jatszmaim.pgn --max-games 1000

# Ha a Parquet már megvan, kihagyja a konverziót
python src/run_pipeline.py --pgn sajat_jatszmaim.pgn --skip-conversion

# Stockfish nélkül (gyorsabb)
python src/run_pipeline.py --pgn sajat_jatszmaim.pgn --skip-stockfish
```

Lichess havi dumpok: [database.lichess.org](https://database.lichess.org)

---

## A narráció JSON fájlok felépítése

A pipeline minden elemzett játszmához egy JSON fájlt ment az `output/llm-analysis/json_narracio/` mappába.

```json
{
  "white": "Kasparov, Garry",
  "black": "Topalov, Veselin",
  "paragraphs": [
    {
      "text": "Narráció szövege – élő kommentátor stílusban, angolul.",
      "anchors": [
        {
          "fen": "<FEN a lépés UTÁN>",
          "trigger_word": "<szó szerinti idézet a text mezőből>"
        }
      ]
    }
  ],
  "moves": [
    { "move_number": 0, "color": "start", "san": "",    "fen": "<kezdőállás FEN>" },
    { "move_number": 1, "color": "white", "san": "e4",  "fen": "<e4 utáni FEN>"  },
    { "move_number": 1, "color": "black", "san": "d6",  "fen": "<d6 utáni FEN>"  }
  ]
}
```

### A `moves` tömb mezői

| Mező | Típus | Jelentés |
|---|---|---|
| `move_number` | int | Sakkban szokásos lépésszám |
| `color` | `"white"` \| `"black"` \| `"start"` | Ki lépett |
| `san` | string | Az a lépés, amely az adott `fen` álláshoz vezet |
| `fen` | string | A tábla állása a lépés után |

### Az `anchors` szerepe

Az anchorok szinkronizálják a hangos lejátszást és a sakktáblát. Minden anchor megadja:
- **`fen`** – melyik állást kell mutatni a táblán
- **`trigger_word`** – a narráció szövegének melyik pontján kell erre az állásra váltani (szó szerinti idézet)

A `narrator.py` automatikusan validálja az anchorokat, és újragenerálja a narrációt, ha valamely `trigger_word` nem egyezik pontosan a bekezdés szövegével.

---

## Streamlit Community Cloud deploy

**Megjegyzés:** A Stockfish Cloud-on való működése még nem teljesen megoldott, további fejlesztést igényel.

1. Fork-old vagy push-old a repót GitHubra
2. [share.streamlit.io](https://share.streamlit.io) → New app → főfájl: `streamlit_app.py`
3. **Secrets** mezőbe add meg az API kulcsokat TOML formátumban:

```toml
CHAT_GPT_API_KEY   = "..."
GEMINI_API_KEY     = "..."
ELEVENLABS_API_KEY = "..."
```

A `packages.txt` automatikusan telepíti a Stockfish-t (`apt install stockfish`).

---

## Technológiai stack

| Eszköz | Szerepe |
|---|---|
| `streamlit` | Webes dashboard |
| `python-chess` | PGN beolvasás, táblaállapot, SVG megjelenítés |
| `stockfish` | Sakkmotor elemzés (UCI subprocess) |
| `openai` / `google-genai` / `anthropic` / `mistralai` | LLM narráció |
| `openai` / `elevenlabs` | TTS hangosítás |
| `polars` | Nagy adathalmazok elemzése (LazyFrame) |
| `duckdb` | SQL lekérdezések Parquet felett |
| `pyarrow` | Hatékony adattárolás |
| `plotly` | Interaktív vizualizációk |
| `multiprocessing` | Párhuzamos PGN feldolgozás |

---

## Megjegyzések

- A `secrets.py` nincs verziókövetésben (`.gitignore`-ban van)
- A DuckDB lekérdezőmotorként üzemel – nem hoz létre tartós `.duckdb` fájlt
- A pipeline bármilyen méretű PGN fájlra működik, nem csak Lichess-re
- Stockfish Windows-on automatikusan letöltődik, ha nincs telepítve

<details>
<summary>LICENSE</summary>

This project is provided for portfolio and educational purposes. Commercial use is strictly prohibited. See the LICENSE file for details.

</details>
