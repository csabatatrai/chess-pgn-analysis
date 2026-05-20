"""
narrator.py – Közös LLM narrációs logika.

A Streamlit app és a notebook is ezt használja, hogy egységes,
ellentmondásmentes szöveget kapjon.

Használat:
    from src.narrator import generate_narration
    narration_json = generate_narration(game_data, evaluations)

game_data mezők: white, black, result, eco, opening, white_elo, black_elo
evaluations: lista, elemenként: move_number, color, san, cp, mate, fen
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.llm_client import generate_text

_MAX_RETRIES = 2


def _broken_anchors(narration: dict) -> list[str]:
    """Visszaadja azokat a trigger_word-öket, amelyek nem szerepelnek szó szerint
    a saját bekezdésük 'text' mezőjében."""
    broken = []
    for para in narration.get("paragraphs", []):
        text = para.get("text", "")
        for anchor in para.get("anchors", []):
            tw = anchor.get("trigger_word", "")
            if tw and tw not in text:
                broken.append(tw)
    return broken


def _parse_llm_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    return json.loads(raw)


NARRATION_SYSTEM_PROMPT = """\
You are a passionate English-speaking chess commentator and coach.

## Your goal:
Walk through the game move by move with instructive explanations. The listener can see the board —
so every move you mention must have an anchor (details below).
Always explain briefly WHY a move was good or bad.

## Style — this is the most important part:
Write as if you are commentating live: enthusiastic, natural English sentences, not textbook prose.
Avoid monotonous patterns like:
  ✗ "White played Y on move X, which secures Z."
  ✓ "White slides the piece to Y — and suddenly the door to Z swings wide open."

Sentence structure:
- Alternate short, punchy sentences with longer explanatory ones.
- Use active verbs: "lunges", "retreats", "pounces", "tears open the position".
- Connectives that keep the commentary alive: yet, meanwhile, now, suddenly, however,
  and yet, of course, brilliantly, but here's the thing.
- Evaluative remarks are encouraged: "A serious blunder.", "Excellent decision!", "A surprising move."

## Chess terminology to use:
- opening: the first ~10 moves; goal is piece development, center control, castling
- center: the e4, d4, e5, d5 squares — whoever controls them controls the game
- development: moving pieces from their starting squares to active positions in the opening
- castling: securing the king (kingside = short castle; queenside = long castle)
- fork: one piece attacks two enemy pieces simultaneously
- pin: a piece is pinned when moving it would expose a more valuable piece behind it
- skewer: attacking a valuable piece and winning the less valuable one behind it
- positional advantage: long-term structural edge (weak squares, rooks on open files)
- turning point (★): where the cp value shifts by at least 100 in a single move
- mating threat: a move or sequence that puts checkmate directly on the agenda

## Stockfish cp value interpretation (from White's perspective; positive = White is better):
- |cp| < 50:   equal position
- 50–150:      slight advantage
- 150–300:     significant advantage
- > 300:       decisive superiority
- mate != null: mating threat on the board

## Stockfish best-move annotation [Stockfish: X]:
When a move has a [Stockfish: X] annotation, it means Stockfish (single-thread, depth 6)
suggested X as a stronger alternative. Important nuances to keep in mind:
- Chess positions often have MULTIPLE equally good moves; X is one strong option, not
  necessarily the only correct continuation.
- Use X as a reference point for your explanation ("a move like X would have kept the
  balance" / "defending with X was the engine's idea"), but do NOT present it as the
  one and only truth — a different move could be equally valid.
- Never read out the algebraic notation of X in the narration text (TTS rule); instead
  describe it: "a rook retreat to d1", "pushing the pawn to e5", etc.

## Mandatory move description (for TTS — never write algebraic notation):
- Nxe5   → knight takes e5
- Rxh7   → rook takes h7
- Bxf6   → bishop takes f6
- Qd8+   → queen to d8, check
- O-O    → kingside castling
- O-O-O  → queenside castling
- e4     → pawn to e4
- exd5   → pawn takes d5

## Narration structure — DYNAMIC (scaled to game length):

You receive a "Target: ~N words" value and moves marked ★ at turning points.
Write 3–5 paragraphs following these principles:

1. **Opening** (first ~8 moves): Name the opening by ECO. Comment on piece development,
   the battle for the center — highlight any unusual move by either side.
2. **Middlegame** (from move 8): Go through moves IN ORDER. For each key move,
   a brief instructive note: why was it good, or what was the better option?
3. **Turning point(s)** (the ★ moves): Explain the turning point in detail — what was the
   mistake, what was the correct continuation, which chess principle does it violate?
4. **Final moves + lesson**: Always comment on the last 2–3 moves.
   Close with a specific, actionable chess principle (not a generic one).

Word count: aim for the given target (±20%). Shorter game = fewer paragraphs is fine.

## CRITICAL — trigger_word and anchor rules (visual sync depends on this!):

1. **Exact match**: the trigger_word is the EXACT same text that appears in the "text" field —
   COPY-PASTE, never paraphrase, never shorten!
   Even a single character difference (punctuation, capitalisation) breaks the sync.

2. **Length**: at least 4 words, at most 8 words.

3. **Uniqueness**: the trigger_word must not appear twice in the full narration.
   If a phrase would repeat, add surrounding words to make it unique.

4. **Precise position**: the trigger_word marks the passage where you ACTIVELY INTRODUCE
   the move — the very first sentence in which you mention it.

5. **Order**: trigger_words in the anchors array must appear in the SAME ORDER
   as they appear in the "text" field (top to bottom).

6. **Completeness — MANDATORY**: Every move you specifically mention needs an anchor.
   Density rule: count the distinct moves you name in each paragraph → provide
   at least ⌈count / 2⌉ anchors (round up). Examples: 2 moves → min 1 anchor;
   4 moves → min 2 anchors; 5 moves → min 3 anchors.
   The last 2–3 moves of the game MUST always be anchored — no exceptions.

7. **Forward-only anchors**: Anchors must strictly advance forward through the game.
   Each anchor's fen must belong to a position LATER than the previous anchor's fen.
   If you refer back to an earlier moment ("as we saw on move X"), express it in text
   only — do NOT create an anchor for it. Backward anchors are silently discarded by
   the player and break the visual sync.

8. **FEN source**: Always copy the fen value from the input "fen:" field — never compute it!

## Output — VALID JSON ONLY, no preamble, no markdown code block:
{
  "paragraphs": [
    {
      "text": "Paragraph text — natural, live commentator style.",
      "anchors": [
        {"fen": "<FEN after this move>", "trigger_word": "<verbatim quote from text>"}
      ]
    }
  ]
}
"""


def generate_narration(game_data: dict, evaluations: list) -> dict:
    """
    LLM-mel narrációt generál egy sakkjátszma Stockfish-elemzéséből.

    A TÉNYEK blokk explicit rögzíti a győztest és a legsúlyosabb hibát,
    így az LLM nem mondhat ellent a Stockfish-adatoknak (pl. nem írhatja
    le vesztesként a győztest).

    Args:
        game_data:   dict – white, black, result, eco, opening, white_elo, black_elo
        evaluations: list – lépésenkénti Stockfish-elemzés
                     (move_number, color, san, cp, mate, fen)

    Returns:
        dict – {"paragraphs": [...]} JSON struktúra
    """
    n = len(evaluations)
    white  = game_data["white"]
    black  = game_data["black"]
    result = game_data.get("result", "*")

    # Cp-különbségek lépésenként (fehér nézőpontjából: pozitív = fehér javára mozdult)
    diffs = []
    for i, e in enumerate(evaluations):
        cp_now  = e.get("cp") or 0
        cp_prev = (evaluations[i - 1].get("cp") or 0) if i > 0 else cp_now
        diffs.append(cp_now - cp_prev)

    # Blame: az a fél hibázott, akinek lépése után az ellenfél relatív helyzete javult.
    #   Fekete lép → cp NŐ (fehér javára) → fekete rontott
    #   Fehér lép  → cp CSÖKKEN (fekete javára) → fehér rontott
    # 80 cp alatt természetes ingadozás, nem minősítjük hibának.
    BLAME_THRESHOLD = 80

    def blame(i: int):
        color = evaluations[i]["color"]
        d = diffs[i]
        if color == "black" and d > BLAME_THRESHOLD:
            return f"{black} (fekete) HIBÁJA"
        if color == "white" and d < -BLAME_THRESHOLD:
            return f"{white} (fehér) HIBÁJA"
        return None

    # Fordulópont: az első 5 lépést kizárjuk (megnyitásbeli ingadozások)
    turning_idx = max(range(min(5, n), n), key=lambda i: abs(diffs[i]), default=n - 1)

    # Célszóhossz: ~12 szó/lépés, min 250, max 650
    target_words = max(250, min(650, n * 12 + 50))

    # Győztes/vesztes szövegesen
    if result == "1-0":
        winner_str = f"{white} (fehér) nyert"
        loser_str  = f"{black} (fekete) veszített"
    elif result == "0-1":
        winner_str = f"{black} (fekete) nyert"
        loser_str  = f"{white} (fehér) veszített"
    else:
        winner_str = loser_str = "döntetlen vagy befejezetlen"

    # A legsúlyosabb hibák (az 5. lépéstől, delta szerint csökkentően)
    blunders = [
        (i, evaluations[i], diffs[i], blame(i))
        for i in range(min(5, n), n)
        if blame(i)
    ]
    blunders.sort(key=lambda x: abs(x[2]), reverse=True)

    # TÉNYEK blokk: ezeket az LLM nem vitathatja
    facts_lines = [f"Eredmény: {result} → {winner_str}."]
    if blunders:
        i0, e0, d0, b0 = blunders[0]
        move_str = f"{e0['move_number']}{'...' if e0['color'] == 'black' else '.'}{e0['san']}"
        facts_lines.append(
            f"Legsúlyosabb hiba: {move_str} – {b0} (cp: {abs(d0):.0f} pont elmozdulás)."
        )
    facts_block = "\n".join(facts_lines)

    # Lépéslista blame-annotációkkal
    lines = []
    for i, e in enumerate(evaluations):
        move_num = e["move_number"]
        dots     = "..." if e["color"] == "black" else "."
        san      = e["san"]
        cp       = e.get("cp")
        mate     = e.get("mate")
        d        = diffs[i]

        cp_str    = f"matt {mate:+d}" if mate is not None else (f"{cp:+d} cp" if cp is not None else "? cp")
        delta_str = f" (Δ{abs(d):.0f})" if abs(d) > 0 else ""
        blame_str = f" ← {blame(i)}" if blame(i) else ""

        best_san  = e.get("best_move_san")
        best_str  = f" [Stockfish: {best_san}]" if best_san and blame(i) else ""

        marker = " ★FORDULÓPONT" if i == turning_idx else ""
        tag    = (" [MEGNYITÁS]" if move_num <= 8
                  else " [UTOLSÓ LÉPÉSEK]" if i >= n - 3
                  else "")

        lines.append(
            f"{move_num}{dots}{san}: {cp_str}{delta_str}{blame_str}{best_str}{marker}{tag} | fen: {e['fen']}"
        )

    user_prompt = (
        f"ECO: {game_data.get('eco', '?')} – {game_data.get('opening', '')}\n"
        f"Fehér: {white} ({game_data.get('white_elo', '?')}), "
        f"Fekete: {black} ({game_data.get('black_elo', '?')})\n"
        f"Összes lépés: {n} | Cél: ~{target_words} szó\n\n"
        "## TÉNYEK – a narráció NEM mondhat ezeknek ellent:\n"
        f"{facts_block}\n\n"
        "## Lépések\n"
        "(Jelölés: cp Δeltérés ← hibás játékos ha van | fen)\n"
        "Szabály: ha cp NŐ, az a LÉPŐ FEKETE hibája. Ha cp CSÖKKEN, az a LÉPŐ FEHÉR hibája.\n\n"
        + "\n".join(lines)
    )

    prompt = user_prompt
    result = None

    for attempt in range(_MAX_RETRIES + 1):
        raw = generate_text(prompt, system_prompt=NARRATION_SYSTEM_PROMPT)
        try:
            result = _parse_llm_json(raw)
        except json.JSONDecodeError:
            if attempt < _MAX_RETRIES:
                prompt = (
                    user_prompt
                    + f"\n\n## RETRY {attempt + 2}/{_MAX_RETRIES + 1} — JSON PARSE ERROR\n"
                    "Your previous response was not valid JSON. "
                    "Output ONLY the JSON object — no preamble, no markdown fences."
                )
                continue
            raise

        broken = _broken_anchors(result)
        if not broken:
            return result

        if attempt < _MAX_RETRIES:
            broken_lines = "\n".join(f'  • "{tw}"' for tw in broken)
            prompt = (
                user_prompt
                + f"\n\n## RETRY {attempt + 2}/{_MAX_RETRIES + 1} — BROKEN ANCHORS\n"
                f"{len(broken)} trigger_word(s) were NOT found verbatim in their paragraph text:\n"
                f"{broken_lines}\n\n"
                "Fix rules:\n"
                "  1. COPY-PASTE the trigger_word character-perfect from the 'text' field.\n"
                "  2. Do NOT edit the text to match — fix the trigger_word to match the text.\n"
                "  3. Every anchor must reference a position LATER in the game than the previous anchor.\n"
                "Regenerate the complete narration JSON with all anchors corrected."
            )
        else:
            print(
                f"[narrator] Warning: {len(broken)} broken anchor(s) remain after "
                f"{_MAX_RETRIES} retries: {broken}"
            )

    return result
