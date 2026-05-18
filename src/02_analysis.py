#!/usr/bin/env python3
"""
02_analysis.py
──────────────
Statisztikai elemzés a Parquet fájlokon DuckDB és Polars (LazyFrame) segítségével.
Minden eredményt JSON fájlba ment a vizualizációhoz.

Futtatás:
  python src/02_analysis.py
"""

import sys
import os
import json
import time
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

import duckdb
import polars as pl

# ─────────────────────────────────────────────
# SEGÉDFÜGGVÉNYEK
# ─────────────────────────────────────────────

def load_lazy(parquet_path: str) -> pl.LazyFrame:
    """Betölti a Parquet fájlt Polars LazyFrame-ként (memória-hatékony)."""
    return pl.scan_parquet(parquet_path)


def duck(query: str, conn: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """DuckDB lekérdezés futtatása, eredmény Polars DataFrame-ként."""
    return conn.execute(query).pl()


def timed(label: str):
    """Dekorátor: kiírja a futási időt."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            t0 = time.time()
            result = fn(*args, **kwargs)
            print(f"  ✓ {label}: {time.time()-t0:.2f}s")
            return result
        return wrapper
    return decorator


def to_json_safe(obj):
    """Polars/DuckDB típusokat JSON-biztos Python típusokká alakítja."""
    if isinstance(obj, pl.DataFrame):
        return obj.to_dicts()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return obj


# ─────────────────────────────────────────────
# ELEMZÉSI FÜGGVÉNYEK
# ─────────────────────────────────────────────

def analyze_results(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """Játszma végeredmények megoszlása."""
    df = duck("""
        SELECT
            result,
            COUNT(*) AS count,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) AS pct
        FROM games
        WHERE result IN ('1-0', '0-1', '1/2-1/2')
        GROUP BY result
        ORDER BY count DESC
    """, conn)
    return {"results": df.to_dicts()}


def analyze_elo_distribution(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """Elo rating eloszlás hisztogram adatai."""
    df = duck("""
        SELECT
            FLOOR(white_elo / 100) * 100 AS elo_bucket,
            COUNT(*) AS white_count
        FROM games
        WHERE white_elo > 400 AND white_elo < 3500
        GROUP BY elo_bucket
        UNION ALL
        SELECT
            FLOOR(black_elo / 100) * 100 AS elo_bucket,
            COUNT(*) AS black_count
        FROM games
        WHERE black_elo > 400 AND black_elo < 3500
        GROUP BY elo_bucket
        ORDER BY elo_bucket
    """, conn)

    # Polars aggregáció
    elo_df = duck("""
        SELECT
            FLOOR(white_elo / 100) * 100 AS elo_bucket,
            COUNT(*) AS count
        FROM (
            SELECT white_elo AS white_elo FROM games WHERE white_elo > 400 AND white_elo < 3500
            UNION ALL
            SELECT black_elo AS white_elo FROM games WHERE black_elo > 400 AND black_elo < 3500
        )
        GROUP BY elo_bucket
        ORDER BY elo_bucket
    """, conn)

    avg = duck("""
        SELECT
            AVG(white_elo) AS avg_white,
            AVG(black_elo) AS avg_black,
            MEDIAN(white_elo) AS median_white,
            MEDIAN(black_elo) AS median_black
        FROM games
        WHERE white_elo > 400 AND black_elo > 400
    """, conn)

    return {
        "elo_histogram": elo_df.to_dicts(),
        "elo_stats": avg.to_dicts()[0]
    }


def analyze_openings(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """Top megnyitók ECO kód szerint."""
    df = duck("""
        SELECT
            eco,
            opening,
            COUNT(*) AS count,
            ROUND(100.0 * SUM(CASE WHEN result = '1-0' THEN 1 ELSE 0 END) / COUNT(*), 1) AS white_win_pct,
            ROUND(100.0 * SUM(CASE WHEN result = '0-1' THEN 1 ELSE 0 END) / COUNT(*), 1) AS black_win_pct,
            ROUND(100.0 * SUM(CASE WHEN result = '1/2-1/2' THEN 1 ELSE 0 END) / COUNT(*), 1) AS draw_pct
        FROM games
        WHERE eco IS NOT NULL AND eco != ''
        GROUP BY eco, opening
        ORDER BY count DESC
        LIMIT 30
    """, conn)
    return {"top_openings": df.to_dicts()}


def analyze_time_controls(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """Időkontrollok megoszlása."""
    df = duck("""
        SELECT
            CASE
                WHEN time_control LIKE '%+%' THEN
                    CASE
                        WHEN CAST(SPLIT_PART(time_control, '+', 1) AS INTEGER) < 60 THEN 'UltraBullet'
                        WHEN CAST(SPLIT_PART(time_control, '+', 1) AS INTEGER) < 180 THEN 'Bullet'
                        WHEN CAST(SPLIT_PART(time_control, '+', 1) AS INTEGER) < 600 THEN 'Blitz'
                        WHEN CAST(SPLIT_PART(time_control, '+', 1) AS INTEGER) < 1800 THEN 'Rapid'
                        ELSE 'Classical'
                    END
                WHEN time_control = '-' THEN 'Correspondence'
                ELSE 'Egyéb'
            END AS time_class,
            COUNT(*) AS count,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) AS pct
        FROM games
        WHERE time_control IS NOT NULL AND time_control != ''
        GROUP BY time_class
        ORDER BY count DESC
    """, conn)
    return {"time_controls": df.to_dicts()}


def analyze_move_counts(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """Játszma hossza (lépések száma) eloszlás."""
    df = duck("""
        SELECT
            num_moves,
            COUNT(*) AS count
        FROM games
        WHERE num_moves > 0 AND num_moves < 300
        GROUP BY num_moves
        ORDER BY num_moves
    """, conn)

    stats = duck("""
        SELECT
            AVG(num_moves) AS avg_moves,
            MEDIAN(num_moves) AS median_moves,
            MIN(num_moves) AS min_moves,
            MAX(num_moves) AS max_moves,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY num_moves) AS p25,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY num_moves) AS p75
        FROM games
        WHERE num_moves > 0
    """, conn)

    return {
        "move_count_dist": df.to_dicts(),
        "move_stats": stats.to_dicts()[0]
    }


def analyze_daily_activity(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """Napi játszma aktivitás."""
    df = duck("""
        SELECT
            date,
            COUNT(*) AS count
        FROM games
        WHERE date IS NOT NULL AND date != '' AND date != '????.??.??'
        GROUP BY date
        ORDER BY date
    """, conn)
    return {"daily_activity": df.to_dicts()}


def analyze_termination(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """Hogyan érnek véget a játszmák."""
    df = duck("""
        SELECT
            termination,
            COUNT(*) AS count,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) AS pct
        FROM games
        WHERE termination IS NOT NULL AND termination != ''
        GROUP BY termination
        ORDER BY count DESC
        LIMIT 15
    """, conn)
    return {"terminations": df.to_dicts()}


def analyze_top_players(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """Legtöbbet játszott játékosok."""
    df = duck("""
        SELECT player, COUNT(*) AS games, MAX(elo) AS peak_elo
        FROM (
            SELECT white AS player, white_elo AS elo FROM games WHERE white_elo > 0
            UNION ALL
            SELECT black AS player, black_elo AS elo FROM games WHERE black_elo > 0
        )
        GROUP BY player
        ORDER BY games DESC
        LIMIT 20
    """, conn)
    return {"top_players": df.to_dicts()}


def find_highest_rated_game(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """
    Megkeresi a két legmagasabb össz-ratingű játékos játszmáját
    (Stockfish elemzéshez).
    """
    df = duck("""
        SELECT
            game_id,
            white,
            black,
            white_elo,
            black_elo,
            (white_elo + black_elo) AS total_elo,
            result,
            moves_uci,
            eco,
            opening,
            date,
            time_control
        FROM games
        WHERE white_elo > 2000 AND black_elo > 2000
          AND moves_uci IS NOT NULL AND moves_uci != ''
        ORDER BY total_elo DESC
        LIMIT 1
    """, conn)

    if len(df) == 0:
        return {}

    row = df.to_dicts()[0]
    return {"top_game": row}


def analyze_eco_categories(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """ECO kategóriák (A-E) megoszlása."""
    df = duck("""
        SELECT
            LEFT(eco, 1) AS eco_cat,
            COUNT(*) AS count,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) AS pct
        FROM games
        WHERE eco IS NOT NULL AND eco != '' AND LENGTH(eco) >= 1
        GROUP BY eco_cat
        ORDER BY eco_cat
    """, conn)
    return {"eco_categories": df.to_dicts()}


def analyze_rating_advantage(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """Rating különbség hatása a győzelmi esélyekre."""
    df = duck("""
        SELECT
            FLOOR((white_elo - black_elo) / 50.0) * 50 AS elo_diff_bucket,
            COUNT(*) AS count,
            ROUND(100.0 * SUM(CASE WHEN result = '1-0' THEN 1 ELSE 0 END) / COUNT(*), 1) AS white_win_pct,
            ROUND(100.0 * SUM(CASE WHEN result = '0-1' THEN 1 ELSE 0 END) / COUNT(*), 1) AS black_win_pct,
            ROUND(100.0 * SUM(CASE WHEN result = '1/2-1/2' THEN 1 ELSE 0 END) / COUNT(*), 1) AS draw_pct
        FROM games
        WHERE white_elo > 400 AND black_elo > 400
          AND ABS(white_elo - black_elo) <= 500
        GROUP BY elo_diff_bucket
        ORDER BY elo_diff_bucket
    """, conn)
    return {"rating_advantage": df.to_dicts()}


# ─────────────────────────────────────────────
# FŐ ELEMZÉSI FUTTATÁS
# ─────────────────────────────────────────────

def run_analysis(parquet_path: str = config.GAMES_PARQUET) -> Dict[str, Any]:
    """Teljes elemzési pipeline futtatása."""

    if not os.path.exists(parquet_path):
        raise FileNotFoundError(
            f"Parquet fájl nem található: {parquet_path}\n"
            f"Előbb futtasd: python src/01_pgn_to_parquet.py"
        )

    size_mb = os.path.getsize(parquet_path) / 1024 / 1024
    print(f"\n📊 Statisztikai elemzés: {parquet_path} ({size_mb:.1f} MB)")

    conn = duckdb.connect()
    conn.execute(f"CREATE VIEW games AS SELECT * FROM read_parquet('{parquet_path}')")

    # Teljes játszma szám
    total = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    print(f"   Összes játszma: {total:,}\n")

    stats: Dict[str, Any] = {"total_games": total}

    analyses = [
        ("Eredmények",              analyze_results),
        ("Elo eloszlás",            analyze_elo_distribution),
        ("Megnyitók",               analyze_openings),
        ("Időkontrollok",           analyze_time_controls),
        ("Lépés számok",            analyze_move_counts),
        ("Napi aktivitás",          analyze_daily_activity),
        ("Befejezési módok",        analyze_termination),
        ("Top játékosok",           analyze_top_players),
        ("ECO kategóriák",          analyze_eco_categories),
        ("Rating hatás",            analyze_rating_advantage),
        ("Legjobb játszma",         find_highest_rated_game),
    ]

    for label, fn in analyses:
        t0 = time.time()
        try:
            result = fn(conn)
            stats.update(result)
            print(f"  ✓ {label}: {time.time()-t0:.2f}s")
        except Exception as e:
            print(f"  ✗ {label}: HIBA – {e}")

    conn.close()

    # Mentés
    os.makedirs(config.ANALYSIS_DIR, exist_ok=True)
    with open(config.STATS_JSON, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2, default=str)

    # Top játszma külön mentése (Stockfish-hez)
    if "top_game" in stats:
        with open(config.TOP_GAME_JSON, "w", encoding="utf-8") as f:
            json.dump(stats["top_game"], f, ensure_ascii=False, indent=2)
        print(f"\n♟️  Legjobb játszma: {stats['top_game'].get('white', '?')} vs "
              f"{stats['top_game'].get('black', '?')} "
              f"({stats['top_game'].get('total_elo', 0):,} össz Elo)")

    print(f"\n✅ Elemzés kész! → {config.STATS_JSON}")
    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Statisztikai elemzés Parquet adatokon.")
    parser.add_argument("--parquet", default=config.GAMES_PARQUET, help="Parquet fájl")
    args = parser.parse_args()
    run_analysis(args.parquet)
