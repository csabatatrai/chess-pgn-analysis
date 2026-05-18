#!/usr/bin/env python3
"""
run_pipeline.py
───────────────
A teljes pipeline egy lépésben való futtatása.

Futtatás:
  python src/run_pipeline.py --pgn lichess_db_2024-01.pgn
  python src/run_pipeline.py --pgn test.pgn --max-games 10000 --skip-stockfish
"""

import sys
import os
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

BANNER = """
╔══════════════════════════════════════════════════════════╗
║          ♟️  LICHESS PGN ANALYSIS PIPELINE ♟️            ║
║                                                          ║
║  1. PGN → Parquet konverzió  (python-chess + MP)        ║
║  2. Statisztikai elemzés     (DuckDB + Polars)           ║
║  3. Stockfish elemzés        (Top ratingű játszma)       ║
║  4. Vizualizáció             (Jupyter + Plotly)          ║
╚══════════════════════════════════════════════════════════╝
"""


def print_step(n: int, title: str):
    print(f"\n{'─'*60}")
    print(f"  LÉPÉS {n}/3: {title}")
    print(f"{'─'*60}")


def run_pipeline(
    pgn_path: str,
    workers: int = config.WORKERS,
    chunk_size: int = config.CHUNK_SIZE,
    max_games: int = config.MAX_GAMES,
    skip_conversion: bool = False,
    skip_analysis: bool = False,
    skip_stockfish: bool = False,
):
    """
    Teljes pipeline futtatása.

    Args:
        pgn_path:         PGN bemeneti fájl elérési útja
        workers:          Párhuzamos workerek száma
        chunk_size:       Batch méret
        max_games:        Maximum játszmák (0 = összes)
        skip_conversion:  Kihagyja a PGN→Parquet konverziót
        skip_analysis:    Kihagyja az elemzést
        skip_stockfish:   Kihagyja a Stockfish elemzést
    """
    print(BANNER)
    total_start = time.time()

    # ── LÉPÉS 1: PGN → Parquet ──────────────────────────
    print_step(1, "PGN → Parquet konverzió")

    if skip_conversion:
        print("  ⏭️  Kihagyva (--skip-conversion)")
    elif not os.path.exists(pgn_path):
        print(f"  ✗ PGN fájl nem található: {pgn_path}")
        sys.exit(1)
    else:
        # A Windows multiprocessing miatt a pgn_to_parquet modult importálni kell név alapján.
        try:
            import importlib
            sys.path.insert(0, os.path.dirname(__file__))
            mod = importlib.import_module("pgn_to_parquet")
            mod.convert_pgn_to_parquet(
                pgn_path=pgn_path,
                output_parquet=config.GAMES_PARQUET,
                n_workers=workers,
                chunk_size=chunk_size,
                max_games=max_games
            )
        except Exception as e:
            print(f"  ✗ Konverzió sikertelen: {e}")
            raise

    # ── LÉPÉS 2: Statisztikai elemzés ───────────────────
    print_step(2, "Statisztikai elemzés (DuckDB + Polars)")

    if skip_analysis:
        print("  ⏭️  Kihagyva (--skip-analysis)")
    elif not os.path.exists(config.GAMES_PARQUET):
        print(f"  ✗ Parquet fájl hiányzik: {config.GAMES_PARQUET}")
        print("     Futtasd előbb a konverziót!")
    else:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "analysis",
                os.path.join(os.path.dirname(__file__), "02_analysis.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run_analysis(config.GAMES_PARQUET)
        except Exception as e:
            print(f"  ✗ Elemzés sikertelen: {e}")
            raise

    # ── LÉPÉS 3: Stockfish elemzés ───────────────────────
    print_step(3, "Stockfish elemzés (Top ratingű játszma)")

    if skip_stockfish:
        print("  ⏭️  Kihagyva (--skip-stockfish)")
    else:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "stockfish_analysis",
                os.path.join(os.path.dirname(__file__), "03_stockfish_analysis.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run_stockfish_analysis()
        except Exception as e:
            print(f"  ⚠️  Stockfish elemzés sikertelen: {e}")
            print("      (Ez nem blokkoló hiba – vizualizáció így is futtatható)")

    # ── ÖSSZESÍTÉS ───────────────────────────────────────
    elapsed = time.time() - total_start
    print(f"\n{'═'*60}")
    print(f"  ✅ PIPELINE KÉSZ – Összes idő: {elapsed:.1f}s")
    print(f"{'═'*60}")
    print(f"\n  Generált fájlok:")
    for path in [config.GAMES_PARQUET, config.STATS_JSON,
                 config.TOP_GAME_JSON, config.STOCKFISH_JSON]:
        if os.path.exists(path):
            size = os.path.getsize(path) / 1024 / 1024
            print(f"    ✓ {path} ({size:.1f} MB)")
        else:
            print(f"    - {path} (nem létezik)")

    print(f"\n  📊 Vizualizáció indítása:")
    print(f"     jupyter notebook notebooks/visualization.ipynb")
    print()


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Lichess PGN teljes elemző pipeline."
    )
    parser.add_argument(
        "--pgn",
        default=config.PGN_FILE,
        help=f"Bemeneti PGN fájl (alapértelmezett: {config.PGN_FILE})"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=config.WORKERS,
        help=f"Workerek száma (alapértelmezett: {config.WORKERS})"
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=config.CHUNK_SIZE,
        help=f"Batch méret (alapértelmezett: {config.CHUNK_SIZE})"
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=config.MAX_GAMES,
        help="Max játszmák (0 = összes). Teszteléshez hasznos."
    )
    parser.add_argument(
        "--skip-conversion",
        action="store_true",
        help="PGN→Parquet konverzió kihagyása (ha már megvan)"
    )
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="Statisztikai elemzés kihagyása"
    )
    parser.add_argument(
        "--skip-stockfish",
        action="store_true",
        help="Stockfish elemzés kihagyása"
    )

    args = parser.parse_args()

    run_pipeline(
        pgn_path=args.pgn,
        workers=args.workers,
        chunk_size=args.chunk_size,
        max_games=args.max_games,
        skip_conversion=args.skip_conversion,
        skip_analysis=args.skip_analysis,
        skip_stockfish=args.skip_stockfish,
    )
