# ChessNarr – Felhasználói kézikönyv

Ez a leírás azoknak szól, akik nem programozók, de szeretnék használni a ChessNarr programot.

---

## Mi ez a program?

A ChessNarr egy sakk-elemző és narrátor alkalmazás. Beillesztesz egy sakkjátszma leírást (PGN formátum), és a program:

1. **elemzi a játszmát** – Stockfish sakkmotorral méri fel a lépések minőségét
2. **szöveges kommentárt ír** – mesterséges intelligencia fogalmazza meg, mint egy élő sportkommentátor
3. **hangosan felolvassa** – szövegfelolvasó hangosítja a kommentárt
4. **szinkronizálva mutatja a táblát** – a sakktábla állása követi a hangot

---

## Mi az a PGN fájl?

A PGN (Portable Game Notation) a sakkjátszmák standard leírási formátuma. Így néz ki:

```
[White "Kasparov, Garry"]
[Black "Topalov, Veselin"]
[Result "1-0"]

1. e4 d6 2. d4 Nf6 3. Nc3 g6 ...
```

Minden online sakkplatform lehetővé teszi a játszmák PGN formátumban való letöltését – lásd alább.

---

## Hogyan szerezzek PGN fájlt?

### Chess.com-ról

1. Nyisd meg a [chess.com](https://www.chess.com) oldalt, és jelentkezz be
2. Kattints a profilodra → **Games** (Játszmák)
3. Keress ki egy játszmát, és kattints rá
4. A játszma nézőkéjén kattints a **⋮ (három pont)** ikonra
5. Válaszd az **Export PGN** opciót
6. Másold ki a szöveget, vagy mentsd el `.pgn` kiterjesztéssel

### Lichess.org-ról

1. Nyisd meg a [lichess.org](https://lichess.org) oldalt, és jelentkezz be
2. Kattints a nevedre a jobb felső sarokban → **Export games**
3. Beállíthatod, hány játszmát szeretnél letölteni
4. Kattints a **Download** gombra – `.pgn` fájl mentődik a gépedre

### Híresebb játszmák

A [chessgames.com](https://www.chessgames.com) vagy [365chess.com](https://www.365chess.com) oldalon keress rá bármely nagymester nevére, és tölts le PGN-t.

---

## Telepítés

> Ha valaki már beállította neked a programot, ugorj a **Program indítása** részre.

### Szükséges előfeltételek

- Python 3.10 vagy újabb – [python.org/downloads](https://www.python.org/downloads/)
- Git – [git-scm.com/downloads](https://git-scm.com/downloads)

### Lépések

**1. Töltsd le a programot**

```
git clone https://github.com/csabatatrai/chess-pgn-analysis.git
cd chess-pgn-analysis
```

**2. Telepítsd a függőségeket**

```
pip install -r requirements.txt
```

**3. Másold le az API kulcs sablont**

```
cp secrets.example.py secrets.py
```

Nyisd meg a `secrets.py` fájlt egy szövegszerkesztővel, és add meg legalább az egyik LLM (szövegíró) és TTS (hangosító) kulcsot. Ha nincs saját kulcsod, kérd meg a program üzemeltetőjét.

---

## A program két módja

| | Demo mód | Teljes mód |
|---|---|---|
| API kulcs kell? | Nem | Igen |
| Mit csinál? | Előre elkészített narráció lejátszása | Saját játszma elemzése + új narráció generálása |
| Indítás | `streamlit run streamlit_demo.py` | `streamlit run streamlit_app.py` |

---

## Demo mód – kész narrációk lejátszása

Ha csak meg szeretnéd nézni, hogyan működik a program – API kulcs nélkül:

```
streamlit run streamlit_demo.py
```

A böngésző automatikusan megnyílik (vagy nyisd meg kézzel: `http://localhost:8501`).

A bal oldali listából kiválaszthatsz egy előre elkészített játszmát (pl. Kasparov vs. Topalov, Fischer vs. Tal). Kattints a **▶ Play** gombra, és figyeld, ahogy a sakktábla szinkronban követi a hangos kommentárt.

---

## Teljes mód – saját játszma elemzése

```
streamlit run streamlit_app.py
```

### Lépések az alkalmazásban

**1. PGN beillesztése**
A bal oldali szövegmezőbe illeszd be a játszma PGN szövegét, vagy töltsd fel a `.pgn` fájlt.

**2. Elemzés indítása**
Kattints az **Elemzés** gombra. A program elvégzi a következőket:
- Sakkmotoros elemzés (Stockfish) – lépésenkénti értékelés, hibák és fordulópontok meghatározása
- Narráció generálása AI segítségével – kb. 30–60 másodperc
- Hangosítás – a szöveg felolvasása

> Az első alkalommal a Stockfish sakkmotort is letölti a program (~100 MB). Ez csak egyszer szükséges.

**3. Lejátszás**
Kattints a **▶ Play** gombra. A sakktábla és a hangos kommentár egyszerre indul, szinkronban.

---

## Játszmák tömeges feldolgozása (statisztikákhoz)

Ha sok játszmádat szeretnéd egyszerre feldolgozni és statisztikákat készíteni:

### 1. Másold a PGN fájlokat a megfelelő helyre

Másold a PGN fájlokat a `data/pgns/` mappába. Érdemes játékosonként külön fájlba gyűjteni, például:

```
data/pgns/sajat_jatszmaim.pgn
data/pgns/Carlsen_7484_games.pgn
```

### 2. Futtasd a feldolgozást

Nyiss egy terminált a program mappájában, és futtasd:

```
python src/run_pipeline.py --pgns-dir data/pgns/
```

A program végigmegy az összes PGN fájlon, és csak azokat dolgozza fel, amelyek újak vagy megváltoztak a legutóbbi feldolgozás óta. Ezer játszma feldolgozása kb. 1 perc.

Ha egyetlen fájlt szeretnél elemezni statisztikákkal együtt:

```
python src/run_pipeline.py --pgn data/pgns/sajat_jatszmaim.pgn
```

### 3. Nyisd meg a vizualizációs notebookot

```
jupyter notebook notebooks/visualization.ipynb
```

Futtasd le sorban a cellákat (Shift+Enter), és interaktív grafikonok jelennek meg:

- **Játszmák hossza** – hány lépéses játszmákat játszottál leggyakrabban
- **Megnyitás-repertoár térkép** – melyik megnyitásokkal játszottál és milyen eredménnyel
- **Összehasonlítás** – a saját statisztikáid Magnus Carlsen játszmái mellé helyezve

---

## Beállítások

Ezeket a `config.py` fájlban, vagy környezeti változóként lehet megadni.

### LLM (szövegíró AI) váltása

| Értékek | Leírás |
|---|---|
| `"openai"` | ChatGPT (GPT-4o) – alapértelmezett |
| `"gemini"` | Google Gemini |
| `"anthropic"` | Anthropic Claude |
| `"mistral"` | Mistral AI |

A `config.py`-ban: `LLM_PROVIDER = "gemini"`

### Narrátor hang váltása (OpenAI TTS)

Elérhető hangok: `alloy`, `echo`, `fable`, `onyx` (alapértelmezett), `nova`, `shimmer`

A `config.py`-ban: `TTS_VOICE_OPENAI = "nova"`

Meghallgathatod a hangokat itt: [openai.fm](https://www.openai.fm/)

---

## Gyakori kérdések

**A program csak angolul tud kommentálni?**
Jelenleg igen – a narráció angolul generálódik. Magyar narráció is lehetséges, de ehhez a `src/narrator.py` fájlban kell módosítani a system promptot.

**Hol találom az elkészült narráció szövegét?**
Az `output/llm-analysis/szoveges/` mappában, `.txt` fájlokban.

**Hol találom a hangfájlokat?**
Az `output/llm-analysis/hangos_narracio/` mappában, `.mp3` fájlokban.

**Elmenthető a narráció?**
Igen – az `.mp3` fájlok a fentebb említett mappában megmaradnak, bármikor visszajátszhatók.

---

## Hibaelhárítás

| Hibaüzenet | Megoldás |
|---|---|
| `FileNotFoundError: secrets.py` | Másold le: `cp secrets.example.py secrets.py`, és töltsd ki az API kulcsokat |
| `Stockfish letöltése sikertelen` | Ellenőrizd az internet-kapcsolatot, vagy töltsd le kézzel a [stockfishchess.org](https://stockfishchess.org/download/) oldalról, és másold a `bin/stockfish/` mappába |
| `API kulcs érvénytelen` | Ellenőrizd a `secrets.py`-ban megadott kulcsot az adott platform oldalán |
| A böngésző nem nyílik meg automatikusan | Írd be kézzel a böngészőbe: `http://localhost:8501` |
| `Parquet fájl nem található` a notebookban | Futtasd előbb: `python src/run_pipeline.py --pgn data/pgns/<fájlnév>.pgn` |
