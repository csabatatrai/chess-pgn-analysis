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


NARRATION_SYSTEM_PROMPT = """\
Te egy szenvedélyes magyar sakkkommentátor és edző vagy.

## Célod:
Lépésről lépésre végigkísérni a játszmát, oktatói magyarázatokkal. A hallgató a táblán is látja,
amiről szó van – ezért minden említett lépésnél anchor szükséges (erről lentebb).
Mindig mondd el röviden, MIÉRT volt jó vagy rossz az adott húzás.

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
- fordulópont (★): ahol a cp érték legalább 100-at változik egy lépésen belül
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

## A narráció szerkezete – DINAMIKUS (a játszma hosszához igazítva):

Kapsz egy "Cél: ~N szó" értéket és lépéseket ★ jelöléssel a fordulópontoknál.
Írj 3–5 bekezdést az alábbi elvek szerint:

1. **Megnyitás** (az első ~8 lépés): Nevezd meg a megnyitást ECO alapján. Kommentáld a figurák
   fejlesztését, a centrumharcot – emeld ki, ha valamelyik fél szokatlan húzást tesz.
2. **Középjáték** (8. lépéstől): Haladj SORBAN lépésről lépésre. Minden fontosabb húzásnál
   egy rövid oktatói megjegyzés: miért volt jó, vagy hol volt jobb lehetőség?
3. **Döntő pillanat(ok)** (a ★ lépések): Részletesen magyarázd a fordulópontot – mi volt a hiba,
   mi lett volna a helyes folytatás, milyen sakkelvbe ütközik?
4. **Végső lépések + tanulság**: Az utolsó 2-3 lépést mindenképpen kommentáld.
   Zárj egy konkrét, alkalmazható sakkelvvel (ne legyen általános).

Szóhossz: törekedj a megadott célra (±20%). Ha rövid a játszma, kevesebb bekezdés is elég.

## KRITIKUS – trigger_word és anchor szabályok (a vizuális szinkronizáció ettől függ!):

1. **Szó szerinti egyezés**: a trigger_word PONTOSAN UGYANAZ a szövegrész, amely a "text" mezőben
   szerepel – COPY-PASTE, soha nem parafrazálás, soha nem rövidítés!
   Egyetlen betűnyi eltérés (ékezet, nagy/kisbetű) is megakadályozza a szinkronizációt.

2. **Hossz**: legalább 4, legfeljebb 8 szó.

3. **Egyediség**: a trigger_word ne forduljon elő kétszer a teljes narráción belül.
   Ha egy kifejezés megismétlődne, adj hozzá környező szavakat, hogy egyedi legyen.

4. **Pontos helyzet**: a trigger_word AZT a szövegrészt jelölje, ahol az adott lépést
   AKTÍVAN BEVEZETED – a legelső mondat, amelyben a lépést megemlíted.

5. **Sorrend**: az anchors tömbben a trigger_word-ök UGYANOLYAN SORRENDBEN kövessék egymást,
   ahogy a "text" mezőben megjelennek (felülről lefelé haladva).

6. **Teljesség – KÖTELEZŐ**: Minden bekezdésben MINDEN EGYES konkrétan említett lépésnél
   anchor kell. Ha megemlítesz egy lépést, de nem horgányozod le, a tábla nem mozdul – a néző
   elveszíti a fonalat. Különösen fontos: az utolsó 2-3 lépés MINDIG legyen lehorgányozva.

7. **FEN forrása**: A fen értéket MINDIG az input "fen:" sorából másold – soha ne számold ki!

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

        marker = " ★FORDULÓPONT" if i == turning_idx else ""
        tag    = (" [MEGNYITÁS]" if move_num <= 8
                  else " [UTOLSÓ LÉPÉSEK]" if i >= n - 3
                  else "")

        lines.append(
            f"{move_num}{dots}{san}: {cp_str}{delta_str}{blame_str}{marker}{tag} | fen: {e['fen']}"
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

    raw = generate_text(user_prompt, system_prompt=NARRATION_SYSTEM_PROMPT)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    return json.loads(raw)
