# -*- coding: utf-8 -*-
"""
streamlit_app.py – Sakk narráció lejátszó.

Indítás:
    streamlit run streamlit_app.py

UI:
  - Játszmaválasztó dropdown
  - Sakktábla (slideshow: minden lépés FEN-je szinkronban a hangfelvétellel)
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
# FEN-sorozat és anchor-időzítés
# ─────────────────────────────────────────────────────────────────────────────

def fen_position_key(fen: str) -> str:
    """FEN első 4 mezője (táblaállás, szín, sáncolás, en passant) – összehasonlításhoz."""
    return " ".join(fen.strip().split()[:4])


def get_all_fens(narration_data: dict, paragraphs: list) -> list[str]:
    """
    Visszaadja a lejátszandó FEN-ek rendezett listáját.
    Új JSON: 'moves' mező tartalmazza az összes lépés FEN-jét.
    Régi JSON: az anchor FEN-ekből rekonstruálja (fallback).
    """
    if narration_data.get("moves"):
        fens = [chess.STARTING_FEN]
        for m in narration_data["moves"]:
            if m.get("fen"):
                fens.append(m["fen"])
        return fens

    # Fallback: anchor FEN-ek dokumentum-sorrendben
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
    """
    Szóalapú (word-count) időzítési frakciót számít minden érvényes anchorhoz,
    és meghatározza a hozzá tartozó FEN indexét az all_fens tömbben.

    Visszatér: [{fen_idx, word_frac}] – word_frac szerint rendezve.
    Érvényes anchor: trigger_word szó szerint szerepel a szövegben ÉS
                     az anchor FEN megtalálható az all_fens tömbben.
    """
    fen_idx_map = {fen_position_key(f): i for i, f in enumerate(all_fens)}

    full_text = ""
    raw = []

    for para in paragraphs:
        text = para.get("text", "")
        for anchor in para.get("anchors", []):
            trigger = anchor.get("trigger_word", "")
            fen = anchor.get("fen", "")
            if not trigger or not fen:
                continue
            pos = text.find(trigger)
            if pos < 0:
                continue  # broken trigger_word – kihagyjuk

            word_pos = len((full_text + text[:pos]).split())
            fen_idx = fen_idx_map.get(fen_position_key(fen), -1)
            if fen_idx >= 0:
                raw.append({"fen_idx": fen_idx, "word_pos": word_pos})

        full_text += text + "  "

    total_words = max(len(full_text.split()), 1)
    for a in raw:
        a["word_frac"] = round(a["word_pos"] / total_words, 6)

    raw.sort(key=lambda x: x["word_frac"])

    # Egyedi fen_idx: csak az első előfordulás marad (ha ugyanaz a FEN kétszer szerepel)
    seen: set[int] = set()
    result = []
    for a in raw:
        if a["fen_idx"] not in seen:
            seen.add(a["fen_idx"])
            result.append({"fen_idx": a["fen_idx"], "word_frac": a["word_frac"]})

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
    """
    Önálló HTML oldal:
      - Összes FEN-pozíció SVG-ként előrenderelve (slideshow)
      - Rejtett audio elem a narráció MP3-ával
      - JavaScript:
          * audio timeupdate → szóarány-alapú interpoláció → FEN index
          * 0.5 s lookahead: az anchor pozícióját kicsit KORÁBBAN mutatja,
            hogy a néző biztosan látja, amikor a narrátor épp arról beszél
          * Opacity fade (0.25 s) az átmenetekhez
          * audio.ended → utolsó állás legalább 3 s-ig látható
    """
    narration_data = narration_data or {}

    all_fens = get_all_fens(narration_data, paragraphs)
    timed_anchors = compute_timed_anchors(paragraphs, all_fens)

    # Összes FEN SVG-vé konvertálva – JS tömbbe ágyazva
    svgs = [fen_to_svg(f) for f in all_fens]
    total_fens = len(svgs)

    svgs_json = json.dumps(svgs)
    js_anchors = json.dumps([
        {"fenIdx": a["fen_idx"], "wordFrac": a["word_frac"]}
        for a in timed_anchors
    ])

    mp3_data = audio_b64(mp3_path)
    autoplay_attr = "autoplay" if autoplay else ""
    init_svg = svgs[0] if svgs else starting_svg()

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
  #board {{
    width: 100%;
    max-width: 480px;
  }}
  #board svg {{ width: 100%; height: auto; display: block; }}
  /* Csak BEFAKULÁS – a tábla soha nem tűnik el, nincs villódzás */
  @keyframes betunik {{
    from {{ opacity: 0.45; }}
    to   {{ opacity: 1; }}
  }}
  #board.valtas {{ animation: betunik 0.28s ease-out; }}
  #info {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    max-width: 480px;
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

<div id="board">{init_svg}</div>
<div id="info">
  <span id="statusz">&#9654; Betöltés…</span>
  <span id="lepesszam">Kezdőállás</span>
</div>

<audio id="narr" {autoplay_attr}
       src="data:audio/mpeg;base64,{mp3_data}"
       style="display:none"></audio>

<script>
// ── Adatok ────────────────────────────────────────────────────────────────
const fenSvgs   = {svgs_json};
const anchors   = {js_anchors};
const TOTAL     = fenSvgs.length;
// Lookahead: ennyi másodperccel KORÁBBAN jelenik meg az anchor állás,
// hogy a néző biztosan lássa, mielőtt a narrátor kimondja
const LOOKAHEAD = 0.5;

// ── DOM ───────────────────────────────────────────────────────────────────
const audio    = document.getElementById('narr');
const board    = document.getElementById('board');
const statusz  = document.getElementById('statusz');
const lepesszam = document.getElementById('lepesszam');

// ── Állapot ───────────────────────────────────────────────────────────────
let lastIdx    = 0;
let targetIdx  = 0;
let rafQueued  = false;
let befejezett = false;

// ── Lépésszám felirat ─────────────────────────────────────────────────────
function lepesFelirat(idx) {{
  if (idx === 0) return 'Kezdőállás';
  return idx + '. lépés / ' + (TOTAL - 1);
}}

// ── FEN-index számítás ────────────────────────────────────────────────────
// Lineáris interpoláció az anchor szinkronpontok között.
// frac: 0…1 (a lookahead-del eltolt audió-idő aránya)
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

// ── Villódzásmentes SVG csere (fade-IN animáció, soha nem üres a tábla) ──
function mutatFen(idx) {{
  idx = Math.max(0, Math.min(idx, TOTAL - 1));
  targetIdx = idx;
  if (!rafQueued && idx !== lastIdx) {{
    rafQueued = true;
    requestAnimationFrame(() => {{
      rafQueued = false;
      if (targetIdx === lastIdx) return;
      lastIdx = targetIdx;
      board.innerHTML = fenSvgs[lastIdx];
      // animation újraindítása: class levétel + reflow + visszarakás
      board.classList.remove('valtas');
      void board.offsetWidth;
      board.classList.add('valtas');
      lepesszam.textContent = lepesFelirat(lastIdx);
    }});
  }}
}}

// ── Audio eseménykezelők ──────────────────────────────────────────────────
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
  mutatFen(TOTAL - 1);          // biztosan az utolsó állás
  statusz.textContent = '⏸ Végállás – még látható…';
  setTimeout(() => {{
    statusz.textContent = '✓ Lejátszás befejezve.';
  }}, 3000);
}});

audio.addEventListener('error', () => {{
  statusz.textContent = '⚠ A hangfájl nem töltődött be.';
}});
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

if st.session_state.last_game != selected_name:
    st.session_state.playing = False
    st.session_state.last_game = selected_name

# ── Tartalom megjelenítése ────────────────────────────────────────────────────

narration_data = load_json(selected["json"])
paragraphs     = narration_data.get("paragraphs", [])

if st.session_state.playing:
    player_html = build_player_html(
        paragraphs,
        selected["mp3"],
        narration_data=narration_data,
        autoplay=True,
    )
    # Magasság: tábla (~480px) + info sor (~30px) + kis padding
    st.components.v1.html(player_html, height=540, scrolling=False)

    if st.button("⏹  Megállít", use_container_width=True):
        st.session_state.playing = False
        st.rerun()

else:
    # Álló mód: kezdőállás vagy az első anchor FEN-je
    all_fens = get_all_fens(narration_data, paragraphs)
    init_fen = all_fens[0] if all_fens else chess.STARTING_FEN
    svg = fen_to_svg(init_fen)
    st.components.v1.html(
        f'<div style="display:flex;justify-content:center">{svg}</div>',
        height=470,
        scrolling=False,
    )

    if st.button("▶  Lejátszás", use_container_width=True):
        st.session_state.playing = True
        st.rerun()
