# -*- coding: utf-8 -*-
"""
streamlit_app.py – Sakk narráció lejátszó + egyedi PGN pipeline.

Indítás:
    streamlit run streamlit_app.py
"""

import os
import sys
import io
import json
import glob
import base64
import threading
import time
import shutil
import traceback

import streamlit as st
import chess
import chess.svg
import chess.pgn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from src.llm_client import generate_text
from src.tts_client import generate_audio

CUSTOM_GAME_STEM    = "sajat_jatszma"
CUSTOM_GAME_DISPLAY = "Saját játszmám"

# ─────────────────────────────────────────────────────────────────────────────
# Adatbetöltés
# ─────────────────────────────────────────────────────────────────────────────

def find_games() -> list[dict]:
    """JSON + MP3 párokat keres; csak azokat adja vissza, ahol mindkettő megvan."""
    json_files = glob.glob(os.path.join(config.LLM_ANALYSIS_JSON_DIR, "*.json"))
    games = []
    for jf in sorted(json_files, key=os.path.getmtime, reverse=True):
        stem = os.path.splitext(os.path.basename(jf))[0]
        mp3  = os.path.join(config.LLM_ANALYSIS_HANGOS_DIR, stem + ".mp3")
        if os.path.exists(mp3):
            display = CUSTOM_GAME_DISPLAY if stem == CUSTOM_GAME_STEM else stem
            games.append({"name": display, "stem": stem, "json": jf, "mp3": mp3})
    return games


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def audio_b64(mp3_path: str) -> str:
    with open(mp3_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# ─────────────────────────────────────────────────────────────────────────────
# SVG generálás
# ─────────────────────────────────────────────────────────────────────────────

def fen_to_svg(fen: str, size: int = 440) -> str:
    try:
        board = chess.Board(fen)
    except Exception:
        board = chess.Board()
    return chess.svg.board(board, size=size)


def starting_svg(size: int = 440) -> str:
    return chess.svg.board(chess.Board(), size=size)

# ─────────────────────────────────────────────────────────────────────────────
# FEN-sorozat és anchor-időzítés
# ─────────────────────────────────────────────────────────────────────────────

def fen_position_key(fen: str) -> str:
    return " ".join(fen.strip().split()[:4])


def get_all_fens(narration_data: dict, paragraphs: list) -> list[str]:
    if narration_data.get("moves"):
        fens = [chess.STARTING_FEN]
        for m in narration_data["moves"]:
            if m.get("fen"):
                fens.append(m["fen"])
        return fens

    seen = {fen_position_key(chess.STARTING_FEN)}
    fens = [chess.STARTING_FEN]
    for para in paragraphs:
        for anchor in para.get("anchors", []):
            f = anchor.get("fen", "")
            if f:
                k = fen_position_key(f)
                if k not in seen:
                    fens.append(f)
                    seen.add(k)
    return fens


def compute_timed_anchors(paragraphs: list, all_fens: list) -> list[dict]:
    fen_idx_map = {fen_position_key(f): i for i, f in enumerate(all_fens)}

    full_text = ""
    raw       = []

    for para in paragraphs:
        text = para.get("text", "")
        for anchor in para.get("anchors", []):
            trigger = anchor.get("trigger_word", "")
            fen     = anchor.get("fen", "")
            if not trigger or not fen:
                continue
            pos = text.find(trigger)
            if pos < 0:
                continue

            word_pos = len((full_text + text[:pos]).split())
            fen_idx  = fen_idx_map.get(fen_position_key(fen), -1)
            if fen_idx >= 0:
                raw.append({"fen_idx": fen_idx, "word_pos": word_pos})

        full_text += text + "  "

    total_words = max(len(full_text.split()), 1)
    for a in raw:
        a["word_frac"] = round(a["word_pos"] / total_words, 6)

    raw.sort(key=lambda x: x["word_frac"])

    seen: set[int] = set()
    result = []
    max_fen_idx = -1
    for a in raw:
        # csak előre haladhatunk: kisebb vagy azonos fen_idx-et kihagyjuk
        if a["fen_idx"] not in seen and a["fen_idx"] > max_fen_idx:
            seen.add(a["fen_idx"])
            result.append({"fen_idx": a["fen_idx"], "word_frac": a["word_frac"]})
            max_fen_idx = a["fen_idx"]

    return result

# ─────────────────────────────────────────────────────────────────────────────
# HTML lejátszó komponens
# ─────────────────────────────────────────────────────────────────────────────

def build_player_html(
    paragraphs: list,
    mp3_path: str,
    narration_data: dict | None = None,
    autoplay: bool = True,
) -> str:
    narration_data = narration_data or {}

    all_fens      = get_all_fens(narration_data, paragraphs)
    timed_anchors = compute_timed_anchors(paragraphs, all_fens)

    svgs       = [fen_to_svg(f) for f in all_fens]
    total_fens = len(svgs)

    svgs_json  = json.dumps(svgs)
    js_anchors = json.dumps([
        {"fenIdx": a["fen_idx"], "wordFrac": a["word_frac"]}
        for a in timed_anchors
    ])

    mp3_data       = audio_b64(mp3_path)
    autoplay_attr  = "autoplay" if autoplay else ""
    init_svg       = svgs[0] if svgs else starting_svg()

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{
    margin: 0; padding: 0;
    background: transparent;
    display: flex;
    flex-direction: column;
    align-items: center;
    font-family: sans-serif;
  }}
  #board-wrapper {{
    position: relative;
    width: min(calc(100vw - 8px), calc(100vh - 50px));
  }}
  #board-sizer {{
    display: block;
    visibility: hidden;
    pointer-events: none;
  }}
  #board-sizer svg, #board-a svg, #board-b svg {{
    width: 100%; height: auto; display: block;
  }}
  #board-a, #board-b {{
    position: absolute;
    inset: 0;
  }}
  #info {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: min(calc(100vw - 8px), calc(100vh - 50px));
    margin-top: 6px;
    font-size: 13px;
    color: #555;
  }}
  #lepesszam {{
    font-variant-numeric: tabular-nums;
    opacity: 0.65;
  }}
</style>
</head>
<body>

<div id="board-wrapper">
  <div id="board-sizer">{init_svg}</div>
  <div id="board-a" style="z-index:2;">{init_svg}</div>
  <div id="board-b" style="z-index:1;"></div>
</div>
<div id="info">
  <span id="statusz">&#9654; Betöltés…</span>
  <span id="lepesszam">Kezdőállás</span>
</div>

<audio id="narr" {autoplay_attr}
       src="data:audio/mpeg;base64,{mp3_data}"
       style="display:none"></audio>

<script>
const fenSvgs   = {svgs_json};
const anchors   = {js_anchors};
const TOTAL     = fenSvgs.length;
const LOOKAHEAD = 0.5;

const audio     = document.getElementById('narr');
const statusz   = document.getElementById('statusz');
const lepesszam = document.getElementById('lepesszam');

let lastIdx    = 0;
let targetIdx  = 0;
let rafQueued  = false;
let befejezett = false;
let front      = 'a';
let fadeTimer  = null;

function lepesFelirat(idx) {{
  if (idx === 0) return 'Kezdőállás';
  return idx + '. lépés / ' + (TOTAL - 1);
}}

function getFenIdx(frac) {{
  frac = Math.max(0, Math.min(1, frac));

  if (!anchors.length) {{
    return Math.min(Math.floor(frac * TOTAL), TOTAL - 1);
  }}

  if (frac <= anchors[0].wordFrac) {{
    const r = anchors[0].wordFrac > 0 ? frac / anchors[0].wordFrac : 0;
    return Math.round(r * anchors[0].fenIdx);
  }}

  const last = anchors[anchors.length - 1];
  if (frac >= last.wordFrac) {{
    const rem = 1 - last.wordFrac;
    const r   = rem > 0 ? (frac - last.wordFrac) / rem : 1;
    return Math.min(last.fenIdx + Math.round(r * (TOTAL - 1 - last.fenIdx)), TOTAL - 1);
  }}

  for (let i = 0; i < anchors.length - 1; i++) {{
    const a = anchors[i], b = anchors[i + 1];
    if (frac >= a.wordFrac && frac < b.wordFrac) {{
      const r = (frac - a.wordFrac) / (b.wordFrac - a.wordFrac);
      return Math.round(a.fenIdx + r * (b.fenIdx - a.fenIdx));
    }}
  }}

  return TOTAL - 1;
}}

function mutatFen(idx) {{
  // a tábla csak előre haladhat – soha ne menjünk vissza egy korábbi álláshoz
  idx = Math.max(lastIdx, Math.min(idx, TOTAL - 1));
  targetIdx = idx;
  if (!rafQueued && idx !== lastIdx) {{
    rafQueued = true;
    requestAnimationFrame(() => {{
      rafQueued = false;
      if (targetIdx === lastIdx) return;
      lastIdx = targetIdx;

      const frontEl = document.getElementById('board-' + front);
      const backId  = front === 'a' ? 'b' : 'a';
      const backEl  = document.getElementById('board-' + backId);

      if (fadeTimer) {{ clearTimeout(fadeTimer); fadeTimer = null; }}

      backEl.innerHTML        = fenSvgs[lastIdx];
      backEl.style.zIndex     = '2';
      frontEl.style.zIndex    = '1';
      backEl.style.transition = 'none';
      backEl.style.opacity    = '0';
      void backEl.offsetWidth;
      backEl.style.transition = 'opacity 0.22s ease-out';
      backEl.style.opacity    = '1';

      fadeTimer = setTimeout(() => {{
        fadeTimer = null;
        front = backId;
      }}, 240);

      lepesszam.textContent = lepesFelirat(lastIdx);
    }});
  }}
}}

audio.addEventListener('loadedmetadata', () => {{
  statusz.textContent = '► Narráció lejátszása…';
  audio.play().catch(() => {{
    statusz.textContent = '► Kattintson a lejátszáshoz!';
  }});
}});

audio.addEventListener('timeupdate', () => {{
  if (befejezett || !audio.duration) return;
  const frac = (audio.currentTime + LOOKAHEAD) / audio.duration;
  mutatFen(getFenIdx(frac));
}});

audio.addEventListener('ended', () => {{
  befejezett = true;
  mutatFen(TOTAL - 1);
  statusz.textContent = '⏸ Végállás – még látható…';
  setTimeout(() => {{
    statusz.textContent = '✓ Lejátszás befejezve.';
  }}, 3000);
}});

audio.addEventListener('error', () => {{
  statusz.textContent = '⚠ A hangfájl nem töltődött be.';
}});
</script>
</body>
</html>"""
    return html

# ─────────────────────────────────────────────────────────────────────────────
# LLM narráció rendszer-prompt (notebook-ból átvéve)
# ─────────────────────────────────────────────────────────────────────────────

NARRATION_SYSTEM_PROMPT = """\
Te egy szenvedélyes magyar sakkkommentátor vagy, aki élő közvetítésben magyaráz.
Lépésenkénti Stockfish-elemzést kapsz JSON formátumban – minden lépésnél megkapod
a FEN-t (az állás a lépés után) és a centipawn (cp) értéket.

## Stílus – ez a legfontosabb:
Úgy írj, mintha élőben kommentálnál: lelkesen, természetes magyar mondatokkal,
nem tankönyvszerűen. Kerüld az ilyen monoton sémákat:
  ✗ "Fehér az X. lépésben Y-t lépett, amely Z-t biztosít."
  ✓ "Fehér most Y-ra húzza a figurát – ez azonnal megnyitja a lehetőséget Z-re."

Mondatszerkezet:
- Váltogasd a rövid, ütős mondatokat a hosszabb magyarázókkal.
- Használj aktív igéket: "beveti", "visszavonul", "lecsap", "megnyitja az utat".
- Magyar kötőszavak, amelyek élővé teszik a szöveget: ám, hiszen, eközben,
  ekkor, persze, csakhogy, mindez, ráadásul, no de, és mégis.
- Szabad az értékelő kommentár: "Ez súlyos tévedés.", "Kitűnő döntés!", "Meglepő húzás."

## Magyar sakkszakkifejezések – KIZÁRÓLAG ezeket használd:
- megnyitás: a játszma első ~10 lépése; cél a figurák fejlesztése, centrum ellenőrzése, sáncolás
- centrum: az e4, d4, e5, d5 mezők összessége – aki uralja, az irányítja a játékot
- fejlesztés: figurák kiindulási mezőről aktív pozícióba való mozgatása a megnyitásban
- sáncolás: a király biztonságba helyezése (rövid sánc: királyszárny; hosszú sánc: vezérszárny)
- villa: egy figura egyszerre két ellenséges figurát támad
- nyársalás: értékes figurát megtámadva mögötte lévő gyengébbet nyeri meg
- stratégiai előny: hosszú távú pozicionális fölény (gyenge mező, tornyok nyílt vonalon)
- döntő lépés / fordulópont: ahol a cp érték legalább 150-et változik egy lépésen belül
- mattfenyegetés: közvetlen mattot kilátásba helyező lépés vagy lépéssorozat

## A Stockfish cp-értékek értelmezése (fehér nézőpontjából, pozitív = fehér előny):
- |cp| < 50:   kiegyenlített állás
- 50–150:      enyhe előny
- 150–300:     jelentős előny
- > 300:       döntő fölény
- mate != null: mattfenyegetés

## Kötelező lépésjelölés (TTS miatt – soha ne írj algebrai jelölést):
- Nxe5   → huszár üti e5-öt
- Rxh7   → bástya üti h7-et
- Bxf6   → futó üti f6-ot
- Qd8+   → vezér d8-ra, sakk
- O-O    → rövid sánc
- O-O-O  → hosszú sánc
- e4     → gyalog e4-re
- exd5   → gyalog üti d5-öt

## A narráció szerkezete – PONTOSAN 3 bekezdés:
1. Megnyitás és fejlesztés (1–10. lépés): nevezd meg az ECO-kód alapján a megnyitást,
   értékeld a figurák fejlesztését és a centrumharcot.
2. Középjáték és fordulópont: azonosítsd azt a lépést, ahol a cp a legnagyobb ugrást mutatja
   (legalább 150 cp); ezt nevezd fordulópontnak és magyarázd el miért volt döntő.
3. Összefoglalás és tanulság: mi volt a vesztes fél fő hibája? Milyen általános sakkelvvel függ össze?

## KRITIKUS – trigger_word szabályok (a vizuális szinkronizáció ettől függ!):

1. **Szó szerinti egyezés**: a trigger_word PONTOSAN UGYANAZ a szövegrész, amely a "text" mezőben
   szerepel – COPY-PASTE, soha nem parafrazálás, soha nem rövidítés, soha nem értelmezés!
   Egyetlen betűnyi eltérés (ékezet, nagy/kisbetű) is megakadályozza a szinkronizációt.

2. **Hossz**: legalább 4, legfeljebb 8 szó. Rövidebb nem egyedi, hosszabb felesleges.

3. **Egyediség**: a trigger_word ne forduljon elő kétszer a teljes narráción belül.
   Ha egy kifejezés megismétlődne, adj hozzá környező szavakat, hogy egyedi legyen.

4. **Pontos helyzet**: a trigger_word AZT a szövegrészt jelölje, ahol az adott lépést
   AKTÍVAN BEVEZETED – a legelső mondat, amelyben a lépést megemlíted.

5. **Sorrend**: az anchors tömbben a trigger_word-ök UGYANOLYAN SORRENDBEN kövessék egymást,
   ahogy a "text" mezőben megjelennek (felülről lefelé haladva).

6. **Teljesség**: minden bekezdésbe kerüljön anchor MINDEN EGYES konkrétan említett lépésnél.

## Kimenet – KIZÁRÓLAG valid JSON, se bevezető szöveg, se markdown kódblokk:
{
  "paragraphs": [
    {
      "text": "Bekezdés szövege – természetes, élő kommentátor stílusban.",
      "anchors": [
        {"fen": "<FEN az adott lépés után>", "trigger_word": "<szó szerinti idézet a text-ből>"}
      ]
    }
  ]
}
"""

# ─────────────────────────────────────────────────────────────────────────────
# Egyedi PGN pipeline – segédfüggvények
# ─────────────────────────────────────────────────────────────────────────────

def _find_stockfish() -> str | None:
    if config.STOCKFISH_PATH and os.path.isfile(config.STOCKFISH_PATH):
        return config.STOCKFISH_PATH
    for name in ["stockfish", "stockfish_x86-64", "stockfish-windows-x86-64-avx2"]:
        path = shutil.which(name)
        if path:
            return path
    candidates = [
        os.path.join(config.ROOT_DIR, "stockfish", "stockfish-windows-x86-64-avx2.exe"),
        os.path.join(config.ROOT_DIR, "stockfish", "stockfish.exe"),
        config.STOCKFISH_BINARY,
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _parse_pgn(pgn_text: str) -> dict:
    game = chess.pgn.read_game(io.StringIO(pgn_text.strip()))
    if game is None:
        raise ValueError("Nem sikerült értelmezni a PGN-t! Ellenőrizd a formátumot.")
    moves_uci = []
    board = game.board()
    for move in game.mainline_moves():
        moves_uci.append(move.uci())
        board.push(move)
    if not moves_uci:
        raise ValueError("Nem találtam lépéseket a PGN-ben!")
    headers = dict(game.headers)
    return {
        "white":     headers.get("White", "Fehér"),
        "black":     headers.get("Black", "Fekete"),
        "white_elo": headers.get("WhiteElo", "?"),
        "black_elo": headers.get("BlackElo", "?"),
        "eco":       headers.get("ECO", "?"),
        "opening":   headers.get("Opening", ""),
        "result":    headers.get("Result", "*"),
        "moves_uci": moves_uci,
    }


def _stockfish_analyze(moves_uci: list, progress: dict, sf_path: str) -> list:
    """Közvetlen UCI subprocess – asyncio-mentes, háttérszálból is működik Windows-on."""
    import subprocess

    proc = subprocess.Popen(
        [sf_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    def send(cmd: str) -> None:
        proc.stdin.write(cmd + "\n")
        proc.stdin.flush()

    def expect(prefix: str) -> str:
        while True:
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("Stockfish váratlanul leállt!")
            if line.startswith(prefix):
                return line.rstrip()

    try:
        send("uci")
        expect("uciok")
        send("isready")
        expect("readyok")

        board = chess.Board()
        evals = []
        total = min(len(moves_uci), config.STOCKFISH_MOVES_LIMIT)

        for i, uci in enumerate(moves_uci[:total]):
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                break
            san = board.san(move)
            board.push(move)
            fen           = board.fen()
            side_to_move  = board.turn  # kinek a köre a lépés UTÁN

            send(f"position fen {fen}")
            send("go depth 12")

            cp_white  = None
            mate_val  = None
            last_info = ""

            while True:
                line = proc.stdout.readline().rstrip()
                if "score" in line and line.startswith("info"):
                    last_info = line
                elif line.startswith("bestmove"):
                    break

            if last_info:
                parts = last_info.split()
                try:
                    si    = parts.index("score")
                    stype = parts[si + 1]
                    sval  = int(parts[si + 2])
                    # Stockfish score a soron lévő játékos szemszögéből → fehér perspektíva
                    sign  = 1 if side_to_move == chess.WHITE else -1
                    if stype == "cp":
                        cp_white = sign * sval
                    elif stype == "mate":
                        mate_val = sign * sval
                except (ValueError, IndexError):
                    pass

            evals.append({
                "move_number": (i // 2) + 1,
                "color":       "white" if i % 2 == 0 else "black",
                "uci":         uci,
                "san":         san,
                "cp":          cp_white,
                "mate":        mate_val,
                "fen":         fen,
            })
            progress["pct"]  = 0.10 + 0.50 * (i + 1) / total
            progress["step"] = f"Stockfish elemzés: {i + 1}/{total} lépés..."

    finally:
        try:
            send("quit")
            proc.wait(timeout=3)
        except Exception:
            proc.kill()

    return evals


def _generate_narration(game_data: dict, evaluations: list) -> dict:
    user_prompt = (
        f"ECO: {game_data.get('eco', '?')} – {game_data.get('opening', '')}\n"
        f"Fehér: {game_data['white']} ({game_data['white_elo']}), "
        f"Fekete: {game_data['black']} ({game_data['black_elo']})\n"
        f"Eredmény: {game_data['result']}\n\n"
        "Elemzendő lépések (JSON):\n"
        + json.dumps(evaluations, ensure_ascii=False, indent=2)
    )
    raw = generate_text(user_prompt, system_prompt=NARRATION_SYSTEM_PROMPT)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    return json.loads(raw)


def run_custom_pipeline(pgn_text: str, progress: dict) -> None:
    """Teljes pipeline futtatása egyedi PGN-re (háttérszálon hívva)."""
    try:
        progress.update({"step": "PGN értelmezése...", "pct": 0.02})
        game_data = _parse_pgn(pgn_text)

        progress.update({"step": "Stockfish keresése...", "pct": 0.07})
        sf_path = _find_stockfish()
        if not sf_path:
            raise RuntimeError(
                "Stockfish nem található! Telepítsd, vagy add meg az elérési utat config.py-ban."
            )

        progress.update({"step": "Stockfish elemzés indítása...", "pct": 0.10})
        evaluations = _stockfish_analyze(game_data["moves_uci"], progress, sf_path)

        moves_for_json = (
            [{"move_number": 0, "color": "start", "san": "", "fen": chess.STARTING_FEN}]
            + [{"move_number": e["move_number"], "color": e["color"],
                "san": e["san"], "fen": e["fen"]}
               for e in evaluations]
        )

        progress.update({
            "step": "LLM narráció generálása (API hívás, néhány másodperc)...",
            "pct":  0.62,
        })
        narration_json = _generate_narration(game_data, evaluations)
        narration_json["moves"] = moves_for_json

        progress.update({"step": "Narráció JSON mentése...", "pct": 0.78})
        json_path = os.path.join(config.LLM_ANALYSIS_JSON_DIR, f"{CUSTOM_GAME_STEM}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(narration_json, f, ensure_ascii=False, indent=2)

        progress.update({
            "step": "Hangfájl generálása TTS-sel (1-2 perc)...",
            "pct":  0.82,
        })
        tts_text = "\n\n".join(p["text"] for p in narration_json.get("paragraphs", []))
        mp3_path = os.path.join(config.LLM_ANALYSIS_HANGOS_DIR, f"{CUSTOM_GAME_STEM}.mp3")
        generate_audio(tts_text, mp3_path)

        progress.update({
            "step": "✅ Kész! Válaszd ki a \"Saját játszmám\" opciót és nyomj Lejátszást!",
            "pct":  1.0,
            "done": True,
        })

    except Exception as exc:
        tb = traceback.format_exc()
        err_msg = str(exc) or type(exc).__name__
        progress.update({
            "step":      f"❌ Hiba a(z) »{progress.get('step', '?')}« lépésnél: {err_msg}",
            "pct":       progress.get("pct", 0.0),
            "done":      True,
            "has_error": True,
            "traceback": tb,
        })

# ─────────────────────────────────────────────────────────────────────────────
# Streamlit alkalmazás
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Sakk narráció",
    page_icon="♟️",
    layout="wide",
)

st.markdown("""
<style>
  div[data-testid="stVerticalBlock"] > div { gap: 0.5rem; }
  .stButton button {
    width: 100%;
    font-size: 1.1rem;
    padding: 0.6rem 0;
    border-radius: 8px;
  }
  .pipeline-status {
    font-size: 1rem;
    line-height: 1.5;
    color: #333;
    margin-top: 0.3rem;
  }
</style>
""", unsafe_allow_html=True)

st.title("♟️ Sakk narráció")

# ── Session state ─────────────────────────────────────────────────────────────

if "playing" not in st.session_state:
    st.session_state.playing = False
if "last_game" not in st.session_state:
    st.session_state.last_game = None
if "pipeline_progress" not in st.session_state:
    st.session_state.pipeline_progress = None
if "pipeline_thread" not in st.session_state:
    st.session_state.pipeline_thread = None

# ── Játékok betöltése ─────────────────────────────────────────────────────────

games      = find_games()
game_names = [g["name"] for g in games]
game_map   = {g["name"]: g for g in games}

pipeline_is_running = (
    st.session_state.pipeline_thread is not None
    and st.session_state.pipeline_thread.is_alive()
)

# ── LEJÁTSZÓ MÓD ─────────────────────────────────────────────────────────────

if st.session_state.playing:
    selected = game_map.get(st.session_state.last_game)
    if selected is None:
        st.session_state.playing = False
        st.rerun()

    narration_data = load_json(selected["json"])
    paragraphs     = narration_data.get("paragraphs", [])
    player_html    = build_player_html(
        paragraphs, selected["mp3"],
        narration_data=narration_data,
        autoplay=True,
    )
    st.components.v1.html(player_html, height=620, scrolling=False)

    if st.button("⏹  Megállít", use_container_width=True):
        st.session_state.playing = False
        st.rerun()

# ── ÁLLÓ MÓD ─────────────────────────────────────────────────────────────────

else:
    col_pgn, col_board = st.columns([5, 7], gap="large")

    # ── Bal oszlop: PGN bevitel ───────────────────────────────────────────────
    with col_pgn:
        st.subheader("Saját játszmád elemzése")

        pgn_text = st.text_area(
            "Illeszd be a PGN-t:",
            height=310,
            key="pgn_input",
            placeholder=(
                '[Event "Live Chess"]\n'
                '[White "Fehér"]\n'
                '[Black "Fekete"]\n'
                '[Result "1-0"]\n\n'
                "1. e4 e5 2. Nf3 Nc6 3. Bb5 ..."
            ),
            help=(
                "Bármilyen standard PGN formátum elfogadott – "
                "fejléc nélkül, csak lépésekkel is működik."
            ),
        )

        if st.button(
            "Elemzés indítása!",
            disabled=pipeline_is_running,
            use_container_width=True,
            type="primary",
        ):
            if pgn_text.strip():
                progress = {
                    "step": "Indítás...",
                    "pct":  0.0,
                    "done": False,
                    "error": None,
                }
                st.session_state.pipeline_progress = progress
                t = threading.Thread(
                    target=run_custom_pipeline,
                    args=(pgn_text, progress),
                    daemon=True,
                )
                t.start()
                st.session_state.pipeline_thread = t
                st.rerun()
            else:
                st.warning("Kérlek illessz be egy PGN-t az elemzés megkezdéséhez!")

        # Folyamat jelzők
        prog = st.session_state.pipeline_progress
        if prog is not None:
            st.progress(prog.get("pct", 0.0))
            step      = prog.get("step", "")
            has_error = prog.get("has_error", False)
            done      = prog.get("done", False)
            if has_error:
                st.error(step)
                tb = prog.get("traceback", "")
                if tb:
                    with st.expander("Részletes hibaüzenet (fejlesztőknek)"):
                        st.code(tb, language="python")
            elif done and prog.get("pct", 0) >= 1.0:
                st.success(step)
            else:
                st.markdown(
                    f'<div class="pipeline-status">{step}</div>',
                    unsafe_allow_html=True,
                )

    # ── Jobb oszlop: játszmaválasztó + sakktábla ──────────────────────────────
    with col_board:
        if not games:
            st.info(
                "Még nincs lejátszható játszma. "
                "Futtasd le a `notebooks/jatek_elemzese.ipynb` notebookot, "
                "vagy elemezd a saját játszmádat a bal oldali panelen!"
            )
        else:
            selected_name = st.selectbox(
                "Válassz játszmát:",
                options=game_names,
                label_visibility="collapsed",
            )
            selected = game_map[selected_name]

            if st.session_state.last_game != selected_name:
                st.session_state.last_game = selected_name

            narration_data = load_json(selected["json"])
            paragraphs     = narration_data.get("paragraphs", [])
            all_fens       = get_all_fens(narration_data, paragraphs)
            init_fen       = all_fens[0] if all_fens else chess.STARTING_FEN
            svg            = fen_to_svg(init_fen)

            st.components.v1.html(
                f'<style>svg{{width:100%;height:auto;display:block}}</style>'
                f'<div style="width:100%;max-width:500px;margin:0 auto">{svg}</div>',
                height=520,
                scrolling=False,
            )

            if st.button("▶  Lejátszás", use_container_width=True):
                st.session_state.playing = True
                st.rerun()

    # ── Auto-refresh ha pipeline fut ─────────────────────────────────────────
    if pipeline_is_running:
        time.sleep(0.5)
        st.rerun()
