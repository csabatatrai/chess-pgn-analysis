# -*- coding: utf-8 -*-
"""
streamlit_demo.py – ChessNarr demó verzió: csak lejátszás, elemzési pipeline nélkül.

Indítás:
    streamlit run streamlit_demo.py
"""

import os
import sys
import re
import json
import glob
import base64
import time

import streamlit as st
import streamlit.components.v1 as stc
import chess
import chess.svg
import chess.pgn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

CUSTOM_GAME_STEM    = "sajat_jatszma"
CUSTOM_GAME_DISPLAY = "My game"

_DEMO_CARD_HTML = """
<div style="
    background: rgba(122,11,24,0.07);
    border: 1.5px solid rgba(122,11,24,0.28);
    border-radius: 12px;
    padding: 1.35rem 1.5rem;
    color: #7a0b18;
    margin-top: 0.25rem;
    flex: 1;
">
    <div style="font-size:0.97rem;line-height:1.75;font-weight:500;margin-bottom:1rem;">
        Csak lokálisan letöltött változatban elérhető a saját játszma elemzése funkció.
        Privát API kulcsokat igényel!
    </div>
    <div style="font-size:0.88rem;line-height:2;">
        <div>
            <strong>Repo:</strong>&nbsp;
            <a href="https://github.com/csabatatrai/chess-pgn-analysis" target="_blank"
               style="color:#7a0b18;font-weight:600;word-break:break-all;text-decoration:underline;">
                https://github.com/csabatatrai/chess-pgn-analysis
            </a>
        </div>
        <div>
            <strong>Készítette:</strong> Tátrai Csaba Attila
        </div>
        <div>
            <strong>LinkedIn:</strong>&nbsp;
            <a href="https://www.linkedin.com/in/csabatatrai-datascientist/" target="_blank"
               style="color:#7a0b18;font-weight:600;word-break:break-all;text-decoration:underline;">
                https://www.linkedin.com/in/csabatatrai-datascientist/
            </a>
        </div>
    </div>
</div>
"""

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
</style>
</head>
<body>
<div id="board-wrapper">
  <div id="board-sizer">{init_svg}</div>
  <div id="board-a" style="z-index:2;">{init_svg}</div>
  <div id="board-b" style="z-index:1;"></div>
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
audio.addEventListener('loadedmetadata',()=>{{statusz.textContent='► Playing narration…';audio.play().catch(()=>{{statusz.textContent='► Click to play!';}});}});
audio.addEventListener('timeupdate',()=>{{if(befejezett||!audio.duration)return;mutatFen(getFenIdx((audio.currentTime+LOOKAHEAD)/audio.duration));}});
audio.addEventListener('ended',()=>{{befejezett=true;mutatFen(TOTAL-1);updatePbar(TOTAL-1);statusz.textContent='⏸ Final position – still visible…';setTimeout(()=>{{statusz.textContent='✓ Playback complete.';}},3000);}});
audio.addEventListener('error',()=>{{statusz.textContent='⚠ Audio file failed to load.';}});
(function(){{function setH(){{try{{var h=Math.max(450,window.parent.innerHeight-130);window.parent.postMessage({{isStreamlitMessage:true,type:'streamlit:setFrameHeight',height:h}},'*');}}catch(e){{}}}}setH();window.addEventListener('resize',function(){{clearTimeout(window._rht);window._rht=setTimeout(setH,120);}});setTimeout(setH,300);}})();
</script>
</body>
</html>"""
    return html

# ─────────────────────────────────────────────────────────────────────────────
# UI segédfüggvények
# ─────────────────────────────────────────────────────────────────────────────

def _inject_css(css: str) -> None:
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

        st.markdown(
            '<div style="background:rgba(122,11,24,0.07);border:1px solid rgba(122,11,24,0.22);'
            'border-radius:10px;padding:0.9rem 1rem;color:#7a0b18;font-size:0.85rem;line-height:1.65;">'
            '<strong>Demo mód</strong><br>'
            'Ez a verzió a lejátszás funkciót tartalmazza. '
            'Az elemzési pipeline helyi telepítést és privát API kulcsokat igényel.'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div style="height:1px;background:rgba(0,0,0,0.08);margin:1.25rem 0;"></div>',
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
                ("1", "♟", "Stockfish analysis"),
                ("2", "🤖", "AI narration"),
                ("3", "🔊", "Speech synthesis"),
                ("4", "▶", "Demo playback"),
            ]
        )
        st.markdown(
            f'<div style="margin-bottom:1.5rem;">'
            f'<div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.09em;'
            f'color:#9ca3af;font-weight:600;margin-bottom:0.5rem;">How it works</div>'
            f'{steps_html}</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Globális CSS
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
/* Button row transparent panels */
[data-testid="stMarkdown"]:has(#ch-btn-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]{background:transparent!important;border:none!important;box-shadow:none!important;padding:0.25rem 0 0!important;}
[data-testid="stMarkdown"]:has(#ch-btn-row)~[data-testid="stHorizontalBlock"] [data-testid="column"]:hover{border:none!important;box-shadow:none!important;}

h1,h2,h3,h4{font-family:'Space Grotesk',system-ui,sans-serif!important;letter-spacing:-0.02em!important;color:var(--text)!important;}

h3{font-size:1.2rem!important;font-weight:600!important;margin:0 0 1rem!important;}

label,[data-testid="stWidgetLabel"] p,[data-testid="stSelectbox"] label{
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

[data-baseweb="popover"],[data-baseweb="menu"]{
  background:var(--accent)!important;
  border:1px solid #8a0d1b!important;
  border-radius:10px!important;
  box-shadow:var(--shadow-lg)!important;
}

[data-baseweb="menu"] li,[data-baseweb="menu-item"]{color:#ffffff!important;font-size:1rem!important;background:var(--accent)!important;transition:background 0.15s ease,box-shadow 0.15s ease!important;}
[data-baseweb="menu"] li:hover,[data-baseweb="menu-item"]:hover{background:linear-gradient(135deg,#d4182e 0%,#e81830 100%)!important;box-shadow:inset 0 0 0 1px rgba(255,255,255,0.12)!important;}
[data-baseweb="menu-item"] *,[data-baseweb="menu"] li *{color:#ffffff!important;}
li[role="option"]{background:var(--accent)!important;color:#ffffff!important;transition:background 0.15s ease,box-shadow 0.15s ease!important;}
li[role="option"]:hover{background:linear-gradient(135deg,#d4182e 0%,#e81830 100%)!important;box-shadow:inset 0 0 0 1px rgba(255,255,255,0.12)!important;}
li[role="option"] *{color:#ffffff!important;}

[data-testid="stAlert"]{
  background:#fff8f8!important;
  border-radius:10px!important;
  border:1px solid rgba(168,16,34,0.2)!important;
  padding:0.85rem 1.1rem!important;
  color:var(--text)!important;
}

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
"""

# ─────────────────────────────────────────────────────────────────────────────
# Streamlit alkalmazás
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="ChessNarrator · Demo",
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

# ── Játékok betöltése ─────────────────────────────────────────────────────────

games      = find_games()
game_names = [g["name"] for g in games]
game_map   = {g["name"]: g for g in games}

# ── LEJÁTSZÓ MÓD ─────────────────────────────────────────────────────────────

if st.session_state.playing:
    selected = game_map.get(st.session_state.last_game)
    if selected is None:
        st.session_state.playing = False
        st.rerun()

    narration_data = load_json(selected["json"])
    white_name = narration_data.get("white") or selected["name"]
    black_name = narration_data.get("black") or ""

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
    paragraphs  = narration_data.get("paragraphs", [])
    player_html = build_player_html(
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
    col_info, col_board = st.columns([1, 1], gap="large")

    # ── Bal oszlop: demó infókártya ───────────────────────────────────────────
    with col_info:
        st.markdown('<div class="section-label">Analyse your game</div>', unsafe_allow_html=True)
        st.markdown(_DEMO_CARD_HTML, unsafe_allow_html=True)

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
                'No pre-generated analyses found in the repository.'
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

    # ── Gombsor ──────────────────────────────────────────────────────────────
    st.markdown('<div id="ch-btn-row" style="height:0;overflow:hidden;"></div>', unsafe_allow_html=True)
    _, btn_col, _ = st.columns([1, 2, 1], gap="large")
    with btn_col:
        if games:
            if st.button("▶  Play", use_container_width=True, type="primary"):
                st.session_state.playing = True
                st.rerun()

    # ── Selectbox keresés tiltása < 10 játszma esetén ────────────────────────
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
