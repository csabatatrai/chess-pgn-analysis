"""
config.py – Központi konfiguráció a Lichess PGN elemző pipeline-hoz.
Módosítsd az alábbi értékeket a saját környezetednek megfelelően.
"""

import os
import multiprocessing

def _load_secrets():
    """Betölti a secrets.py-t fájlútvonal alapján, elkerülve a beépített secrets modul ütközést."""
    import importlib.util
    _path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secrets.py")
    spec = importlib.util.spec_from_file_location("_project_secrets", _path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod

try:
    _s = _load_secrets()
    GEMINI_API_KEY     = getattr(_s, "GEMINI_API_KEY", "")
    CHAT_GPT_API_KEY   = getattr(_s, "CHAT_GPT_API_KEY", "")
    ANTHROPIC_API_KEY  = getattr(_s, "ANTHROPIC_API_KEY", "")
    MISTRAL_API_KEY    = getattr(_s, "MISTRAL_API_KEY", "")
    ELEVENLABS_API_KEY = getattr(_s, "ELEVENLABS_API_KEY", "")
except FileNotFoundError:
    GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
    CHAT_GPT_API_KEY   = os.environ.get("CHAT_GPT_API_KEY", "")
    ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
    MISTRAL_API_KEY    = os.environ.get("MISTRAL_API_KEY", "")
    ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

# ─────────────────────────────────────────────
# NYELVI MODELL (LLM) BEÁLLÍTÁSOK
# ─────────────────────────────────────────────
# Melyik providert használja a narráció-generáláshoz.
# Lehetséges értékek: "openai" | "gemini" | "anthropic" | "mistral"
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")

# Alapértelmezett modellek providerenként (felülírható env változóval)
LLM_DEFAULT_MODELS = {
    "openai":    "gpt-4o-mini",
    "gemini":    "gemini-2.0-flash-lite",
    "anthropic": "claude-haiku-4-5-20251001",
    "mistral":   "mistral-small-latest",
}
LLM_MODEL = os.environ.get("LLM_MODEL", LLM_DEFAULT_MODELS.get(LLM_PROVIDER, ""))

# Az aktív provider API kulcsa
_LLM_KEY_MAP = {
    "openai":    CHAT_GPT_API_KEY,
    "gemini":    GEMINI_API_KEY,
    "anthropic": ANTHROPIC_API_KEY,
    "mistral":   MISTRAL_API_KEY,
}
LLM_API_KEY = _LLM_KEY_MAP.get(LLM_PROVIDER, "")

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
LLM_ANALYSIS_DIR = os.path.join(OUTPUT_DIR, "llm-analysis")
LLM_ANALYSIS_SZOVEGES_DIR = os.path.join(LLM_ANALYSIS_DIR, "szoveges")
LLM_ANALYSIS_HANGOS_DIR = os.path.join(LLM_ANALYSIS_DIR, "hangos_narracio")

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

# ─────────────────────────────────────────────
# LLM ELEMZÉS KIMENETI FÁJLOK
# ─────────────────────────────────────────────
# Játszma sorszáma – fájlnevekben szerepel a visszakövethetőségért
GAME_NUMBER = int(os.environ.get("GAME_NUMBER", 1))

# Elemzett játszma PGN-je (az llm-analysis mappában)
ELEMZETT_PGN = os.path.join(LLM_ANALYSIS_DIR, "elemzett.pgn")

# ─────────────────────────────────────────────
# TTS BEÁLLÍTÁSOK
# ─────────────────────────────────────────────
# Melyik TTS providert használja. "openai" | "elevenlabs"
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "openai")

# OpenAI TTS hang: alloy | echo | fable | onyx | nova | shimmer
TTS_VOICE_OPENAI = os.environ.get("TTS_VOICE_OPENAI", "nova")

# OpenAI TTS modell: tts-1 | tts-1-hd
TTS_MODEL_OPENAI = os.environ.get("TTS_MODEL_OPENAI", "tts-1")

# ElevenLabs hang ID (alapértelmezett: Rachel – eleven_multilingual_v2 modellel)
TTS_VOICE_ELEVENLABS = os.environ.get("TTS_VOICE_ELEVENLABS", "21m00Tcm4TlvDq8ikWAM")

# Könyvtárak létrehozása (ha nem léteznek)
for _dir in [OUTPUT_DIR, PARQUET_DIR, ANALYSIS_DIR, PLOTS_DIR, DATA_DIR, LLM_ANALYSIS_DIR,
             LLM_ANALYSIS_SZOVEGES_DIR, LLM_ANALYSIS_HANGOS_DIR]:
    os.makedirs(_dir, exist_ok=True)
