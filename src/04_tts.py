#!/usr/bin/env python3
"""
04_tts.py
─────────
Pipeline 4. lépés: LLM-narráció szövegfájlból hangfájl generálása TTS-sel.

A fájlnév-egyezmény:
  Bemenet:  output/llm-analysis/{llm_provider}_{game_number}.txt
  Kimenet:  output/llm-analysis/{llm_provider}_{game_number}.mp3

Futtatás:
  python src/04_tts.py                              # config.py alapján
  python src/04_tts.py --game 2                     # 2. játszma
  python src/04_tts.py --provider elevenlabs        # TTS provider felülírása
  python src/04_tts.py --input output/llm-analysis/openai_1.txt
  python src/04_tts.py --voice onyx                 # OpenAI hang felülírása
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.tts_client import generate_audio


def run_tts(
    input_file: str = None,
    output_file: str = None,
    tts_provider: str = None,
    game_number: int = None,
    voice: str = None,
) -> str | None:
    """Hangfájlt generál az LLM elemzés szövegéből."""
    gn = game_number or config.GAME_NUMBER
    provider = tts_provider or config.TTS_PROVIDER

    if input_file is None:
        input_file = os.path.join(
            config.LLM_ANALYSIS_DIR,
            f"{config.LLM_PROVIDER}_{gn}.txt"
        )

    if not os.path.exists(input_file):
        print(f"⚠️  Elemzés fájl nem található: {input_file}")
        print("   Előbb generálj LLM-narrációt.")
        return None

    with open(input_file, encoding="utf-8") as f:
        text = f.read().strip()

    if not text:
        print(f"⚠️  Üres szövegfájl: {input_file}")
        return None

    if output_file is None:
        base = os.path.splitext(input_file)[0]
        output_file = base + ".mp3"

    print(f"\n🔊 TTS generálás")
    print(f"   Provider:  {provider}")
    print(f"   Bemenet:   {input_file}")
    print(f"   Kimenet:   {output_file}")
    print(f"   Karakterek: {len(text)}")

    generate_audio(text, output_file, provider=provider, voice=voice)

    size_kb = os.path.getsize(output_file) / 1024
    print(f"\n✅ Hangfájl kész! → {output_file} ({size_kb:.1f} KB)")
    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TTS hangfájl generálás LLM elemzésből.")
    parser.add_argument("--input", help="Bemeneti szövegfájl (.txt)")
    parser.add_argument("--output", help="Kimeneti hangfájl (.mp3)")
    parser.add_argument("--provider", help="TTS provider: openai | elevenlabs")
    parser.add_argument("--game", type=int, help="Játszma sorszáma (alapért.: GAME_NUMBER config)")
    parser.add_argument("--voice", help="Hang neve/ID (OpenAI: nova/onyx/alloy/..., ElevenLabs: voice_id)")
    args = parser.parse_args()

    run_tts(
        input_file=args.input,
        output_file=args.output,
        tts_provider=args.provider,
        game_number=args.game,
        voice=args.voice,
    )
