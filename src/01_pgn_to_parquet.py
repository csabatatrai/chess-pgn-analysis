#!/usr/bin/env python3
"""
01_pgn_to_parquet.py
────────────────────
Nagy PGN fájl → Apache Parquet konverzió.

Stratégia:
  - Egy olvasó folyamat tölti be a játszmákat a PGN-ből és feltölti a sorba.
  - N worker folyamat dolgozza fel a játszmákat és írja ki Parquet partíciókba.
  - Végül az összes partíciót egyetlen games.parquet fájlba egyesíti.

Futtatás:
  python src/01_pgn_to_parquet.py --pgn lichess_db.pgn --workers 8
"""

import sys
import os
import argparse
import time
import math
import multiprocessing as mp
from multiprocessing import Queue, Process
from typing import Optional, List, Dict, Any

import chess.pgn
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

# A config.py a szülőkönyvtárban van
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# ─────────────────────────────────────────────
# SÉMA – milyen mezőket mentünk el játszmánként
# ─────────────────────────────────────────────
SCHEMA = pa.schema([
    pa.field("game_id",       pa.int32()),
    pa.field("event",         pa.string()),
    pa.field("site",          pa.string()),
    pa.field("date",          pa.string()),
    pa.field("white",         pa.string()),
    pa.field("black",         pa.string()),
    pa.field("result",        pa.string()),
    pa.field("white_elo",     pa.int16()),
    pa.field("black_elo",     pa.int16()),
    pa.field("white_rd",      pa.float32()),
    pa.field("black_rd",      pa.float32()),
    pa.field("eco",           pa.string()),
    pa.field("opening",       pa.string()),
    pa.field("time_control",  pa.string()),
    pa.field("termination",   pa.string()),
    pa.field("num_moves",     pa.int16()),
    pa.field("moves_uci",     pa.string()),   # space-separated UCI lépések
    pa.field("clock_times",   pa.string()),   # space-separated másodpercek (ha van)
])


def safe_int(value: Optional[str], default: int = 0) -> int:
    """Biztonságos egész konverzió."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Optional[str], default: float = 0.0) -> float:
    """Biztonságos lebegőpontos konverzió."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_clock(comment: str) -> Optional[str]:
    """
    Kiszedi a [%clk H:MM:SS] kommentből az időt másodpercben.
    Visszaad None-t, ha nincs ilyen komment.
    """
    if "%clk" not in comment:
        return None
    try:
        clk_part = comment.split("%clk")[1].strip().lstrip("[ ").split("]")[0].strip()
        parts = clk_part.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return str(int(h) * 3600 + int(m) * 60 + int(float(s)))
        elif len(parts) == 2:
            m, s = parts
            return str(int(m) * 60 + int(float(s)))
    except Exception:
        pass
    return None


def extract_game_row(game: chess.pgn.Game, game_index: int) -> Dict[str, Any]:
    """Egy chess.pgn.Game objektumból kinyeri a szükséges mezőket."""
    headers = game.headers

    # Lépések és óraadatok
    moves_uci = []
    clock_times = []
    node = game
    while node.variations:
        next_node = node.variation(0)
        move = next_node.move
        if move:
            moves_uci.append(move.uci())
        # Óra komment
        clk = parse_clock(next_node.comment or "")
        if clk:
            clock_times.append(clk)
        node = next_node

    num_moves = len(moves_uci)

    game_id = game_index + 1

    site = headers.get("Site", "")
    return {
        "game_id":      game_id,
        "event":        headers.get("Event", ""),
        "site":         site,
        "date":         headers.get("UTCDate", headers.get("Date", "")),
        "white":        headers.get("White", ""),
        "black":        headers.get("Black", ""),
        "result":       headers.get("Result", ""),
        "white_elo":    safe_int(headers.get("WhiteElo")),
        "black_elo":    safe_int(headers.get("BlackElo")),
        "white_rd":     safe_float(headers.get("WhiteRatingDiff")),
        "black_rd":     safe_float(headers.get("BlackRatingDiff")),
        "eco":          headers.get("ECO", ""),
        "opening":      headers.get("Opening", ""),
        "time_control": headers.get("TimeControl", ""),
        "termination":  headers.get("Termination", ""),
        "num_moves":    num_moves,
        "moves_uci":    " ".join(moves_uci),
        "clock_times":  " ".join(clock_times) if clock_times else "",
    }


# ─────────────────────────────────────────────
# WORKER FOLYAMAT
# ─────────────────────────────────────────────
def worker_process(
    task_queue: Queue,
    result_queue: Queue,
    worker_id: int,
    output_dir: str
):
    """
    Játszma batch-eket dolgoz fel és Parquet partíciókat ír.
    task_queue-ból kap listákat (chess.pgn.Game raw strings vagy dicts),
    result_queue-ba jelenti a feldolgozott darabszámot.
    """
    partition_idx = 0
    while True:
        batch = task_queue.get()
        if batch is None:  # Leállítás jel
            break

        start_idx, games = batch
        rows = [extract_game_row(g, start_idx + i) for i, g in enumerate(games)]
        if not rows:
            continue

        # Parquet írás
        table = pa.table(
            {field.name: [r[field.name] for r in rows] for field in SCHEMA},
            schema=SCHEMA
        )
        out_path = os.path.join(output_dir, f"part_{worker_id:03d}_{partition_idx:06d}.parquet")
        pq.write_table(table, out_path, compression="snappy")
        partition_idx += 1
        result_queue.put(len(rows))


# ─────────────────────────────────────────────
# OLVASÓ (FŐFOLYAMAT)
# ─────────────────────────────────────────────
def read_and_distribute(
    pgn_path: str,
    task_queues: List[Queue],
    chunk_size: int,
    max_games: int
):
    """
    Beolvassa a PGN-t és elosztja a játszmákat a workerek között.
    Round-robin elosztással egyensúlyozza a terhelést.
    """
    n_workers = len(task_queues)
    batch: List[chess.pgn.Game] = []
    total = 0
    batch_start = 0
    worker_idx = 0

    with open(pgn_path, encoding="utf-8", errors="replace") as pgn_file:
        while True:
            game = chess.pgn.read_game(pgn_file)
            if game is None:
                break

            batch.append(game)
            total += 1

            if len(batch) >= chunk_size:
                task_queues[worker_idx].put((batch_start, batch))
                batch_start += len(batch)
                batch = []
                worker_idx = (worker_idx + 1) % n_workers

            if max_games > 0 and total >= max_games:
                break

    # Maradék batch
    if batch:
        task_queues[worker_idx].put((batch_start, batch))

    # Leállítás jelek
    for q in task_queues:
        q.put(None)


# ─────────────────────────────────────────────
# PARTÍCIÓK EGYESÍTÉSE
# ─────────────────────────────────────────────
def merge_partitions(parquet_dir: str, output_path: str):
    """Összes Parquet partíciót egyetlen, game_id szerint rendezett fájlba egyesíti."""
    part_files = [
        os.path.join(parquet_dir, f)
        for f in os.listdir(parquet_dir)
        if f.startswith("part_") and f.endswith(".parquet")
    ]

    if not part_files:
        print("⚠️  Nem találtam partíció fájlokat!")
        return

    # Rendezés az első game_id alapján (numerikus sorrend)
    def first_game_id(path):
        tbl = pq.read_table(path, columns=["game_id"])
        return tbl.column("game_id")[0].as_py()

    part_files = sorted(part_files, key=first_game_id)

    print(f"\n🔗 {len(part_files)} partíció egyesítése → {output_path}")
    writer = None
    total_rows = 0

    for pf in tqdm(part_files, desc="Merge", unit="part"):
        tbl = pq.read_table(pf)
        total_rows += len(tbl)
        if writer is None:
            writer = pq.ParquetWriter(output_path, tbl.schema, compression="snappy")
        writer.write_table(tbl)

    if writer:
        writer.close()

    # Partíciók törlése
    for pf in part_files:
        os.remove(pf)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"✅ Kész! {total_rows:,} sor → {output_path} ({size_mb:.1f} MB)")


# ─────────────────────────────────────────────
# FŐ BELÉPÉSI PONT
# ─────────────────────────────────────────────
def convert_pgn_to_parquet(
    pgn_path: str,
    output_parquet: str,
    n_workers: int = config.WORKERS,
    chunk_size: int = config.CHUNK_SIZE,
    max_games: int = config.MAX_GAMES
):
    """
    Teljes konverziós folyamat.

    Args:
        pgn_path:       Bemeneti PGN fájl elérési útja
        output_parquet: Kimeneti Parquet fájl elérési útja
        n_workers:      Párhuzamos feldolgozók száma
        chunk_size:     Egy batch mérete játszmában
        max_games:      Maximum játszmák (0 = összes)
    """
    if not os.path.exists(pgn_path):
        raise FileNotFoundError(f"PGN fájl nem található: {pgn_path}")

    pgn_size_gb = os.path.getsize(pgn_path) / 1024**3
    print(f"\n♟️  Lichess PGN → Parquet konverzió")
    print(f"   Bemeneti fájl:  {pgn_path} ({pgn_size_gb:.2f} GB)")
    print(f"   Kimenet:        {output_parquet}")
    print(f"   Workerek:       {n_workers}")
    print(f"   Chunk méret:    {chunk_size:,}")
    if max_games > 0:
        print(f"   Max játszmák:   {max_games:,}")
    print()

    # Ideiglenes partíció könyvtár
    part_dir = os.path.dirname(output_parquet)
    os.makedirs(part_dir, exist_ok=True)

    # Sorák és eredmény-sor létrehozása
    task_queues = [Queue(maxsize=4) for _ in range(n_workers)]
    result_queue = Queue()

    # Workerek indítása
    workers = []
    for i in range(n_workers):
        p = Process(
            target=worker_process,
            args=(task_queues[i], result_queue, i, part_dir),
            daemon=True
        )
        p.start()
        workers.append(p)

    # Progress bar
    pbar = tqdm(desc="Játszmák feldolgozva", unit="game", unit_scale=True)
    start_time = time.time()

    # Olvasás egy külön thread-ben (hogy a progress bar frissüljön)
    import threading
    reader_thread = threading.Thread(
        target=read_and_distribute,
        args=(pgn_path, task_queues, chunk_size, max_games),
        daemon=True
    )
    reader_thread.start()

    # Progress figyelés
    finished_workers = 0
    total_processed = 0
    while finished_workers < n_workers or not result_queue.empty():
        try:
            count = result_queue.get(timeout=0.5)
            total_processed += count
            pbar.update(count)
        except Exception:
            pass
        # Ellenőrzés: befejeztek-e a workerek
        finished_workers = sum(1 for w in workers if not w.is_alive())
        if finished_workers == n_workers:
            # Ürítjük a maradék eredményeket
            while not result_queue.empty():
                count = result_queue.get_nowait()
                total_processed += count
                pbar.update(count)
            break

    pbar.close()
    reader_thread.join()
    for w in workers:
        w.join()

    elapsed = time.time() - start_time
    rate = total_processed / elapsed if elapsed > 0 else 0
    print(f"\n⏱️  Feldolgozási idő: {elapsed:.1f}s ({rate:,.0f} játszma/s)")

    # Partíciók egyesítése
    merge_partitions(part_dir, output_parquet)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Nagy PGN fájl konvertálása Apache Parquet formátumba."
    )
    parser.add_argument(
        "--pgn",
        default=config.PGN_FILE,
        help=f"Bemeneti PGN fájl (alapértelmezett: {config.PGN_FILE})"
    )
    parser.add_argument(
        "--output",
        default=config.GAMES_PARQUET,
        help=f"Kimeneti Parquet fájl (alapértelmezett: {config.GAMES_PARQUET})"
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
        help="Maximum játszmák száma (0 = összes)"
    )
    args = parser.parse_args()

    convert_pgn_to_parquet(
        pgn_path=args.pgn,
        output_parquet=args.output,
        n_workers=args.workers,
        chunk_size=args.chunk_size,
        max_games=args.max_games
    )
