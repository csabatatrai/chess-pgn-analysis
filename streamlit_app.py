# -*- coding: utf-8 -*-
"""
streamlit_app.py – Sakk narráció lejátszó + egyedi PGN pipeline.

Indítás:
    streamlit run streamlit_app.py
"""

import os
import sys
import io
import re
import json
import glob
import base64
import threading
import time
import shutil
import traceback

import streamlit as st
import streamlit.components.v1 as stc
import chess
import chess.svg
import chess.pgn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from src.llm_client import generate_text
from src.tts_client import generate_audio
from src.narrator import generate_narration

# Globális töltőkép – a document.body-ra kerül, Streamlit React-rootján kívül,
# ezért túléli a rerenderelést. Megjelenik a Play kattintáskor, eltűnik mikor
# a hang lejátszásra kész (chess-narr-started postMessage).
_OVERLAY_INJECTOR_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:transparent;">
<script>
(function(){
  try{
    var par=window.parent, doc=par.document;

    /* ── 1. postMessage hallgató (egyszer regisztrálva) ─────────────────── */
    if(!par._chNarrMsg){
      par._chNarrMsg=true;
      par.addEventListener('message',function(e){
        if(!e.data||e.data.type!=='chess-narr-started')return;
        var ol=doc.getElementById('chess-gl-ol');
        if(!ol)return;
        ol.style.transition='opacity 0.55s ease';
        ol.style.opacity='0';
        setTimeout(function(){
          ol.style.display='none';
          ol.style.opacity='1';
          ol.style.transition='';
        },580);
      });
    }

    /* ── 2. Overlay létrehozása (egyszer) ──────────────────────────────── */
    if(!doc.getElementById('chess-gl-ol')){
      var s=doc.createElement('style');
      s.textContent=
        '#chess-gl-ol{position:fixed;inset:0;z-index:99999;background:#f8f9fb;'+
        'display:none;flex-direction:column;align-items:center;justify-content:center;'+
        'gap:1.1rem;font-family:Inter,system-ui,sans-serif;}'+
        '#chess-gl-ol .gl-logo{font-family:"Space Grotesk",system-ui,sans-serif;'+
        'font-size:1.25rem;font-weight:700;color:#111827;letter-spacing:-0.02em;'+
        'margin-bottom:0.5rem;}'+
        '#chess-gl-ol .gl-logo span{color:#A81022;}'+
        '#chess-gl-ol .gl-wrap{position:relative;width:64px;height:64px;}'+
        '#chess-gl-ol .gl-ring{position:absolute;inset:0;border-radius:50%;'+
        'border:4px solid rgba(168,16,34,0.13);border-top-color:#A81022;'+
        'animation:glSpin 0.88s linear infinite;}'+
        '#chess-gl-ol .gl-piece{position:absolute;top:50%;left:50%;'+
        'transform:translate(-50%,-50%);font-size:2rem;color:#A81022;'+
        'animation:glBounce 1.35s cubic-bezier(.36,.07,.19,.97) infinite;line-height:1;}'+
        '#chess-gl-ol .gl-txt{font-size:0.82rem;font-weight:700;color:#A81022;'+
        'letter-spacing:0.1em;text-transform:uppercase;}'+
        '#chess-gl-ol .gl-sub{font-size:0.7rem;color:#9ca3af;letter-spacing:0.04em;}'+
        '@keyframes glSpin{to{transform:rotate(360deg);}}'+
        '@keyframes glBounce{0%,100%{transform:translate(-50%,-42%);}'+
        '50%{transform:translate(-50%,-72%);}}';
      doc.head.appendChild(s);

      var ol=doc.createElement('div');
      ol.id='chess-gl-ol';
      ol.innerHTML=
        '<div class="gl-logo">Chess<span>Narr</span></div>'+
        '<div class="gl-wrap">'+
          '<div class="gl-ring"></div>'+
          '<div class="gl-piece">&#9818;</div>'+
        '</div>'+
        '<div class="gl-txt">Betöltés</div>'+
        '<div class="gl-sub">A narráció töltése folyamatban&hellip;</div>';
      doc.body.appendChild(ol);
    }

    /* ── 3. Kattintásfigyelő (minden rendernél frissítve) ──────────────── */
    if(par._chClickH) doc.removeEventListener('click',par._chClickH);
    par._chClickH=function(e){
      var btn=e.target.closest('button');
      if(btn&&/Play/.test(btn.textContent)){
        var ol=doc.getElementById('chess-gl-ol');
        if(ol){ol.style.display='flex';ol.style.opacity='1';ol.style.transition='';}
      }
    };
    doc.addEventListener('click',par._chClickH);

  }catch(ex){}
})();
</script>
</body></html>"""

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
            games.append({"name": stem, "stem": stem, "json": jf, "mp3": mp3})
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

_BOARD_COLORS = {"margin": "#A81022", "coord": "#FFFFFF"}


def fen_to_svg(fen: str, size: int = 440) -> str:
    try:
        board = chess.Board(fen)
    except Exception:
        board = chess.Board()
    return chess.svg.board(board, size=size, colors=_BOARD_COLORS)


def starting_svg(size: int = 440) -> str:
    return chess.svg.board(chess.Board(), size=size, colors=_BOARD_COLORS)


def make_svg_responsive(svg: str) -> str:
    """SVG szélességét 100%-ra állítja, magasságát eltávolítja – a viewBox tartja az arányt."""
    svg = re.sub(r'\bwidth="\d+"', 'width="100%"', svg, count=1)
    svg = re.sub(r'\s*\bheight="\d+"', '', svg, count=1)
    return svg

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
        if a["fen_idx"] not in seen and a["fen_idx"] > max_fen_idx:
            seen.add(a["fen_idx"])
            result.append({"fen_idx": a["fen_idx"], "word_frac": a["word_frac"]})
            max_fen_idx = a["fen_idx"]
    final_idx = len(all_fens) - 1
    if final_idx > 0 and (not result or result[-1]["fen_idx"] < final_idx):
        last_frac = result[-1]["word_frac"] if result else 0.0
        auto_frac = round(last_frac + (1.0 - last_frac) * 0.65, 6)
        result.append({"fen_idx": final_idx, "word_frac": auto_frac})
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
    svgs          = [fen_to_svg(f) for f in all_fens]
    svgs_json     = json.dumps(svgs)
    js_anchors    = json.dumps([
        {"fenIdx": a["fen_idx"], "wordFrac": a["word_frac"]}
        for a in timed_anchors
    ])
    mp3_data      = audio_b64(mp3_path)
    autoplay_attr = "autoplay" if autoplay else ""
    init_svg      = svgs[0] if svgs else starting_svg()

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
html,body{{margin:0;padding:0 6px 6px;background:#f8f9fb;display:flex;flex-direction:column;align-items:center;font-family:'Inter',system-ui,-apple-system,sans-serif;-webkit-font-smoothing:antialiased;}}
#board-wrapper{{position:relative;width:min(calc(100vw - 12px),calc(100vh - 78px));border-radius:14px;overflow:hidden;box-shadow:0 0 0 1px rgba(0,0,0,0.07),0 16px 48px rgba(0,0,0,0.12),0 4px 12px rgba(0,0,0,0.06);margin-top:6px;transition:box-shadow 0.18s ease;}}
#board-wrapper:hover{{box-shadow:0 8px 32px rgba(168,16,34,0.65),0 0 0 3px rgba(212,24,46,0.22),0 2px 8px rgba(0,0,0,0.14);}}
#board-wrapper svg rect:first-child{{transition:fill 0.18s ease;}}
#board-wrapper:hover svg rect:first-child{{fill:#d4182e!important;}}
#board-wrapper::before{{content:'';position:absolute;top:0;left:-75%;width:50%;height:100%;background:linear-gradient(90deg,transparent 0%,rgba(255,255,255,0.18) 50%,transparent 100%);transform:skewX(-15deg);pointer-events:none;z-index:10;transition:none;}}
#board-wrapper:hover::before{{left:150%;transition:left 0.55s ease;}}
#board-sizer{{display:block;visibility:hidden;pointer-events:none;}}
#board-sizer svg,#board-a svg,#board-b svg{{width:100%;height:auto;display:block;}}
#board-a,#board-b{{position:absolute;inset:0;}}
#info{{display:flex;align-items:center;gap:14px;width:min(calc(100vw - 12px),calc(100vh - 78px));margin-top:8px;padding:10px 16px;background:rgba(0,0,0,0.03);border:1px solid rgba(0,0,0,0.07);border-radius:10px;}}
#statusz{{font-size:0.92rem;font-weight:600;letter-spacing:0.02em;color:#A81022;white-space:nowrap;flex-shrink:0;}}
#pbar-wrap{{flex:1;height:10px;background:rgba(168,16,34,0.12);border-radius:99px;overflow:hidden;}}
#pbar-fill{{width:0%;height:100%;background:linear-gradient(90deg,#A81022,#c41428);border-radius:99px;transition:width 0.35s ease;}}
#load-overlay{{position:absolute;inset:0;z-index:50;background:rgba(248,249,251,0.93);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.65rem;border-radius:14px;transition:opacity 0.45s ease;pointer-events:none;}}
#load-piece{{font-size:2.8rem;color:#A81022;animation:loadBounce 1.3s cubic-bezier(0.36,0.07,0.19,0.97) infinite;transform-origin:center bottom;}}
#load-ring{{width:48px;height:48px;border:3px solid rgba(168,16,34,0.15);border-top-color:#A81022;border-radius:50%;animation:loadSpin 0.9s linear infinite;position:absolute;top:50%;left:50%;margin:-24px 0 0 -24px;}}
#load-label{{font-size:0.78rem;font-weight:700;color:#A81022;letter-spacing:0.1em;text-transform:uppercase;}}
#load-dots{{display:inline-block;animation:loadDots 1.4s steps(4,end) infinite;}}
@keyframes loadBounce{{0%,100%{{transform:translateY(0) scale(1);}}45%{{transform:translateY(-14px) scale(1.08);}}55%{{transform:translateY(-14px) scale(1.08);}}}}
@keyframes loadSpin{{to{{transform:rotate(360deg);}}}}
@keyframes loadDots{{0%{{content:'';}}25%{{content:'.';}}50%{{content:'..';}}75%{{content:'...';}}100%{{content:'';}} }}
</style>
</head>
<body>
<div id="board-wrapper">
  <div id="board-sizer">{init_svg}</div>
  <div id="board-a" style="z-index:2;">{init_svg}</div>
  <div id="board-b" style="z-index:1;"></div>
  <div id="load-overlay">
    <div style="position:relative;width:48px;height:48px;display:flex;align-items:center;justify-content:center;">
      <div id="load-ring"></div>
      <div id="load-piece">♟</div>
    </div>
    <div id="load-label">Narration loading<span id="load-dots"></span></div>
  </div>
</div>
<div id="info">
  <span id="statusz">&#9654; Loading…</span>
  <div id="pbar-wrap"><div id="pbar-fill"></div></div>
</div>
<audio id="narr" {autoplay_attr} src="data:audio/mpeg;base64,{mp3_data}" style="display:none"></audio>
<script>
const fenSvgs={svgs_json};
const anchors={js_anchors};
const TOTAL=fenSvgs.length;
const LOOKAHEAD=0.5;
const audio=document.getElementById('narr');
const statusz=document.getElementById('statusz');
const pbarFill=document.getElementById('pbar-fill');
let lastIdx=0,targetIdx=0,rafQueued=false,befejezett=false,front='a',fadeTimer=null;
function updatePbar(idx){{pbarFill.style.width=(TOTAL>1?(idx/(TOTAL-1))*100:0)+'%';}}
function getFenIdx(frac){{
  frac=Math.max(0,Math.min(1,frac));
  if(!anchors.length)return Math.min(Math.floor(frac*TOTAL),TOTAL-1);
  if(frac<=anchors[0].wordFrac){{const r=anchors[0].wordFrac>0?frac/anchors[0].wordFrac:0;return Math.round(r*anchors[0].fenIdx);}}
  const last=anchors[anchors.length-1];
  if(frac>=last.wordFrac){{const rem=1-last.wordFrac;const r=rem>0?(frac-last.wordFrac)/rem:1;return Math.min(last.fenIdx+Math.round(r*(TOTAL-1-last.fenIdx)),TOTAL-1);}}
  for(let i=0;i<anchors.length-1;i++){{const a=anchors[i],b=anchors[i+1];if(frac>=a.wordFrac&&frac<b.wordFrac){{const r=(frac-a.wordFrac)/(b.wordFrac-a.wordFrac);return Math.round(a.fenIdx+r*(b.fenIdx-a.fenIdx));}}}}
  return TOTAL-1;
}}
function mutatFen(idx){{
  idx=Math.max(lastIdx,Math.min(idx,TOTAL-1));targetIdx=idx;
  if(!rafQueued&&idx!==lastIdx){{rafQueued=true;requestAnimationFrame(()=>{{
    rafQueued=false;if(targetIdx===lastIdx)return;lastIdx=targetIdx;
    const frontEl=document.getElementById('board-'+front);
    const backId=front==='a'?'b':'a';const backEl=document.getElementById('board-'+backId);
    if(fadeTimer){{clearTimeout(fadeTimer);fadeTimer=null;}}
    backEl.innerHTML=fenSvgs[lastIdx];backEl.style.zIndex='2';frontEl.style.zIndex='1';
    backEl.style.transition='none';backEl.style.opacity='0';void backEl.offsetWidth;
    backEl.style.transition='opacity 0.22s ease-out';backEl.style.opacity='1';
    fadeTimer=setTimeout(()=>{{fadeTimer=null;front=backId;}},240);
    updatePbar(lastIdx);
  }});}}
}}
function hideLoadOverlay(){{var ol=document.getElementById('load-overlay');if(ol){{ol.style.opacity='0';setTimeout(function(){{if(ol&&ol.parentNode)ol.parentNode.removeChild(ol);}},480);}}}}
var _narrReady=false;
function onNarrReady(){{
  if(_narrReady)return;_narrReady=true;
  hideLoadOverlay();
  try{{
    var _ol=window.parent.document.getElementById('chess-gl-ol');
    if(_ol){{_ol.style.transition='opacity 0.55s ease';_ol.style.opacity='0';
      setTimeout(function(){{_ol.style.display='none';_ol.style.opacity='1';_ol.style.transition='';}},580);}}
  }}catch(_e){{try{{window.parent.postMessage({{type:'chess-narr-started'}},'*');}}catch(_x){{}}}}
  statusz.textContent='► Playing narration…';
  audio.play().catch(()=>{{
    statusz.textContent='► Click anywhere to play';
    document.body.style.cursor='pointer';
    document.addEventListener('click',function startOnClick(){{
      audio.play().catch(()=>{{}});
      document.body.style.cursor='';
      document.removeEventListener('click',startOnClick);
    }},{{once:true}});
  }});
}}
['loadedmetadata','canplay','play'].forEach(function(ev){{audio.addEventListener(ev,onNarrReady);}});
audio.addEventListener('timeupdate',function(){{if(!_narrReady&&audio.currentTime>0.1)onNarrReady();}});
audio.addEventListener('error',()=>{{onNarrReady();}});
if(audio.readyState>=1)setTimeout(onNarrReady,0);
audio.addEventListener('timeupdate',()=>{{if(befejezett||!audio.duration)return;mutatFen(getFenIdx((audio.currentTime+LOOKAHEAD)/audio.duration));}});
audio.addEventListener('ended',()=>{{befejezett=true;mutatFen(TOTAL-1);updatePbar(TOTAL-1);statusz.textContent='⏸ Final position – still visible…';setTimeout(()=>{{statusz.textContent='✓ Playback complete.';}},3000);}});
audio.addEventListener('error',()=>{{statusz.textContent='⚠ Audio file failed to load.';}});
(function(){{function setH(){{try{{var h=Math.max(450,window.parent.innerHeight-130);window.parent.postMessage({{isStreamlitMessage:true,type:'streamlit:setFrameHeight',height:h}},'*');}}catch(e){{}}}}setH();window.addEventListener('resize',function(){{clearTimeout(window._rht);window._rht=setTimeout(setH,120);}});setTimeout(setH,300);}})();
</script>
</body>
</html>"""
    return html

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
        raise ValueError("Failed to parse PGN! Check the format.")
    moves_uci = []
    board = game.board()
    for move in game.mainline_moves():
        moves_uci.append(move.uci())
        board.push(move)
    if not moves_uci:
        raise ValueError("No moves found in the PGN!")
    headers = dict(game.headers)
    return {
        "white":     headers.get("White", "White"),
        "black":     headers.get("Black", "Black"),
        "white_elo": headers.get("WhiteElo", "?"),
        "black_elo": headers.get("BlackElo", "?"),
        "eco":       headers.get("ECO", "?"),
        "opening":   headers.get("Opening", ""),
        "result":    headers.get("Result", "*"),
        "moves_uci": moves_uci,
    }


def _make_game_stem(pgn_text: str) -> str:
    """PGN headers alapján egyedi, sorszámozott fájlnevet generál.

    Formátum: White_vs_Black_ECO_NNNN
    A sorszám az első szabad 4 jegyű szám, amely nem ütközik
    a json_narracio és hangos_narracio mappák meglévő fájljaival.
    """
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text.strip()))
    except Exception:
        game = None

    if game is not None:
        white = game.headers.get("White", "White")
        black = game.headers.get("Black", "Black")
        eco   = game.headers.get("ECO", "")
    else:
        white, black, eco = "White", "Black", ""

    def _sanitize(name: str) -> str:
        name = re.sub(r"[^\w]", "_", name)
        name = re.sub(r"_+", "_", name).strip("_")
        return name or "Unknown"

    white_s = _sanitize(white)
    black_s = _sanitize(black)
    eco_s   = re.sub(r"[^\w]", "", eco) or "XX"
    base    = f"{white_s}_vs_{black_s}_{eco_s}"

    existing: set[int] = set()
    for pattern in [
        os.path.join(config.LLM_ANALYSIS_JSON_DIR,   f"{base}_*.json"),
        os.path.join(config.LLM_ANALYSIS_HANGOS_DIR, f"{base}_*.mp3"),
    ]:
        for f in glob.glob(pattern):
            m = re.search(r"_(\d{4})\.\w+$", f)
            if m:
                existing.add(int(m.group(1)))

    n = 1
    while n in existing:
        n += 1
    return f"{base}_{n:04d}"


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
                raise RuntimeError("Stockfish terminated unexpectedly!")
            if line.startswith(prefix):
                return line.rstrip()

    try:
        send("uci");  expect("uciok")
        send("isready"); expect("readyok")
        board = chess.Board()
        evals = []
        total = min(len(moves_uci), config.STOCKFISH_MOVES_LIMIT)
        for i, uci in enumerate(moves_uci[:total]):
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                break
            san     = board.san(move)
            pre_fen = board.fen()

            # Pre-move: legjobb alternatíva (depth 6, gyors heurisztika az LLM-nek)
            send(f"position fen {pre_fen}")
            send("go depth 6")
            best_uci_alt = None
            while True:
                line = proc.stdout.readline().rstrip()
                if line.startswith("bestmove"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] not in ("(none)", uci):
                        best_uci_alt = parts[1]
                    break
            best_move_san = None
            if best_uci_alt:
                try:
                    tmp = chess.Board(pre_fen)
                    best_move_san = tmp.san(chess.Move.from_uci(best_uci_alt))
                except Exception:
                    pass

            board.push(move)
            fen          = board.fen()
            side_to_move = board.turn

            # Post-move: cp értékelés (depth 12)
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
                    sign  = 1 if side_to_move == chess.WHITE else -1
                    if stype == "cp":
                        cp_white = sign * sval
                    elif stype == "mate":
                        mate_val = sign * sval
                except (ValueError, IndexError):
                    pass
            evals.append({
                "move_number":   (i // 2) + 1,
                "color":         "white" if i % 2 == 0 else "black",
                "uci":           uci,
                "san":           san,
                "cp":            cp_white,
                "mate":          mate_val,
                "fen":           fen,
                "best_move_san": best_move_san,
            })
            progress["pct"]  = 0.10 + 0.50 * (i + 1) / total
            progress["step"] = f"Stockfish analysis: {i + 1}/{total} moves..."
    finally:
        try:
            send("quit")
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
    return evals


def run_custom_pipeline(pgn_text: str, progress: dict) -> None:
    """Teljes pipeline futtatása egyedi PGN-re (háttérszálon hívva)."""
    try:
        progress.update({"step": "Parsing PGN...", "pct": 0.02})
        game_data = _parse_pgn(pgn_text)
        game_stem = _make_game_stem(pgn_text)
        progress["stem"] = game_stem

        progress.update({"step": "Locating Stockfish...", "pct": 0.07})
        sf_path = _find_stockfish()
        if not sf_path:
            raise RuntimeError(
                "Stockfish not found! Install it or set the path in config.py."
            )

        progress.update({"step": "Starting Stockfish analysis...", "pct": 0.10})
        evaluations = _stockfish_analyze(game_data["moves_uci"], progress, sf_path)

        moves_for_json = (
            [{"move_number": 0, "color": "start", "san": "", "fen": chess.STARTING_FEN}]
            + [{"move_number": e["move_number"], "color": e["color"],
                "san": e["san"], "fen": e["fen"]}
               for e in evaluations]
        )
        remaining_ucis = game_data["moves_uci"][len(evaluations):]
        if remaining_ucis:
            board = chess.Board()
            for e in evaluations:
                board.push(chess.Move.from_uci(e["uci"]))
            for i, uci in enumerate(remaining_ucis):
                move = chess.Move.from_uci(uci)
                san = board.san(move)
                board.push(move)
                ply = len(evaluations) + i
                moves_for_json.append({
                    "move_number": (ply // 2) + 1,
                    "color": "white" if ply % 2 == 0 else "black",
                    "san": san,
                    "fen": board.fen(),
                })

        progress.update({
            "step": "Generating LLM narration (API call, a few seconds)...",
            "pct":  0.62,
        })
        narration_json = generate_narration(game_data, evaluations)
        narration_json["white"] = game_data["white"]
        narration_json["black"] = game_data["black"]
        narration_json["moves"] = moves_for_json

        progress.update({"step": "Saving narration JSON...", "pct": 0.78})
        json_path = os.path.join(config.LLM_ANALYSIS_JSON_DIR, f"{game_stem}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(narration_json, f, ensure_ascii=False, indent=2)

        tts_text = "\n\n".join(p["text"] for p in narration_json.get("paragraphs", []))
        txt_path = os.path.join(config.LLM_ANALYSIS_SZOVEGES_DIR, f"{game_stem}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(tts_text)

        progress.update({
            "step": "Generating audio with TTS (1–2 min)...",
            "pct":  0.82,
        })
        mp3_path = os.path.join(config.LLM_ANALYSIS_HANGOS_DIR, f"{game_stem}.mp3")
        generate_audio(tts_text, mp3_path)

        progress.update({
            "step": f"Done! \"{game_stem}\" is ready – press Play!",
            "pct":  1.0,
            "done": True,
        })
    except Exception as exc:
        tb = traceback.format_exc()
        err_msg = str(exc) or type(exc).__name__
        progress.update({
            "step":      f"Error in step »{progress.get('step', '?')}«: {err_msg}",
            "pct":       progress.get("pct", 0.0),
            "done":      True,
            "has_error": True,
            "traceback": tb,
        })

# ─────────────────────────────────────────────────────────────────────────────
# UI segédfüggvények
# ─────────────────────────────────────────────────────────────────────────────

def _provider_color(provider: str) -> str:
    return {
        "openai":    "#10a37f",
        "gemini":    "#4285f4",
        "anthropic": "#cc785c",
        "mistral":   "#f7630c",
        "elevenlabs":"#6c4be4",
    }.get(provider.lower(), "#6b7280")


def _badge(label: str, color: str) -> str:
    return (
        f'<span style="display:inline-flex;align-items:center;padding:0.2rem 0.6rem;'
        f'border-radius:99px;font-size:0.7rem;font-weight:600;letter-spacing:0.04em;'
        f'background:{color}18;color:{color};border:1px solid {color}35;">'
        f'{label}</span>'
    )


def _inject_css(css: str) -> None:
    """CSS injektálás Python-Markdown HTML-blokk truncation nélkül.

    A Markdown parser az első üres sornál lezárja a <style> blokkot,
    ezért az üres sorokat egyre tömörítjük injektálás előtt.
    """
    compressed = re.sub(r"\n[ \t]*\n", "\n", css)
    st.markdown(f"<style>{compressed}</style>", unsafe_allow_html=True)


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div style="padding:0.5rem 0 1.5rem;text-align:center;">'
            '<div style="width:52px;height:52px;background:linear-gradient(135deg,#A81022,#7a0b18);'
            'border-radius:16px;display:inline-flex;align-items:center;justify-content:center;'
            'font-size:1.8rem;line-height:1;box-shadow:0 6px 20px rgba(168,16,34,0.3);'
            'margin-bottom:0.75rem;">&#9818;</div>'
            '<div style="font-family:\'Space Grotesk\',system-ui,sans-serif;font-size:1.15rem;'
            'font-weight:700;color:#111827;letter-spacing:-0.02em;">'
            'Chess<span style="color:#A81022;">Narr</span></div>'
            '<div style="font-size:0.7rem;color:#9ca3af;letter-spacing:0.06em;'
            'text-transform:uppercase;margin-top:0.2rem;">AI · Stockfish · TTS</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div style="height:1px;background:rgba(0,0,0,0.08);margin:0 0 1.25rem;"></div>',
            unsafe_allow_html=True,
        )

        steps_html = "".join(
            f'<div style="display:flex;align-items:center;gap:0.65rem;padding:0.45rem 0;">'
            f'<span style="width:22px;height:22px;border-radius:7px;'
            f'background:rgba(168,16,34,0.08);border:1px solid rgba(168,16,34,0.18);'
            f'display:inline-flex;align-items:center;justify-content:center;'
            f'font-size:0.7rem;font-weight:700;color:#A81022;flex-shrink:0;">{num}</span>'
            f'<span style="font-size:0.85rem;color:#4b5563;">{icon} {label}</span>'
            f'</div>'
            for num, icon, label in [
                ("1", "📄", "PGN input"),
                ("2", "♟", "Stockfish analysis"),
                ("3", "🤖", "AI narration"),
                ("4", "🔊", "Speech synthesis"),
            ]
        )
        st.markdown(
            f'<div style="margin-bottom:1.5rem;">'
            f'<div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.09em;'
            f'color:#9ca3af;font-weight:600;margin-bottom:0.5rem;">How it works</div>'
            f'{steps_html}</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div style="height:1px;background:rgba(0,0,0,0.08);margin:0 0 1.25rem;"></div>',
            unsafe_allow_html=True,
        )

        llm_color = _provider_color(config.LLM_PROVIDER)
        tts_color = _provider_color(config.TTS_PROVIDER)
        st.markdown(
            f'<div>'
            f'<div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.09em;'
            f'color:#9ca3af;font-weight:600;margin-bottom:0.65rem;">Configuration</div>'
            f'<div style="display:flex;flex-direction:column;gap:0.5rem;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="font-size:0.8rem;color:#6b7280;">LLM</span>'
            f'{_badge(config.LLM_PROVIDER.upper(), llm_color)}</div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="font-size:0.8rem;color:#6b7280;">TTS</span>'
            f'{_badge(config.TTS_PROVIDER.upper(), tts_color)}</div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="font-size:0.8rem;color:#6b7280;">Depth</span>'
            f'{_badge(f"depth {config.STOCKFISH_DEPTH}", "#6b7280")}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )



def render_header() -> None:
    st.markdown(
        '<div style="padding:0 0 1.1rem;text-align:center;">'
        '<div style="display:inline-flex;align-items:center;gap:0.9rem;margin-bottom:0.6rem;">'
        '<div style="width:52px;height:52px;background:linear-gradient(135deg,#A81022 0%,#7a0b18 100%);'
        'border-radius:15px;display:flex;align-items:center;justify-content:center;'
        'font-size:1.75rem;line-height:1;color:#fff;'
        'box-shadow:0 6px 24px rgba(168,16,34,0.35),0 2px 6px rgba(0,0,0,0.15);">&#9818;</div>'
        '<div style="text-align:left;">'
        '<div style="font-family:\'Space Grotesk\',system-ui,sans-serif;font-size:1.9rem;'
        'font-weight:700;color:#111827;letter-spacing:-0.03em;line-height:1;">'
        'Chess<span style="color:#A81022;">Narr</span></div>'
        '<div style="font-size:0.72rem;color:#9ca3af;letter-spacing:0.08em;'
        'text-transform:uppercase;font-weight:500;margin-top:0.3rem;">'
        'AI-powered game commentary</div>'
        '</div></div>'
        '<div style="width:80px;height:2px;background:linear-gradient(90deg,transparent,#A8102255,transparent);'
        'margin:0.75rem auto 0;border-radius:99px;"></div>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_pipeline_progress(prog: dict) -> None:
    pct       = prog.get("pct", 0.0)
    step      = prog.get("step", "")
    has_error = prog.get("has_error", False)
    done      = prog.get("done", False)

    pct_pct = min(pct, 1.0) * 100
    st.markdown(
        f'<div style="margin:0.4rem 0;height:10px;background:rgba(168,16,34,0.12);'
        f'border-radius:99px;overflow:hidden;">'
        f'<div style="width:{pct_pct:.1f}%;height:100%;'
        f'background:linear-gradient(90deg,#A81022,#c41428);'
        f'border-radius:99px;transition:width 0.35s ease;"></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if has_error:
        st.error(step)
        tb = prog.get("traceback", "")
        if tb:
            with st.expander("Error details"):
                st.code(tb, language="python")
        return

    if done and pct >= 1.0:
        st.success(step)
        return

    pipeline_steps = [
        (0.02, 0.10, "📄", "PGN parsing"),
        (0.10, 0.62, "♟",  "Stockfish analysis"),
        (0.62, 0.82, "🤖", "AI narration"),
        (0.82, 1.00, "🔊", "Speech synthesis"),
    ]

    rows = []
    for s_start, s_end, icon, label in pipeline_steps:
        if pct >= s_end:
            ind, col_i, bg, border, tc = "✓", "#059669", "rgba(5,150,105,0.08)", "rgba(5,150,105,0.22)", "#059669"
        elif pct >= s_start:
            ind, col_i, bg, border, tc = "●", "#A81022", "rgba(168,16,34,0.07)", "rgba(168,16,34,0.25)", "#111827"
        else:
            ind, col_i, bg, border, tc = "○", "#d1d5db", "rgba(0,0,0,0.02)", "rgba(0,0,0,0.07)", "#9ca3af"
        anim = "animation:chpulse 1.4s ease-in-out infinite;" if pct >= s_start and pct < s_end else ""
        rows.append(
            f'<div style="display:flex;align-items:center;gap:0.7rem;padding:0.55rem 0.9rem;'
            f'border-radius:9px;background:{bg};border:1px solid {border};">'
            f'<span style="color:{col_i};font-size:1rem;width:18px;text-align:center;{anim}">{ind}</span>'
            f'<span style="font-size:0.95rem;color:{tc};">{icon} {label}</span>'
            f'</div>'
        )

    step_safe = step.replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(
        f'<style>@keyframes chpulse{{0%,100%{{opacity:1}}50%{{opacity:0.35}}}}</style>'
        f'<div style="display:flex;flex-direction:column;gap:0.4rem;margin-top:0.4rem;">'
        + "".join(rows)
        + f'<div style="font-size:0.85rem;color:#9ca3af;padding:0.3rem 0.5rem;'
          f'font-family:monospace;">{step_safe}</div>'
          f'</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Globális CSS  (tömörítve injektálva – lásd _inject_css)
# ─────────────────────────────────────────────────────────────────────────────

_RAW_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg:          #ffffff;
  --surf:        #f8f9fb;
  --surf2:       #f0f2f6;
  --surf3:       #e5e8ef;
  --border:      rgba(0,0,0,0.08);
  --border2:     rgba(0,0,0,0.15);
  --accent:      #A81022;
  --accent2:     #c41428;
  --accent-glow: rgba(168,16,34,0.12);
  --green:       #059669;
  --green2:      #10b981;
  --red:         #dc2626;
  --blue:        #2563eb;
  --text:        #111827;
  --muted:       #6b7280;
  --faint:       #9ca3af;
  --radius:      12px;
  --radius-lg:   20px;
  --shadow:      0 4px 20px rgba(0,0,0,0.07);
  --shadow-lg:   0 8px 40px rgba(0,0,0,0.12);
}

*,*::before,*::after{box-sizing:border-box;}

.stApp{background:var(--bg)!important;height:100vh!important;overflow:hidden!important;}

html,body{height:100vh!important;overflow:hidden!important;}

[data-testid="stAppViewContainer"]{height:100vh!important;overflow:hidden!important;}

[data-testid="stMain"],[data-testid="stMainBlockContainer"]{overflow:hidden!important;}

html,body,[class*="css"]{
  font-family:'Inter',system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif!important;
  font-size:17px!important;
  color:var(--text)!important;
  -webkit-font-smoothing:antialiased!important;
  text-rendering:optimizeLegibility!important;
}

#MainMenu,footer,header,[data-testid="stToolbar"],[data-testid="stDecoration"],.stDeployButton{display:none!important;height:0!important;min-height:0!important;visibility:hidden!important;position:absolute!important;}

[data-testid="stHeader"]{display:none!important;height:0!important;min-height:0!important;visibility:hidden!important;position:absolute!important;}

.main .block-container{max-width:1380px!important;padding:0.4rem 1.5rem 0.5rem!important;margin:0 auto;}

section.main>div:first-child{padding-top:0!important;}

[data-testid="stAppViewContainer"]>section>div{padding-top:0!important;}

[data-testid="stMain"]{padding-top:0!important;}

[data-testid="stMain"]>div{padding-top:0!important;}

[data-testid="stMainBlockContainer"]{padding-top:0.4rem!important;}

[data-testid="stHorizontalBlock"]{gap:1.25rem!important;align-items:stretch!important;}

[data-testid="column"]{
  background:var(--surf)!important;
  border:1px solid var(--border)!important;
  border-radius:var(--radius-lg)!important;
  padding:1rem!important;
  box-shadow:var(--shadow)!important;
  transition:border-color 0.25s ease,box-shadow 0.25s ease!important;
  display:flex!important;
  flex-direction:column!important;
}

[data-testid="column"]:hover{border-color:var(--border2)!important;box-shadow:var(--shadow-lg)!important;}

[data-testid="column"] [data-testid="stVerticalBlock"]{flex:1!important;display:flex!important;flex-direction:column!important;}
[data-testid="column"] [data-testid="stVerticalBlock"]>div{flex:1!important;display:flex!important;flex-direction:column!important;}
[data-testid="stTextArea"]{flex:1!important;display:flex!important;flex-direction:column!important;min-height:0!important;}
[data-testid="stTextArea"]>label{flex:0 0 auto!important;}
[data-testid="stTextArea"]>[data-baseweb="textarea"]{flex:1!important;display:flex!important;flex-direction:column!important;min-height:0!important;}
[data-testid="stTextArea"] [data-baseweb="textarea"]>div{flex:1!important;display:flex!important;flex-direction:column!important;min-height:0!important;}
/* Button row transparent panels */
[data-testid="stMarkdown"]:has(#ch-btn-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]{background:transparent!important;border:none!important;box-shadow:none!important;padding:0.25rem 0 0!important;}
[data-testid="stMarkdown"]:has(#ch-btn-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:hover{border:none!important;box-shadow:none!important;}
/* Selectbox placeholder */
.pgn-selectbox-placeholder{height:42px!important;flex:0 0 42px!important;}

h1,h2,h3,h4{font-family:'Space Grotesk',system-ui,sans-serif!important;letter-spacing:-0.02em!important;color:var(--text)!important;}

h3{font-size:1.2rem!important;font-weight:600!important;margin:0 0 1rem!important;}

label,[data-testid="stWidgetLabel"] p,[data-testid="stTextArea"] label,[data-testid="stSelectbox"] label{
  color:var(--muted)!important;
  font-size:0.85rem!important;
  text-transform:uppercase!important;
  letter-spacing:0.09em!important;
  font-weight:600!important;
}

.stButton>button{
  width:100%!important;
  font-family:'Space Grotesk',system-ui,sans-serif!important;
  font-size:1.08rem!important;
  font-weight:600!important;
  letter-spacing:0.02em!important;
  padding:0.85rem 1.5rem!important;
  border-radius:10px!important;
  border:none!important;
  cursor:pointer!important;
  transition:all 0.18s cubic-bezier(0.4,0,0.2,1)!important;
  position:relative!important;
  overflow:hidden!important;
}

[data-testid="baseButton-primary"],
[data-testid="stBaseButton-primary"],
button[kind="primary"]{
  background:linear-gradient(135deg,#A81022 0%,#8a0d1b 100%)!important;
  color:#ffffff!important;
  box-shadow:0 4px 18px rgba(168,16,34,0.35),0 1px 3px rgba(0,0,0,0.12)!important;
}

[data-testid="baseButton-primary"]:hover,
[data-testid="stBaseButton-primary"]:hover,
button[kind="primary"]:hover{
  background:linear-gradient(135deg,#d4182e 0%,#f01c34 100%)!important;
  transform:translateY(-2px)!important;
  box-shadow:0 8px 32px rgba(168,16,34,0.65),0 0 0 3px rgba(212,24,46,0.22),0 2px 8px rgba(0,0,0,0.14)!important;
}

[data-testid="baseButton-primary"]::before,
[data-testid="stBaseButton-primary"]::before,
button[kind="primary"]::before{
  content:'';
  position:absolute;
  top:0;left:-75%;
  width:50%;height:100%;
  background:linear-gradient(90deg,transparent 0%,rgba(255,255,255,0.28) 50%,transparent 100%);
  transform:skewX(-15deg);
  pointer-events:none;
  transition:none;
}

[data-testid="baseButton-primary"]:hover::before,
[data-testid="stBaseButton-primary"]:hover::before,
button[kind="primary"]:hover::before{
  left:150%;
  transition:left 0.45s ease;
}

[data-testid="baseButton-primary"]:active,
[data-testid="stBaseButton-primary"]:active,
button[kind="primary"]:active{transform:translateY(0)!important;}

[data-testid="baseButton-primary"]:disabled,
[data-testid="stBaseButton-primary"]:disabled,
button[kind="primary"]:disabled{
  background:var(--surf3)!important;
  color:var(--faint)!important;
  box-shadow:none!important;
  transform:none!important;
  cursor:not-allowed!important;
}

[data-testid="baseButton-secondary"],
[data-testid="stBaseButton-secondary"],
button[kind="secondary"]{
  background:linear-gradient(135deg,#A81022 0%,#8a0d1b 100%)!important;
  color:#ffffff!important;
  border:none!important;
  box-shadow:0 4px 18px rgba(168,16,34,0.35),0 1px 3px rgba(0,0,0,0.12)!important;
}

[data-testid="baseButton-secondary"]:hover,
[data-testid="stBaseButton-secondary"]:hover,
button[kind="secondary"]:hover{
  background:linear-gradient(135deg,#d4182e 0%,#f01c34 100%)!important;
  transform:translateY(-2px)!important;
  box-shadow:0 8px 32px rgba(168,16,34,0.65),0 0 0 3px rgba(212,24,46,0.22),0 2px 8px rgba(0,0,0,0.14)!important;
}

[data-testid="baseButton-secondary"]::before,
[data-testid="stBaseButton-secondary"]::before,
button[kind="secondary"]::before{
  content:'';
  position:absolute;
  top:0;left:-75%;
  width:50%;height:100%;
  background:linear-gradient(90deg,transparent 0%,rgba(255,255,255,0.28) 50%,transparent 100%);
  transform:skewX(-15deg);
  pointer-events:none;
  transition:none;
}

[data-testid="baseButton-secondary"]:hover::before,
[data-testid="stBaseButton-secondary"]:hover::before,
button[kind="secondary"]:hover::before{
  left:150%;
  transition:left 0.45s ease;
}

textarea{
  flex:1!important;
  height:100%!important;
  min-height:200px!important;
  resize:vertical!important;
  background:#ffffff!important;
  border:1px solid var(--border)!important;
  border-radius:10px!important;
  color:var(--text)!important;
  font-family:'JetBrains Mono','Fira Code','Cascadia Code',monospace!important;
  font-size:0.95rem!important;
  line-height:1.65!important;
  transition:border-color 0.2s ease,box-shadow 0.2s ease!important;
  padding:0.85rem!important;
  box-shadow:0 1px 4px rgba(0,0,0,0.05)!important;
  caret-color:#A81022!important;
}

textarea:focus{border-color:var(--accent)!important;box-shadow:0 0 0 3px var(--accent-glow)!important;outline:none!important;}

textarea::placeholder{color:#d1d5db!important;}

[data-testid="stSelectbox"] [data-baseweb="select"]>div{
  background:linear-gradient(135deg,#A81022 0%,#8a0d1b 100%)!important;
  border-color:#8a0d1b!important;
  border-radius:10px!important;
  color:#ffffff!important;
  box-shadow:0 4px 18px rgba(168,16,34,0.3),0 1px 3px rgba(0,0,0,0.1)!important;
  transition:background 0.18s ease,box-shadow 0.18s ease!important;
  position:relative!important;
  overflow:hidden!important;
}

[data-testid="stSelectbox"] [data-baseweb="select"]>div:hover{
  background:linear-gradient(135deg,#d4182e 0%,#f01c34 100%)!important;
  box-shadow:0 8px 32px rgba(168,16,34,0.65),0 0 0 3px rgba(212,24,46,0.22),0 2px 8px rgba(0,0,0,0.14)!important;
}

[data-testid="stSelectbox"] [data-baseweb="select"]>div::before{
  content:'';
  position:absolute;
  top:0;left:-75%;
  width:50%;height:100%;
  background:linear-gradient(90deg,transparent 0%,rgba(255,255,255,0.28) 50%,transparent 100%);
  transform:skewX(-15deg);
  pointer-events:none;
  transition:none;
}

[data-testid="stSelectbox"] [data-baseweb="select"]>div:hover::before{
  left:150%;
  transition:left 0.45s ease;
}

[data-testid="stSelectbox"] [data-baseweb="select"]>div>div{color:#ffffff!important;}
[data-testid="stSelectbox"] [data-baseweb="select"]>div span{color:#ffffff!important;}
[data-testid="stSelectbox"] [data-baseweb="select"]>div svg{fill:rgba(255,255,255,0.85)!important;}

[data-baseweb="popover"],[data-baseweb="menu"],ul[role="listbox"]{
  background:var(--accent)!important;
  border:1px solid #8a0d1b!important;
  border-radius:10px!important;
  box-shadow:var(--shadow-lg)!important;
}

[data-baseweb="menu"] li,[data-baseweb="menu-item"],[data-baseweb="list-item"],li[role="option"],[role="option"]{color:#ffffff!important;font-size:1rem!important;background:var(--accent)!important;transition:background 0.15s ease,box-shadow 0.15s ease!important;}
[data-baseweb="menu"] li:hover,[data-baseweb="menu-item"]:hover,[data-baseweb="list-item"]:hover,li[role="option"]:hover,[role="option"]:hover,[data-baseweb="menu"] li[data-highlighted],[data-baseweb="menu-item"][data-highlighted],[data-baseweb="list-item"][data-highlighted],li[role="option"][data-highlighted],[role="option"][data-highlighted]{background:linear-gradient(135deg,#d4182e 0%,#e81830 100%)!important;box-shadow:inset 0 0 0 1px rgba(255,255,255,0.12)!important;}
[data-baseweb="menu-item"] *,[data-baseweb="menu"] li *,[data-baseweb="list-item"] *,li[role="option"] *,[role="option"] *{color:#ffffff!important;}


[data-testid="stAlert"]{
  background:#fff8f8!important;
  border-radius:10px!important;
  border:1px solid rgba(168,16,34,0.2)!important;
  padding:0.85rem 1.1rem!important;
  color:var(--text)!important;
}

[data-testid="stAlert"] p,[data-testid="stAlert"] span,[data-testid="stAlert"] div{color:var(--text)!important;font-size:1rem!important;}

.stSuccess{border-color:rgba(5,150,105,0.35)!important;background:rgba(5,150,105,0.07)!important;}
.stError{border-color:rgba(220,38,38,0.35)!important;background:rgba(220,38,38,0.07)!important;}
.stWarning{border-color:rgba(168,16,34,0.25)!important;background:#fff8f8!important;}
.stInfo{border-color:rgba(37,99,235,0.3)!important;background:rgba(37,99,235,0.06)!important;}

[data-testid="stExpander"]{background:var(--surf)!important;border:1px solid var(--border)!important;border-radius:10px!important;}

[data-testid="stExpander"] summary{color:var(--muted)!important;font-size:0.9rem!important;}

[data-testid="stSidebar"]{background:var(--surf)!important;border-right:1px solid var(--border)!important;}

[data-testid="stSidebar"] .block-container{padding:1.5rem 1.25rem!important;}

::selection{background:rgba(168,16,34,0.28);color:inherit;}
::-webkit-scrollbar{width:5px;height:5px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:var(--surf3);border-radius:3px;}
::-webkit-scrollbar-thumb:hover{background:var(--muted);}

div[data-testid="stVerticalBlock"]>div{gap:0.7rem!important;}

.section-label{
  font-size:0.82rem;
  text-transform:uppercase;
  letter-spacing:0.1em;
  font-weight:700;
  color:#A81022;
  margin-bottom:0.5rem;
  display:flex;
  align-items:center;
  gap:0.5rem;
}

.section-label::after{content:'';flex:1;height:1px;background:rgba(168,16,34,0.15);}

.chess-board-wrap{width:min(100%,calc(100vh - 240px));margin:4px auto 8px;border-radius:12px;overflow:hidden;box-shadow:0 0 0 1px rgba(0,0,0,0.07),0 12px 40px rgba(0,0,0,0.10);position:relative;transition:box-shadow 0.18s ease;}
.chess-board-wrap:hover{box-shadow:0 8px 32px rgba(168,16,34,0.65),0 0 0 3px rgba(212,24,46,0.22),0 2px 8px rgba(0,0,0,0.14);}
.chess-board-wrap svg rect:first-child{transition:fill 0.18s ease;}
.chess-board-wrap:hover svg rect:first-child{fill:#d4182e!important;}
.chess-board-wrap::before{content:'';position:absolute;top:0;left:-75%;width:50%;height:100%;background:linear-gradient(90deg,transparent 0%,rgba(255,255,255,0.18) 50%,transparent 100%);transform:skewX(-15deg);pointer-events:none;z-index:10;transition:none;}
.chess-board-wrap:hover::before{left:150%;transition:left 0.55s ease;}
.chess-board-wrap svg{width:100%!important;display:block;}

@media (max-width:768px){
  [data-testid="stSidebar"]{display:none!important;width:0!important;min-width:0!important;}
  [data-testid="collapsedControl"]{display:none!important;width:0!important;}
  html,body{
    height:auto!important;overflow-y:auto!important;overflow-x:hidden!important;
    max-width:100vw!important;touch-action:pan-y!important;
  }
  .stApp{
    height:auto!important;min-height:100svh!important;
    overflow-y:auto!important;overflow-x:hidden!important;max-width:100vw!important;
  }
  [data-testid="stAppViewContainer"]{
    height:auto!important;overflow-y:auto!important;
    overflow-x:hidden!important;max-width:100vw!important;
  }
  section.main{
    flex:1 1 0%!important;min-width:0!important;width:100%!important;
    overflow-x:hidden!important;margin-left:0!important;
  }
  [data-testid="stMain"],[data-testid="stMainBlockContainer"]{
    overflow-x:hidden!important;overflow-y:visible!important;height:auto!important;
  }
  .main .block-container{
    width:100%!important;max-width:100%!important;
    padding:0.4rem 0.75rem 0.5rem!important;
    padding-left:0.75rem!important;
    margin:0 auto!important;
    overflow-x:hidden!important;box-sizing:border-box!important;
  }
  [data-testid="stMainBlockContainer"]{padding-bottom:0.5rem!important;}
  [data-testid="stHorizontalBlock"]{
    flex-direction:column!important;gap:0.5rem!important;
    width:100%!important;align-items:stretch!important;
    margin-left:0!important;margin-right:0!important;
  }
  [data-testid="column"]{
    min-width:100%!important;width:100%!important;max-width:100%!important;
    box-sizing:border-box!important;margin-left:0!important;margin-right:0!important;
  }
  [data-testid="column"]:has([data-testid="stVerticalBlock"]:empty),
  [data-testid="column"]:has([data-testid="stVerticalBlock"]:not(:has(*))){
    display:none!important;padding:0!important;margin:0!important;min-height:0!important;
  }
  [data-testid="stVerticalBlock"]{gap:0.4rem!important;}
  div[data-testid="stVerticalBlock"]>div{gap:0.4rem!important;}
  .chess-board-wrap{
    width:min(100%,calc(100vw - 24px))!important;
    margin:4px auto!important;display:block!important;
  }
}

[data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]{background:transparent!important;border:none!important;box-shadow:none!important;padding:0!important;}
[data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:hover{border:none!important;box-shadow:none!important;}
[data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:first-child [data-testid="stVerticalBlock"],
[data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:last-child [data-testid="stVerticalBlock"]{justify-content:center!important;}
[data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:first-child [data-testid="stVerticalBlock"]>div,
[data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:last-child [data-testid="stVerticalBlock"]>div{flex:0 0 auto!important;}

@media (max-width:768px){
  [data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"]{min-height:calc(100svh - 80px)!important;justify-content:center!important;gap:2rem!important;}
  [data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:first-child{order:2!important;}
  [data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2){order:1!important;}
  [data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:last-child{order:3!important;display:none!important;}
  [data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:first-child{height:auto!important;min-height:0!important;}
  [data-testid="stMarkdown"]:has(#ch-play-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:first-child [data-testid="stVerticalBlock"]{flex:0 0 auto!important;height:auto!important;}
}
"""

# ─────────────────────────────────────────────────────────────────────────────
# Streamlit alkalmazás
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="ChessNarrator · Chess narration",
    page_icon="♟️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

_inject_css(_RAW_CSS)

render_sidebar()

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
    white_name = narration_data.get("white") or selected["name"]
    black_name = narration_data.get("black") or ""
    matchup    = f"{white_name} vs {black_name}" if black_name else white_name

    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:center;gap:0.75rem;'
        f'padding:0.6rem 1.25rem;background:rgba(168,16,34,0.05);'
        f'border:1px solid rgba(168,16,34,0.15);border-radius:12px;margin-bottom:0.75rem;">'
        f'<span style="width:8px;height:8px;border-radius:50%;background:#A81022;'
        f'box-shadow:0 0 8px rgba(168,16,34,0.6);flex-shrink:0;'
        f'animation:nblink 1.5s ease-in-out infinite;"></span>'
        f'<span style="font-size:0.9rem;font-weight:600;color:#111827;letter-spacing:0.01em;">'
        f'{white_name}</span>'
        f'<span style="font-size:0.78rem;font-weight:500;color:#A81022;letter-spacing:0.06em;'
        f'text-transform:uppercase;">vs</span>'
        f'<span style="font-size:0.9rem;font-weight:600;color:#111827;letter-spacing:0.01em;">'
        f'{black_name}</span>'
        f'</div>'
        f'<style>@keyframes nblink{{0%,100%{{opacity:1;box-shadow:0 0 8px rgba(168,16,34,0.6);}}50%{{opacity:0.3;box-shadow:0 0 3px rgba(168,16,34,0.3);}}}}</style>',
        unsafe_allow_html=True,
    )
    paragraphs     = narration_data.get("paragraphs", [])
    player_html    = build_player_html(
        paragraphs, selected["mp3"],
        narration_data=narration_data,
        autoplay=True,
    )
    stc.html(player_html, height=560, scrolling=False)

    gap_l, btn_col, gap_r = st.columns([2, 3, 2])
    with btn_col:
        if st.button("← Back", use_container_width=True, type="primary"):
            st.session_state.playing = False
            st.rerun()

# ── ÁLLÓ MÓD ─────────────────────────────────────────────────────────────────

else:
    col_pgn, col_board = st.columns([1, 1], gap="large")

    # ── Bal oszlop: PGN bevitel ───────────────────────────────────────────────
    with col_pgn:
        st.markdown('<div class="section-label">Analyse your game</div>', unsafe_allow_html=True)

        st.markdown('<div class="pgn-selectbox-placeholder"></div>', unsafe_allow_html=True)
        pgn_text = st.text_area(
            "PGN",
            height=400,
            key="pgn_input",
            label_visibility="collapsed",
            placeholder=(
                '[Event "Live Chess"]\n'
                '[White "White"]\n'
                '[Black "Black"]\n'
                '[Result "1-0"]\n\n'
                "1. e4 e5 2. Nf3 Nc6 3. Bb5 ..."
            ),
            help=(
                "Any standard PGN format is accepted – "
                "headers are optional, moves-only works too."
            ),
        )

        prog = st.session_state.pipeline_progress
        if prog is not None:
            render_pipeline_progress(prog)
            if prog.get("done") and not prog.get("has_error") and prog.get("stem"):
                if st.session_state.last_game != prog["stem"]:
                    st.session_state.last_game = prog["stem"]

    # ── Jobb oszlop: játszmaválasztó + sakktábla ──────────────────────────────
    with col_board:
        if not games:
            st.markdown(
                '<div style="display:flex;flex-direction:column;align-items:center;'
                'justify-content:center;padding:4rem 1.5rem;text-align:center;">'
                '<div style="font-size:3.5rem;opacity:0.1;margin-bottom:1.25rem;">&#9818;</div>'
                '<div style="font-size:0.95rem;font-weight:600;color:#9ca3af;margin-bottom:0.5rem;">'
                'No analysed games</div>'
                '<div style="font-size:0.8rem;color:#d1d5db;line-height:1.7;max-width:280px;">'
                'Paste a PGN in the left panel and start the analysis, '
                'or run the <code style="color:#9ca3af;background:rgba(0,0,0,0.05);'
                'padding:0 0.3rem;border-radius:4px;">jatek_elemzese.ipynb</code> notebook.'
                '</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown('<div class="section-label">Select a game</div>', unsafe_allow_html=True)

            selected_name = st.selectbox(
                "Játszma",
                options=game_names,
                label_visibility="collapsed",
            )

            selected = game_map[selected_name]

            if st.session_state.last_game != selected_name:
                st.session_state.last_game = selected_name

            narration_data = load_json(selected["json"])
            paragraphs     = narration_data.get("paragraphs", [])
            all_fens       = get_all_fens(narration_data, paragraphs)
            last_fen       = all_fens[-1] if all_fens else chess.STARTING_FEN
            move_count     = len(all_fens) - 1
            svg            = fen_to_svg(last_fen)

            # Lépésszám a selectbox alatt
            if move_count:
                st.markdown(
                    f'<div style="font-size:0.85rem;color:#9ca3af;margin:-0.15rem 0 0.25rem;'
                    f'padding:0 0.15rem;">{move_count} ply (1/2 move)</div>',
                    unsafe_allow_html=True,
                )

            st.markdown(
                f'<div class="chess-board-wrap">{make_svg_responsive(svg)}</div>',
                unsafe_allow_html=True,
            )

    # ── Gombsor – mindkét gomb egy vonalban, panel stílus nélkül ─────────────
    st.markdown('<div id="ch-btn-row" style="height:0;overflow:hidden;"></div>', unsafe_allow_html=True)
    btn_col1, btn_col2 = st.columns([1, 1], gap="large")
    with btn_col1:
        if st.button(
            "Start analysis",
            disabled=pipeline_is_running,
            use_container_width=True,
            type="primary",
        ):
            if pgn_text.strip():
                progress = {"step": "Starting...", "pct": 0.0, "done": False, "error": None}
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
                pass
    with btn_col2:
        if games:
            if st.button("▶  Play", use_container_width=True, type="primary"):
                st.session_state.playing = True
                st.rerun()

    # ── Globális töltő overlay ────────────────────────────────────────────────
    stc.html(_OVERLAY_INJECTOR_HTML, height=0, scrolling=False)

    # ── Selectbox keresés tiltása < 10 játszma esetén (oszlopokon kívül, layout-semleges) ──
    if len(games) < 10:
        st.markdown(
            '<style>'
            '[data-testid="stSelectbox"] [data-baseweb="select"]>div,'
            '[data-testid="stSelectbox"] input{cursor:pointer!important;}'
            '</style>',
            unsafe_allow_html=True,
        )
        stc.html(
            """<script>
            (function() {
                function patch() {
                    var inp = window.parent.document.querySelector(
                        '[data-testid="stSelectbox"] input');
                    if (inp) {
                        inp.setAttribute('readonly', 'readonly');
                        inp.style.caretColor = 'transparent';
                        inp.style.cursor = 'pointer';
                    } else {
                        requestAnimationFrame(patch);
                    }
                }
                patch();
            })();
            </script>""",
            height=0,
            scrolling=False,
        )

    # ── Auto-refresh ha pipeline fut ─────────────────────────────────────────
    if pipeline_is_running:
        time.sleep(0.5)
        st.rerun()
