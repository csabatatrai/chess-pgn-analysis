#!/usr/bin/env python3
"""
run_pipeline.py
───────────────
A teljes pipeline futtatása egy vagy több PGN fájlra.

Futtatás – egyetlen fájl (teljes pipeline):
  python src/run_pipeline.py --pgn data/pgns/sakkpartik.pgn
  python src/run_pipeline.py --pgn data/pgns/sakkpartik.pgn --skip-stockfish

Futtatás – teljes pgns/ mappa konvertálása (csak konverzió, elemzés nélkül):
  python src/run_pipeline.py --pgns-dir data/pgns/
  python src/run_pipeline.py --pgns-dir data/pgns/ --force
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


def needs_processing(pgn_path: str, parquet_path: str) -> bool:
    """True, ha a parquet hiányzik vagy régebbi a PGN-nél."""
    if not os.path.exists(parquet_path):
        return True
    return os.path.getmtime(pgn_path) > os.path.getmtime(parquet_path)


def _convert_single(pgn_path: str, output_parquet: str, workers: int, chunk_size: int, max_games: int):
    """Egy PGN → Parquet konverzió (a pipeline 1. lépése)."""
    try:
        import importlib
        sys.path.insert(0, os.path.dirname(__file__))
        mod = importlib.import_module("pgn_to_parquet")
        mod.convert_pgn_to_parquet(
            pgn_path=pgn_path,
            output_parquet=output_parquet,
            n_workers=workers,
            chunk_size=chunk_size,
            max_games=max_games,
        )
    except Exception as e:
        print(f"  ✗ Konverzió sikertelen: {e}")
        raise


def run_batch_conversion(
    pgns_dir: str,
    force: bool = False,
    workers: int = config.WORKERS,
    chunk_size: int = config.CHUNK_SIZE,
    max_games: int = config.MAX_GAMES,
):
    """
    A pgns_dir könyvtár összes PGN fájlját konvertálja parquet-té.
    Kihagyja azokat, amelyekhez már létezik naprakész parquet (kivéve ha force=True).
    """
    pgn_files = sorted(
        f for f in os.listdir(pgns_dir) if f.lower().endswith(".pgn")
    )

    if not pgn_files:
        print(f"  ⚠️  Nem található PGN fájl: {pgns_dir}")
        return

    print(f"\n{'═'*60}")
    print(f"  Batch konverzió: {pgns_dir}  ({len(pgn_files)} fájl)")
    print(f"{'═'*60}")

    converted, skipped, failed = 0, 0, 0
    batch_start = time.time()

    for pgn_file in pgn_files:
        pgn_path     = os.path.join(pgns_dir, pgn_file)
        parquet_path = config.pgn_to_parquet_path(pgn_path)

        if not force and not needs_processing(pgn_path, parquet_path):
            size_mb = os.path.getsize(parquet_path) / 1024 / 1024
            print(f"\n  ⏭️  {pgn_file}  →  naprakész ({size_mb:.1f} MB), kihagyva")
            skipped += 1
            continue

        reason = "frissebb PGN" if os.path.exists(parquet_path) else "nincs parquet"
        print(f"\n  ▶  {pgn_file}  →  {os.path.basename(parquet_path)}  ({reason})")
        try:
            _convert_single(pgn_path, parquet_path, workers, chunk_size, max_games)
            converted += 1
        except Exception:
            failed += 1

    elapsed = time.time() - batch_start
    print(f"\n{'═'*60}")
    print(f"  Batch kész – {elapsed:.1f}s")
    print(f"  ✅ Konvertálva: {converted}   ⏭️  Kihagyva: {skipped}   ✗ Sikertelen: {failed}")
    print(f"{'═'*60}\n")


def run_pipeline(
    pgn_path: str,
    workers: int = config.WORKERS,
    chunk_size: int = config.CHUNK_SIZE,
    max_games: int = config.MAX_GAMES,
    force: bool = False,
    skip_conversion: bool = False,
    skip_analysis: bool = False,
    skip_stockfish: bool = False,
):
    """
    Teljes pipeline futtatása egyetlen PGN fájlra.

    Args:
        pgn_path:         PGN bemeneti fájl elérési útja
        workers:          Párhuzamos workerek száma
        chunk_size:       Batch méret
        max_games:        Maximum játszmák (0 = összes)
        force:            Újrafeldolgozás akkor is, ha parquet naprakész
        skip_conversion:  Kihagyja a PGN→Parquet konverziót
        skip_analysis:    Kihagyja az elemzést
        skip_stockfish:   Kihagyja a Stockfish elemzést
    """
    print(BANNER)
    total_start = time.time()

    output_parquet = config.pgn_to_parquet_path(pgn_path)

    # ── LÉPÉS 1: PGN → Parquet ──────────────────────────
    print_step(1, "PGN → Parquet konverzió")

    if skip_conversion:
        print("  ⏭️  Kihagyva (--skip-conversion)")
    elif not os.path.exists(pgn_path):
        print(f"  ✗ PGN fájl nem található: {pgn_path}")
        sys.exit(1)
    elif not force and not needs_processing(pgn_path, output_parquet):
        size_mb = os.path.getsize(output_parquet) / 1024 / 1024
        print(f"  ⏭️  Parquet naprakész ({size_mb:.1f} MB), kihagyva  (--force a kényszerített újrafeldolgozáshoz)")
    else:
        _convert_single(pgn_path, output_parquet, workers, chunk_size, max_games)

    # ── LÉPÉS 2: Statisztikai elemzés ───────────────────
    print_step(2, "Statisztikai elemzés (DuckDB + Polars)")

    if skip_analysis:
        print("  ⏭️  Kihagyva (--skip-analysis)")
    elif not os.path.exists(output_parquet):
        print(f"  ✗ Parquet fájl hiányzik: {output_parquet}")
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
            mod.run_analysis(output_parquet)
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
    for path in [output_parquet, config.STATS_JSON,
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
        description="Lichess PGN elemző pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Példák:\n"
            "  Egy fájl teljes pipeline:\n"
            "    python src/run_pipeline.py --pgn data/pgns/sakkpartik.pgn\n\n"
            "  Batch konverzió (csak az újak):\n"
            "    python src/run_pipeline.py --pgns-dir data/pgns/\n\n"
            "  Batch konverzió (mind újrafeldolgozva):\n"
            "    python src/run_pipeline.py --pgns-dir data/pgns/ --force\n"
        ),
    )

    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument(
        "--pgn",
        help="Egyetlen bemeneti PGN fájl (teljes pipeline: konverzió + elemzés + Stockfish)",
    )
    source.add_argument(
        "--pgns-dir",
        metavar="DIR",
        help="Könyvtár: összes PGN fájlt konvertálja parquet-té (elemzés nélkül)",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Újrafeldolgozás akkor is, ha a parquet már naprakész",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=config.WORKERS,
        help=f"Workerek száma (alapértelmezett: {config.WORKERS})",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=config.CHUNK_SIZE,
        help=f"Batch méret (alapértelmezett: {config.CHUNK_SIZE})",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=config.MAX_GAMES,
        help="Max játszmák (0 = összes). Teszteléshez hasznos.",
    )
    parser.add_argument(
        "--skip-conversion",
        action="store_true",
        help="PGN→Parquet konverzió kihagyása (csak --pgn módban)",
    )
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="Statisztikai elemzés kihagyása (csak --pgn módban)",
    )
    parser.add_argument(
        "--skip-stockfish",
        action="store_true",
        help="Stockfish elemzés kihagyása (csak --pgn módban)",
    )

    args = parser.parse_args()

    if args.pgns_dir:
        run_batch_conversion(
            pgns_dir=args.pgns_dir,
            force=args.force,
            workers=args.workers,
            chunk_size=args.chunk_size,
            max_games=args.max_games,
        )
    else:
        pgn = args.pgn or config.PGN_FILE
        run_pipeline(
            pgn_path=pgn,
            workers=args.workers,
            chunk_size=args.chunk_size,
            max_games=args.max_games,
            force=args.force,
            skip_conversion=args.skip_conversion,
            skip_analysis=args.skip_analysis,
            skip_stockfish=args.skip_stockfish,
        )
