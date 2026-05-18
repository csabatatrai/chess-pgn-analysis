"""
tts_client.py – Egységes TTS (szöveg-hang) hívási réteg.

Használat:
    from src.tts_client import generate_audio
    generate_audio("szöveg", "output/llm-analysis/openai_1.mp3")

A provider a config.py-ból jön (TTS_PROVIDER), de felülírható:
    generate_audio("szöveg", "output.mp3", provider="elevenlabs")
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def generate_audio(
    text: str,
    output_path: str,
    provider: str = None,
    voice: str = None,
    model: str = None,
    api_key: str = None,
) -> str:
    """
    Hangfájlt generál a megadott szövegből.

    Args:
        text:        Felolvasandó szöveg.
        output_path: Kimeneti MP3 fájl elérési útja.
        provider:    "openai" | "elevenlabs" – None = config.TTS_PROVIDER
        voice:       Hang neve / ID. None = provider alapértelmezése.
        model:       TTS modell neve. None = provider alapértelmezése.
        api_key:     Felülírja a config API kulcsát.

    Returns:
        A kimeneti fájl elérési útja.
    """
    provider = provider or config.TTS_PROVIDER
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if provider == "openai":
        key = api_key or config.CHAT_GPT_API_KEY
        if not key:
            raise ValueError(
                "Nincs OpenAI API kulcs. Töltsd ki a secrets.py CHAT_GPT_API_KEY mezőjét."
            )
        _openai_tts(
            text, output_path, key,
            voice or config.TTS_VOICE_OPENAI,
            model or config.TTS_MODEL_OPENAI,
        )

    elif provider == "elevenlabs":
        key = api_key or config.ELEVENLABS_API_KEY
        if not key:
            raise ValueError(
                "Nincs ElevenLabs API kulcs. Töltsd ki a secrets.py ELEVENLABS_API_KEY mezőjét."
            )
        _elevenlabs_tts(text, output_path, key, voice or config.TTS_VOICE_ELEVENLABS)

    else:
        raise ValueError(
            f"Ismeretlen TTS provider: '{provider}'. "
            "Érvényes értékek: openai, elevenlabs"
        )

    return output_path


# ── Provider implementációk ────────────────────────────────────────────────────

def _openai_tts(text: str, output_path: str, api_key: str, voice: str, model: str) -> None:
    """OpenAI TTS API – tts-1 / tts-1-hd modell, MP3 kimenet."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    response = client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
    )
    response.stream_to_file(output_path)


def _elevenlabs_tts(text: str, output_path: str, api_key: str, voice_id: str) -> None:
    """ElevenLabs TTS API – eleven_multilingual_v2 modell, MP3 kimenet."""
    from elevenlabs.client import ElevenLabs
    client = ElevenLabs(api_key=api_key)
    audio_stream = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
    )
    with open(output_path, "wb") as f:
        for chunk in audio_stream:
            f.write(chunk)
