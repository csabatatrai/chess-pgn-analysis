# ♟️ Lichess PGN Analysis Pipeline

Nagyméretű (akár 31 GB+) Lichess PGN fájlok elemzésére és vizualizálására épített, moduláris, nagy teljesítményű pipeline.

## 📁 Projekt struktúra

```
lichess_pipeline/
├── README.md
├── requirements.txt
├── config.py                    # Központi konfiguráció
├── src/
│   ├── 01_pgn_to_parquet.py    # PGN → Parquet konverzió (multiprocessing)
│   ├── 02_analysis.py          # DuckDB/Polars alapú statisztikák
│   ├── 03_stockfish_analysis.py # Stockfish elemzés a top játékosok játszmájára
│   └── run_pipeline.py         # Teljes pipeline futtatása egy lépésben
├── notebooks/
│   └── visualization.ipynb     # Plotly vizualizációk Jupyter Notebookban
├── output/                     # Generált fájlok (parquet, JSON, képek)
└── data/                       # (ide kerül a Stockfish bináris, ha szükséges)
```

## 🚀 Gyors indítás

### 1. Függőségek telepítése
```bash
pip install -r requirements.txt
```

### 2. Teljes pipeline futtatása
```bash
# PGN fájlt a gyökérkönyvtárba kell helyezni, pl.: lichess_db_2024-01.pgn
python src/run_pipeline.py --pgn your_file.pgn
```

### 3. Csak az egyes lépések futtatása
```bash
# 1. lépés: PGN konverzió
python src/01_pgn_to_parquet.py --pgn your_file.pgn --workers 8

# 2. lépés: Statisztikai elemzés
python src/02_analysis.py

# 3. lépés: Stockfish elemzés (opcionális, Stockfish telepítés szükséges)
# Windows esetén a pipeline automatikusan letölti és kicsomagolja a Stockfish binárist a data/stockfish könyvtárba, ha még nincs ott.
python src/03_stockfish_analysis.py

# 4. lépés: Vizualizáció
jupyter notebook notebooks/visualization.ipynb
```

## ⚙️ Konfiguráció

A `config.py` fájlban módosítható:
- `PGN_FILE`: bemeneti PGN fájl neve
- `WORKERS`: párhuzamos feldolgozó szálak száma
- `CHUNK_SIZE`: memóriahatékony feldolgozáshoz
- `STOCKFISH_PATH`: Stockfish bináris elérési útja
- `OUTPUT_DIR`: kimeneti könyvtár

## 📊 Vizualizációk saját chess.com játszmákból

1. **Játszmák hosszának eloszlása PLY-ban** – A ply féllépést jelent társasjátékokban, 1 lépés = 2 féllépés (1 sötéttel, 1 világossal!)
2. TODOs
3. TODOs
4. TODOs
5. TODOs

## Vizualizációk 1 havi Lichess játszmákból

1. TODOs
2. TODOs
3. TODOs
4. TODOs
5. TODOs

## Sakk narrátor funkció LLM + Elevenlabs segítségével

TODOs

## 🔧 Technológiai stack

| Eszköz | Szerepe |
|--------|---------|
| `python-chess` | PGN beolvasás, táblaállapot |
| `multiprocessing` | Párhuzamos PGN feldolgozás |
| `pyarrow` / `parquet` | Hatékony adattárolás |
| `polars` | Nagy adathalmazok elemzése (LazyFrame) |
| `duckdb` | SQL lekérdezések Parquet felett |
| `stockfish` | Sakkmotor elemzés |
| `plotly` | Interaktív vizualizációk |
| `jupyter` | Notebook megjelenítés |

## 📝 Megjegyzések

- A pipeline **bármilyen méretű PGN fájlra** működik, nem csak Lichess-re
- A Parquet konverzió után a nyers PGN-re már nincs szükség az elemzéshez
- Stockfish elemzés opcionális; ha nincs telepítve, a pipeline kihagyja
- A LazyFrame API miatt még 100 GB+ adathalmazok is elemezhetők korlátozott RAM-mal

> A DuckDB ebben a projektben nem adatbázis-fájlként, hanem lekérdezőmotorként üzemel: közvetlenül a Parquet fájlokon fut SQL lekérdezéseket, és nem hoz létre tartós .duckdb adatbázisfájlt. Az adatok egyetlen forrása a Parquet könyvtár marad. Így nem keletkezik redundáns adatkópia, és a repo sem terhelődik nehéz bináris fájlokkal.