#!/usr/bin/env python3
"""
03_stockfish_analysis.py
────────────────────────
A pipeline 3. lépése: Stockfish motorral elemzi a legjobb ratingű játékosok játszmáját.

A top_game.json-ból olvassa be az UCI lépéseket, lépésenként értékeli a pozíciót,
és az eredményt stockfish_analysis.json-ba menti.

Futtatás:
  python src/03_stockfish_analysis.py
"""

import sys
import os
import json
import shutil
import tempfile
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

import chess
import chess.pgn
import chess.engine

# ─────────────────────────────────────────────
# STOCKFISH KERESÉS
# ─────────────────────────────────────────────

def stockfish_data_binary() -> str:
    """A projekt adatkatalogusában tárolt Windows Stockfish bináris elérési útja."""
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data", "stockfish")
    if os.name == "nt":
        return os.path.join(data_dir, "stockfish.exe")
    return os.path.join(data_dir, "stockfish")


def download_stockfish_windows(target_dir: str) -> str:
    """Letölti és kicsomagolja a Stockfish Windows binárist a célkönyvtárba."""
    os.makedirs(target_dir, exist_ok=True)
    print(f"  📥 Letöltés: {config.STOCKFISH_DOWNLOAD_URL_WINDOWS}")

    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = os.path.join(tmpdir, "stockfish.zip")
        urllib.request.urlretrieve(config.STOCKFISH_DOWNLOAD_URL_WINDOWS, archive_path)

        with zipfile.ZipFile(archive_path, "r") as zip_file:
            candidates = [name for name in zip_file.namelist() if os.path.basename(name).lower() == "stockfish.exe"]
            if not candidates:
                raise RuntimeError("A letöltött Stockfish ZIP nem tartalmaz stockfish.exe fájlt.")
            member = candidates[0]
            zip_file.extract(member, tmpdir)
            extracted_path = os.path.join(tmpdir, member)

        dest_path = os.path.join(target_dir, "stockfish.exe")
        shutil.move(extracted_path, dest_path)
        os.chmod(dest_path, 0o755)
        return dest_path


def find_stockfish() -> str:
    """Megkeresi a Stockfish binárist."""
    # 1. Konfig-ban megadott elérési út
    if config.STOCKFISH_PATH and os.path.isfile(config.STOCKFISH_PATH):
        return config.STOCKFISH_PATH

    # 2. PATH-ban keresés
    for name in ["stockfish", "stockfish_x86-64", "stockfish-windows-x86-64"]:
        path = shutil.which(name)
        if path:
            return path

    # 3. Root stockfish mappa vagy a data/stockfish telepített binárisa
    candidate_files = []
    if os.name == "nt":
        candidate_files.extend([
            os.path.join(os.path.dirname(__file__), "..", "stockfish", "stockfish.exe"),
            stockfish_data_binary(),
        ])
    else:
        candidate_files.extend([
            os.path.join(os.path.dirname(__file__), "..", "stockfish", "stockfish"),
            stockfish_data_binary(),
        ])

    for c in candidate_files:
        if os.path.isfile(c):
            return c

    if os.name == "nt":
        try:
            return download_stockfish_windows(os.path.dirname(stockfish_data_binary()))
        except Exception as exc:
            print(f"  ⚠️  Stockfish letöltése sikertelen: {exc}")

    return None


# ─────────────────────────────────────────────
# ELEMZÉSI LOGIKA
# ─────────────────────────────────────────────

def analyze_game_with_stockfish(
    moves_uci: str,
    white: str,
    black: str,
    depth: int = config.STOCKFISH_DEPTH,
    moves_limit: int = config.STOCKFISH_MOVES_LIMIT,
    stockfish_path: str = None
) -> dict:
    """
    Elemez egy játszmát Stockfish-sel.

    Args:
        moves_uci:      Szóközzel elválasztott UCI lépések
        white / black:  Játékosok neve
        depth:          Keresési mélység
        moves_limit:    Maximum elemzett lépések száma
        stockfish_path: Stockfish bináris elérési útja

    Returns:
        dict: Lépésenkénti értékelések, nyerési valószínűségek, hibák
    """
    sf_path = stockfish_path or find_stockfish()
    if not sf_path:
        raise RuntimeError(
            "Stockfish nem található!\n"
            "Telepítés: sudo apt install stockfish (Linux)\n"
            "Vagy adj meg elérési utat a config.py STOCKFISH_PATH változóban."
        )

    moves = moves_uci.strip().split()
    if not moves:
        raise ValueError("Üres lépéslista!")

    board = chess.Board()
    evaluations = []
    best_moves = []
    mistakes = []

    print(f"\n🔍 Stockfish elemzés: {white} vs {black}")
    print(f"   Mélység: {depth}, Lépések: min({len(moves)}, {moves_limit})")

    with chess.engine.SimpleEngine.popen_uci(sf_path) as engine:
        limit = chess.engine.Limit(depth=depth)

        for i, uci in enumerate(moves[:moves_limit]):
            try:
                move = chess.Move.from_uci(uci)
                if move not in board.legal_moves:
                    print(f"  ⚠️  Illegális lépés #{i+1}: {uci}")
                    break

                # Értékelés a lépés ELŐTT
                info_before = engine.analyse(board, limit)
                score_before = info_before["score"].white()
                eval_before = score_before.score(mate_score=10000)

                # Legjobb lépés
                best_move_info = info_before.get("pv", [None])[0]
                best_move_uci = best_move_info.uci() if best_move_info else uci

                # Lépés megtétele
                board.push(move)

                # Értékelés a lépés UTÁN
                info_after = engine.analyse(board, limit)
                score_after = info_after["score"].white()
                eval_after = score_after.score(mate_score=10000)

                # Centipawn veszteség (a lépő fél szemszögéből)
                if i % 2 == 0:  # Fehér lép
                    cp_loss = (eval_after or 0) - (eval_before or 0)
                    player = white
                else:            # Fekete lép
                    cp_loss = (eval_before or 0) - (eval_after or 0)
                    player = black

                # Nyerési valószínűség (logisztikus közelítés)
                def win_prob(cp):
                    if cp is None:
                        return 0.5
                    import math
                    return 1 / (1 + math.exp(-cp / 400))

                wp_before = win_prob(eval_before)
                wp_after = win_prob(eval_after)

                move_data = {
                    "move_num": i + 1,
                    "ply": i,
                    "player": player,
                    "uci": uci,
                    "best_uci": best_move_uci,
                    "eval_before": eval_before,
                    "eval_after": eval_after,
                    "cp_loss": abs(cp_loss) if cp_loss else 0,
                    "win_prob_before": round(wp_before, 4),
                    "win_prob_after": round(wp_after, 4),
                    "is_best": uci == best_move_uci,
                    "fen_before": board.fen() if i == 0 else evaluations[-1].get("fen_after", ""),
                    "fen_after": board.fen(),
                }

                # Hiba/blunder osztályozás
                if cp_loss and cp_loss < -50:
                    if cp_loss < -200:
                        move_data["quality"] = "blunder"
                    elif cp_loss < -100:
                        move_data["quality"] = "mistake"
                    else:
                        move_data["quality"] = "inaccuracy"
                    mistakes.append(move_data)
                else:
                    move_data["quality"] = "good" if uci == best_move_uci else "ok"

                evaluations.append(move_data)
                best_moves.append(best_move_uci)

                if (i + 1) % 10 == 0:
                    print(f"  ... {i+1}/{min(len(moves), moves_limit)} lépés kész")

            except Exception as e:
                print(f"  ⚠️  Hiba a {i+1}. lépésnél: {e}")
                break

    # Összesítő statisztikák
    total_analyzed = len(evaluations)
    mistakes_count = sum(1 for e in evaluations if e["quality"] in ("mistake", "blunder"))
    blunders_count = sum(1 for e in evaluations if e["quality"] == "blunder")

    summary = {
        "total_moves_analyzed": total_analyzed,
        "mistakes": mistakes_count,
        "blunders": blunders_count,
        "avg_cp_loss": round(
            sum(e["cp_loss"] for e in evaluations) / total_analyzed, 1
        ) if total_analyzed else 0,
    }

    result = {
        "white": white,
        "black": black,
        "depth": depth,
        "evaluations": evaluations,
        "summary": summary,
        "top_mistakes": sorted(
            [e for e in mistakes],
            key=lambda x: x.get("cp_loss", 0),
            reverse=True
        )[:5]
    }

    print(f"\n  📈 Elemzés kész: {total_analyzed} lépés")
    print(f"  ❌ Hibák: {mistakes_count}, Blunderek: {blunders_count}")
    print(f"  📉 Átlag centipawn veszteség: {summary['avg_cp_loss']}")

    return result


# ─────────────────────────────────────────────
# FŐ BELÉPÉSI PONT
# ─────────────────────────────────────────────

def run_stockfish_analysis():
    """Beolvassa a top_game.json-t és futtatja a Stockfish elemzést."""

    if not os.path.exists(config.TOP_GAME_JSON):
        print(f"⚠️  Top játszma fájl nem található: {config.TOP_GAME_JSON}")
        print("   Előbb futtasd: python src/02_analysis.py")
        return None

    with open(config.TOP_GAME_JSON, encoding="utf-8") as f:
        game_data = json.load(f)

    if not game_data:
        print("⚠️  Üres top játszma adatok.")
        return None

    white = game_data.get("white", "Fehér")
    black = game_data.get("black", "Fekete")
    moves_uci = game_data.get("moves_uci", "")
    white_elo = game_data.get("white_elo", 0)
    black_elo = game_data.get("black_elo", 0)

    print(f"\n♟️  Top játszma: {white} ({white_elo}) vs {black} ({black_elo})")
    print(f"   ECO: {game_data.get('eco', '?')} – {game_data.get('opening', '?')}")
    print(f"   Eredmény: {game_data.get('result', '?')}")

    sf_path = find_stockfish()
    if not sf_path:
        print("\n⚠️  Stockfish nem elérhető – az elemzés kihagyva.")
        print("   Telepítés: sudo apt install stockfish")
        print("   Vagy add meg a config.py STOCKFISH_PATH változóban.")

        # Létrehozunk egy placeholder fájlt a vizualizáció számára
        placeholder = {
            "white": white, "black": black,
            "error": "Stockfish nem elérhető",
            "evaluations": [], "summary": {}
        }
        with open(config.STOCKFISH_JSON, "w", encoding="utf-8") as f:
            json.dump(placeholder, f, indent=2)
        return None

    result = analyze_game_with_stockfish(
        moves_uci=moves_uci,
        white=white,
        black=black,
        stockfish_path=sf_path
    )

    # Játszma metaadatok hozzáadása
    result["game_meta"] = {
        "eco": game_data.get("eco", ""),
        "opening": game_data.get("opening", ""),
        "result": game_data.get("result", ""),
        "date": game_data.get("date", ""),
        "time_control": game_data.get("time_control", ""),
        "white_elo": white_elo,
        "black_elo": black_elo,
    }

    os.makedirs(config.ANALYSIS_DIR, exist_ok=True)
    with open(config.STOCKFISH_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n✅ Stockfish elemzés kész! → {config.STOCKFISH_JSON}")
    return result


if __name__ == "__main__":
    run_stockfish_analysis()
