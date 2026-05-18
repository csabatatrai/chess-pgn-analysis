"""
config.py – Központi konfiguráció a Lichess PGN elemző pipeline-hoz.
Módosítsd az alábbi értékeket a saját környezetednek megfelelően.
"""

import os
import multiprocessing

# A projekt gyökérkönyvtára (ez biztosítja, hogy a relatív elérési utak mindig a repo gyökérére mutassanak)
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────────────────────────
# BEMENETI FÁJL
# ─────────────────────────────────────────────
# A PGN fájl neve (a projektgyökérben kell lennie, vagy teljes elérési út)
PGN_FILE = os.environ.get("LICHESS_PGN", "lichess_db.pgn")

# ─────────────────────────────────────────────
# FELDOLGOZÁSI BEÁLLÍTÁSOK
# ─────────────────────────────────────────────
# Párhuzamos munkások száma (0 = automatikus: CPU magok - 1)
WORKERS = int(os.environ.get("LICHESS_WORKERS", 0)) or max(1, multiprocessing.cpu_count() - 1)

# Hány játszmát dolgoz fel egyszerre egy worker (memória vs. sebesség kompromisszum)
CHUNK_SIZE = int(os.environ.get("LICHESS_CHUNK_SIZE", 50_000))

# Maximum játszmák száma (0 = összes). Teszteléshez hasznos kis értékre állítani.
MAX_GAMES = int(os.environ.get("LICHESS_MAX_GAMES", 0))

# ─────────────────────────────────────────────
# KIMENETI KÖNYVTÁR
# ─────────────────────────────────────────────
OUTPUT_DIR = os.environ.get("LICHESS_OUTPUT_DIR", "output")
if not os.path.isabs(OUTPUT_DIR):
    OUTPUT_DIR = os.path.join(ROOT_DIR, OUTPUT_DIR)
PARQUET_DIR = os.path.join(OUTPUT_DIR, "parquet")
ANALYSIS_DIR = os.path.join(OUTPUT_DIR, "analysis")
PLOTS_DIR = os.path.join(OUTPUT_DIR, "plots")

# ─────────────────────────────────────────────
# STOCKFISH
# ─────────────────────────────────────────────
# Stockfish bináris elérési útja. None = automatikus keresés PATH-ban.
STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", None)

# Stockfish letöltési URL Windows-hoz
STOCKFISH_DOWNLOAD_URL_WINDOWS = os.environ.get(
    "STOCKFISH_DOWNLOAD_URL_WINDOWS",
    "https://github.com/official-stockfish/Stockfish/releases/latest/download/stockfish-windows-x86-64-avx2.zip"
)

# Stockfish elemzési mélység
STOCKFISH_DEPTH = int(os.environ.get("STOCKFISH_DEPTH", 18))

# Hány lépést elemezzen játszmánként
STOCKFISH_MOVES_LIMIT = int(os.environ.get("STOCKFISH_MOVES_LIMIT", 40))

# Stockfish bináris és letöltési adatok
DATA_DIR = os.environ.get("LICHESS_DATA_DIR", "data")
if not os.path.isabs(DATA_DIR):
    DATA_DIR = os.path.join(ROOT_DIR, DATA_DIR)
STOCKFISH_DIR = os.path.join(DATA_DIR, "stockfish")
STOCKFISH_BINARY = os.path.join(STOCKFISH_DIR, "stockfish.exe")

# ─────────────────────────────────────────────
# PARQUET FÁJL NEVEI
# ─────────────────────────────────────────────
GAMES_PARQUET = os.path.join(PARQUET_DIR, "mychessdotcomgames.parquet")
MOVES_PARQUET = os.path.join(PARQUET_DIR, "moves.parquet")   # Opcionális, nagy méret!

# ─────────────────────────────────────────────
# ELEMZÉSI EREDMÉNY FÁJLOK
# ─────────────────────────────────────────────
STATS_JSON = os.path.join(ANALYSIS_DIR, "stats.json")
TOP_GAME_JSON = os.path.join(ANALYSIS_DIR, "top_game.json")
STOCKFISH_JSON = os.path.join(ANALYSIS_DIR, "stockfish_analysis.json")

# ─────────────────────────────────────────────
# VIZUALIZÁCIÓ
# ─────────────────────────────────────────────
PLOT_THEME = "plotly_dark"   # vagy "plotly_white", "ggplot2", stb.
PLOT_HEIGHT = 500
PLOT_WIDTH = 900

# Könyvtárak létrehozása (ha nem léteznek)
for _dir in [OUTPUT_DIR, PARQUET_DIR, ANALYSIS_DIR, PLOTS_DIR, DATA_DIR]:
    os.makedirs(_dir, exist_ok=True)
