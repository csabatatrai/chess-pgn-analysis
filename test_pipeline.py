#!/usr/bin/env python3
"""
test_pipeline.py
────────────────
Tesztelő script: egy mini PGN fájlt hoz létre és lefuttatja
a teljes pipeline-t rajta, így azonnal ellenőrizhető hogy minden működik.

Futtatás:
  python test_pipeline.py
"""

import os
import sys
import json
import tempfile

# Projekt gyökér hozzáadása a PATH-hoz
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

SAMPLE_PGN = """\
[Event "Rated Blitz game"]
[Site "https://lichess.org/abcd1234"]
[Date "2024.01.15"]
[UTCDate "2024.01.15"]
[White "MagnusTest"]
[Black "HikaruTest"]
[Result "1-0"]
[WhiteElo "2800"]
[BlackElo "2750"]
[WhiteRatingDiff "+5"]
[BlackRatingDiff "-5"]
[ECO "B20"]
[Opening "Sicilian Defense"]
[TimeControl "180+2"]
[Termination "Normal"]

1. e4 { [%clk 0:03:02] } c5 { [%clk 0:03:02] } 2. Nf3 { [%clk 0:03:01] } d6 { [%clk 0:03:01] }
3. d4 { [%clk 0:03:00] } cxd4 { [%clk 0:03:00] } 4. Nxd4 { [%clk 0:02:59] } Nf6 { [%clk 0:02:59] }
5. Nc3 { [%clk 0:02:58] } a6 { [%clk 0:02:58] } 6. Be3 { [%clk 0:02:57] } e5 { [%clk 0:02:57] }
7. Nb3 { [%clk 0:02:56] } Be6 { [%clk 0:02:56] } 8. f3 { [%clk 0:02:55] } Be7 { [%clk 0:02:55] }
9. Qd2 { [%clk 0:02:54] } O-O { [%clk 0:02:54] } 10. O-O-O { [%clk 0:02:53] } Nbd7 { [%clk 0:02:53] }
11. g4 { [%clk 0:02:52] } b5 { [%clk 0:02:52] } 12. g5 { [%clk 0:02:51] } Nh5 { [%clk 0:02:51] }
13. Nd5 { [%clk 0:02:50] } Bxd5 { [%clk 0:02:50] } 14. exd5 { [%clk 0:02:49] } Nf4 { [%clk 0:02:49] }
15. Bxf4 { [%clk 0:02:48] } exf4 { [%clk 0:02:48] } 16. h4 { [%clk 0:02:47] } Nc5 { [%clk 0:02:47] }
17. Nxc5 { [%clk 0:02:46] } dxc5 { [%clk 0:02:46] } 18. h5 { [%clk 0:02:45] } b4 { [%clk 0:02:45] }
19. h6 { [%clk 0:02:44] } g6 { [%clk 0:02:44] } 20. Qxf4 { [%clk 0:02:43] } Qd6 { [%clk 0:02:43] }
21. Qh4 { [%clk 0:02:42] } Qe5 { [%clk 0:02:42] } 22. Bd3 { [%clk 0:02:41] } Rad8 { [%clk 0:02:41] }
23. Rhe1 { [%clk 0:02:40] } Qf4+ { [%clk 0:02:40] } 24. Kb1 { [%clk 0:02:39] } Rfe8 { [%clk 0:02:39] }
25. Re6 { [%clk 0:02:38] } Rxe6 { [%clk 0:02:38] } 26. dxe6 { [%clk 0:02:37] } fxe6 { [%clk 0:02:37] }
27. Bxg6 { [%clk 0:02:36] } hxg6 { [%clk 0:02:36] } 28. Qxe6+ { [%clk 0:02:35] } Kh7 { [%clk 0:02:35] }
29. Qf7+ { [%clk 0:02:34] } Kxh6 { [%clk 0:02:34] } 30. Qg8 { [%clk 0:02:33] } 1-0

[Event "Rated Rapid game"]
[Site "https://lichess.org/efgh5678"]
[Date "2024.01.15"]
[UTCDate "2024.01.15"]
[White "AlphaPlayer"]
[Black "BetaPlayer"]
[Result "0-1"]
[WhiteElo "1500"]
[BlackElo "1520"]
[WhiteRatingDiff "-8"]
[BlackRatingDiff "+8"]
[ECO "C50"]
[Opening "Italian Game"]
[TimeControl "600+0"]
[Termination "Normal"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d4 exd4 6. cxd4 Bb4+
7. Bd2 Bxd2+ 8. Nbxd2 d5 9. exd5 Nxd5 10. Qb3 Na5 11. Qa4+ Nc6
12. O-O O-O 13. Rfe1 Bg4 14. h3 Bh5 15. g4 Bg6 16. Ne5 Nxe5
17. dxe5 Nf4 18. Nf3 Qd3 19. Re3 Qxf3 0-1

[Event "Rated Bullet game"]
[Site "https://lichess.org/ijkl9012"]
[Date "2024.01.16"]
[UTCDate "2024.01.16"]
[White "SpeedRunner"]
[Black "QuickMover"]
[Result "1/2-1/2"]
[WhiteElo "2100"]
[BlackElo "2080"]
[WhiteRatingDiff "+0"]
[BlackRatingDiff "+0"]
[ECO "D00"]
[Opening "Queen's Pawn Game"]
[TimeControl "60+0"]
[Termination "Draw by repetition"]

1. d4 d5 2. Nf3 Nf6 3. Bf4 e6 4. e3 Bd6 5. Bg3 O-O 6. c4 c6
7. Nc3 Nbd7 8. cxd5 exd5 9. Bd3 Re8 10. O-O Nf8 11. Qc2 Ng6
12. Bxg6 hxg6 13. Ne5 Bxg3 14. hxg3 Qd6 15. f4 Ne4 16. Nxe4 dxe4
1/2-1/2

[Event "Rated Classical game"]
[Site "https://lichess.org/mnop3456"]
[Date "2024.01.17"]
[UTCDate "2024.01.17"]
[White "GrandMasterG"]
[Black "ExpertE"]
[Result "1-0"]
[WhiteElo "2600"]
[BlackElo "2450"]
[WhiteRatingDiff "+4"]
[BlackRatingDiff "-4"]
[ECO "E60"]
[Opening "King's Indian Defense"]
[TimeControl "1800+30"]
[Termination "Normal"]

1. d4 Nf6 2. c4 g6 3. Nf3 Bg7 4. g3 O-O 5. Bg2 d6 6. O-O Nc6
7. Nc3 a6 8. d5 Na5 9. Nd2 c5 10. Qc2 Rb8 11. b3 b5 12. cxb5 axb5
13. Bb2 b4 14. Nd1 Nd7 15. Nf1 Ne5 16. Ne3 f5 17. f4 Nf7 18. Nf3 Nd8
19. Nd2 Nf7 20. a3 bxa3 21. Rxa3 Bd7 22. Ra7 Qc8 23. Rfa1 Rb7 24. Rxb7 Qxb7
25. Ra7 Qb8 26. Ng2 Qb6 27. Bxg7 Kxg7 28. Nh4 gxh5 29. Nhxf5+ Bxf5 30. Nxf5+ Rxf5
31. exf5 e4 32. f6+ Kh8 33. Qxe4 Qxb3 34. Qe7 Qd1+ 35. Kf2 Qd4+ 36. Kg2 Qd2+
37. Kh3 Nxf6 38. Rxh7+ Nxh7 39. Qxh7# 1-0

[Event "Rated Blitz game"]
[Site "https://lichess.org/qrst7890"]
[Date "2024.01.17"]
[UTCDate "2024.01.17"]
[White "PatzerP"]
[Black "NoviceN"]
[Result "0-1"]
[WhiteElo "800"]
[BlackElo "850"]
[WhiteRatingDiff "-10"]
[BlackRatingDiff "+10"]
[ECO "A00"]
[Opening "Uncommon Opening"]
[TimeControl "300+3"]
[Termination "Time forfeit"]

1. a4 e5 2. h4 d5 3. a5 Nc6 4. Ra3 Nf6 5. Rh3 Bc5 6. b4 Bb6
7. c3 O-O 8. d3 Re8 9. Nd2 Nd4 10. cxd4 exd4 0-1
"""


def create_test_pgn(path: str):
    """Létrehozza a teszt PGN fájlt."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(SAMPLE_PGN)
    print(f"✅ Teszt PGN létrehozva: {path}")


def run_test():
    """Teljes pipeline tesztelése mini adatokkal."""
    print("\n" + "═"*60)
    print("  🧪 PIPELINE TESZT – mini PGN adatokon")
    print("═"*60)

    # 1. Teszt PGN létrehozása
    test_pgn = os.path.join(ROOT, "test_sample.pgn")
    create_test_pgn(test_pgn)

    # 2. Config módosítás tesztre
    import config
    config.PGN_FILE = test_pgn
    config.MAX_GAMES = 0
    config.WORKERS = 2
    config.CHUNK_SIZE = 10

    # 3. Lépés 1: PGN → Parquet
    print("\n── 1. LÉPÉS: PGN → Parquet ──")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pgn_to_parquet",
        os.path.join(ROOT, "src", "01_pgn_to_parquet.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod.convert_pgn_to_parquet(
        pgn_path=test_pgn,
        output_parquet=config.GAMES_PARQUET,
        n_workers=1,
        chunk_size=10,
        max_games=0
    )

    # 4. Lépés 2: Elemzés
    print("\n── 2. LÉPÉS: Elemzés ──")
    spec2 = importlib.util.spec_from_file_location(
        "analysis",
        os.path.join(ROOT, "src", "02_analysis.py")
    )
    mod2 = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mod2)
    stats = mod2.run_analysis(config.GAMES_PARQUET)

    print(f"\n📊 Eredmény ellenőrzés:")
    print(f"   Összes játszma: {stats.get('total_games', 0)}")
    print(f"   Megnyitók: {len(stats.get('top_openings', []))}")
    print(f"   Időkontrollok: {len(stats.get('time_controls', []))}")

    # 5. Lépés 3: Stockfish (opcionális)
    print("\n── 3. LÉPÉS: Stockfish (opcionális) ──")
    spec3 = importlib.util.spec_from_file_location(
        "sf_analysis",
        os.path.join(ROOT, "src", "03_stockfish_analysis.py")
    )
    mod3 = importlib.util.module_from_spec(spec3)
    spec3.loader.exec_module(mod3)
    mod3.run_stockfish_analysis()

    # Ellenőrzés
    print("\n── EREDMÉNY FÁJLOK ──")
    for label, path in [
        ("Parquet", config.GAMES_PARQUET),
        ("Stats JSON", config.STATS_JSON),
        ("Top Game JSON", config.TOP_GAME_JSON),
        ("Stockfish JSON", config.STOCKFISH_JSON),
    ]:
        exists = os.path.exists(path)
        size = os.path.getsize(path) / 1024 if exists else 0
        status = f"✅ {size:.1f} KB" if exists else "❌ hiányzik"
        print(f"   {label}: {status}")

    print("\n✅ Teszt sikeres!")
    print(f"\n📊 Vizualizáció indítása:")
    print(f"   jupyter notebook notebooks/visualization.ipynb")
    print()

    # Teszt PGN törlése
    if os.path.exists(test_pgn):
        os.remove(test_pgn)


if __name__ == "__main__":
    run_test()
