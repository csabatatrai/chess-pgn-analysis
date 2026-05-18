# -*- coding: utf-8 -*-
"""
streamlit_app.py – Sakk narráció lejátszó.

Indítás:
    streamlit run streamlit_app.py

UI:
  - Játszmaválasztó dropdown
  - Sakktábla (automatikusan frissül lejátszás közben)
  - PLAY / STOP gomb
"""

import os
import sys
import json
import glob
import base64

import streamlit as st
import chess
import chess.svg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# ─────────────────────────────────────────────────────────────────────────────
# Adatbetöltés
# ─────────────────────────────────────────────────────────────────────────────

def find_games() -> list[dict]:
    """JSON + MP3 párokat keres; csak azokat adja vissza, ahol mindkettő megvan."""
    json_files = glob.glob(os.path.join(config.LLM_ANALYSIS_JSON_DIR, "*.json"))
    games = []
    for jf in sorted(json_files, key=os.path.getmtime, reverse=True):
        stem = os.path.splitext(os.path.basename(jf))[0]
        mp3 = os.path.join(config.LLM_ANALYSIS_HANGOS_DIR, stem + ".mp3")
        if os.path.exists(mp3):
            games.append({"name": stem, "json": jf, "mp3": mp3})
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
# Anchor időzítés számítása (karakterarány → audio-arány)
# ─────────────────────────────────────────────────────────────────────────────

def compute_anchors(paragraphs: list) -> list[dict]:
    """
    Minden anchorhoz kiszámítja a char_frac értéket:
      char_frac = karakter-pozíció a teljes szövegben / összes karakter
    Ez lesz vetítve az audio időtartamára a böngészőben.
    """
    full_text = ""
    result = []

    for para in paragraphs:
        text = para.get("text", "")
        for anchor in para.get("anchors", []):
            trigger = anchor.get("trigger_word", "")
            fen = anchor.get("fen", "")
            if not trigger or not fen:
                continue
            pos = text.find(trigger)
            if pos < 0:
                continue
            result.append({
                "fen": fen,
                "trigger": trigger,
                "char_pos": len(full_text) + pos,
            })
        full_text += text + "  "

    total = len(full_text) or 1
    for a in result:
        a["char_frac"] = round(a["char_pos"] / total, 6)

    result.sort(key=lambda x: x["char_frac"])
    return result

# ─────────────────────────────────────────────────────────────────────────────
# HTML lejátszó komponens
# ─────────────────────────────────────────────────────────────────────────────

def build_player_html(paragraphs: list, mp3_path: str, autoplay: bool = True) -> str:
    """
    Önálló HTML oldal:
      - Sakktábla (SVG), ami az anchor-időknek megfelelően frissül
      - Rejtett audio elem, ami a narráció MP3-at játssza le
      - JavaScript: audio timeupdate → megfelelő SVG megjelenítése
    """
    anchors = compute_anchors(paragraphs)

    # Kezdőállás: az első anchor FEN-je, vagy a teljes kezdőállás
    init_svg = fen_to_svg(anchors[0]["fen"]) if anchors else starting_svg()

    # Minden anchor SVG-jét beágyazzuk rejtett <div>-ekbe
    hidden_svgs_html = ""
    for i, a in enumerate(anchors):
        svg = fen_to_svg(a["fen"])
        hidden_svgs_html += f'<div id="svg{i}" style="display:none">{svg}</div>\n'

    # JS anchor adat (csak char_frac kell, az SVG a DOM-ban van)
    js_fracs = json.dumps([a["char_frac"] for a in anchors])

    # Audio base64
    mp3_data = audio_b64(mp3_path)
    autoplay_attr = "autoplay" if autoplay else ""

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
  }}
  #board svg {{ width: 100%; height: auto; display: block; }}
  #board {{ width: 100%; max-width: 480px; }}
  #status {{
    font-family: sans-serif;
    font-size: 13px;
    color: #555;
    margin-top: 6px;
    min-height: 18px;
  }}
</style>
</head>
<body>

<div id="board">{init_svg}</div>
<div id="status">&#9654; Betöltés...</div>

<!-- Rejtett SVG-k minden anchor-hoz -->
<div style="display:none" id="svgstore">
{hidden_svgs_html}
</div>

<!-- Audio -->
<audio id="narr" {autoplay_attr}
       src="data:audio/mpeg;base64,{mp3_data}"
       style="display:none">
</audio>

<script>
  const fracs = {js_fracs};
  const audio  = document.getElementById('narr');
  const board  = document.getElementById('board');
  const status = document.getElementById('status');
  const total  = fracs.length;

  let lastIdx = -1;

  function showSvg(idx) {{
    if (idx === lastIdx || idx < 0 || idx >= total) return;
    const el = document.getElementById('svg' + idx);
    if (el) {{
      board.innerHTML = el.innerHTML;
      lastIdx = idx;
    }}
  }}

  audio.addEventListener('loadedmetadata', () => {{
    status.textContent = '\\u25BA Lejátszás folyamatban...';
    audio.play().catch(() => {{
      status.textContent = '\\u25BA Kattints a böngészőn belül az indításhoz.';
    }});
  }});

  audio.addEventListener('timeupdate', () => {{
    if (!audio.duration) return;
    const frac = audio.currentTime / audio.duration;
    let idx = -1;
    for (let i = 0; i < total; i++) {{
      if (fracs[i] <= frac) idx = i;
    }}
    showSvg(idx);
  }});

  audio.addEventListener('ended', () => {{
    status.textContent = '\\u2713 Lejátszás kész.';
  }});

  audio.addEventListener('error', () => {{
    status.textContent = '\\u26A0 Hangfájl betöltési hiba.';
  }});

  // Fallback: ha autoplay blokkolva van, visszük a init SVG-t
  if (total === 0) {{
    status.textContent = 'Nincs anchor adat.';
  }}
</script>
</body>
</html>"""
    return html

# ─────────────────────────────────────────────────────────────────────────────
# Streamlit alkalmazás
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Sakk narráció",
    page_icon="♟️",
    layout="centered",
)

# Minimális stílus: középre igazított, tiszta UI
st.markdown("""
<style>
  .block-container { max-width: 540px; padding-top: 2rem; }
  div[data-testid="stVerticalBlock"] > div { gap: 0.5rem; }
  .stButton button {
    width: 100%;
    font-size: 1.1rem;
    padding: 0.6rem 0;
    border-radius: 8px;
  }
</style>
""", unsafe_allow_html=True)

st.title("♟️ Sakk narráció")

# ── Session state ─────────────────────────────────────────────────────────────

if "playing" not in st.session_state:
    st.session_state.playing = False
if "last_game" not in st.session_state:
    st.session_state.last_game = None

# ── Játékok betöltése ─────────────────────────────────────────────────────────

games = find_games()

if not games:
    st.warning(
        "Még nincs lejátszható játszma. "
        "Futtasd le a `notebooks/jatek_elemzese.ipynb` notebookot, "
        "hogy JSON-narráció és MP3 fájl is keletkezzen, majd töltsd újra az oldalt!"
    )
    st.stop()

game_names = [g["name"] for g in games]
game_map   = {g["name"]: g for g in games}

# ── Dropdown ──────────────────────────────────────────────────────────────────

selected_name = st.selectbox(
    "Válassz játszmát:",
    options=game_names,
    label_visibility="collapsed",
)
selected = game_map[selected_name]

# Ha játszmát váltottunk, leállítjuk a lejátszást
if st.session_state.last_game != selected_name:
    st.session_state.playing = False
    st.session_state.last_game = selected_name

# ── Tartalom megjelenítése ────────────────────────────────────────────────────

narration_data = load_json(selected["json"])
paragraphs     = narration_data.get("paragraphs", [])

if st.session_state.playing:
    # ── LEJÁTSZÓ MÓD: HTML komponens (tábla + audio) ──────────────────────────
    player_html = build_player_html(paragraphs, selected["mp3"], autoplay=True)

    # Magasság: tábla (~480px) + státusz (~30px) + kis padding
    st.components.v1.html(player_html, height=540, scrolling=False)

    if st.button("⏹  Stop", use_container_width=True):
        st.session_state.playing = False
        st.rerun()

else:
    # ── ÁLLÓ MÓD: Streamlit tábla (első anchor FEN, vagy kezdőállás) ──────────
    anchors = compute_anchors(paragraphs)
    init_fen = anchors[0]["fen"] if anchors else chess.STARTING_FEN
    svg = fen_to_svg(init_fen)
    st.components.v1.html(
        f'<div style="display:flex;justify-content:center">{svg}</div>',
        height=470,
        scrolling=False,
    )

    if st.button("▶  Play", use_container_width=True):
        st.session_state.playing = True
        st.rerun()
