"""
llm_client.py – Egységes LLM hívási réteg.

Használat:
    from src.llm_client import generate_text
    narration = generate_text("prompt szöveg")

A provider és modell a config.py-ból jön (LLM_PROVIDER, LLM_MODEL),
de híváskor felülírható:
    generate_text("prompt", provider="gemini", model="gemini-2.0-flash-lite")
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def generate_text(
    prompt: str,
    provider: str = None,
    api_key: str = None,
    model: str = None,
) -> str:
    """
    Szöveget generál a konfigurált LLM providerrel.

    Args:
        prompt:   A teljes prompt (rendszerüzenet + felhasználói tartalom egyben).
        provider: "openai" | "gemini" | "anthropic" | "mistral" – None = config.LLM_PROVIDER
        api_key:  Felülírja a config.LLM_API_KEY értékét.
        model:    Felülírja a config.LLM_MODEL értékét.

    Returns:
        A modell szöveges válasza.
    """
    provider = provider or config.LLM_PROVIDER
    api_key  = api_key  or config.LLM_API_KEY
    model    = model    or config.LLM_MODEL

    if not api_key:
        raise ValueError(
            f"Nincs API kulcs a '{provider}' providerhez. "
            "Töltsd ki a secrets.py-t, vagy állítsd be a megfelelő env változót."
        )

    if provider == "openai":
        return _openai(prompt, api_key, model or "gpt-4o-mini")
    if provider == "gemini":
        return _gemini(prompt, api_key, model or "gemini-2.0-flash-lite")
    if provider == "anthropic":
        return _anthropic(prompt, api_key, model or "claude-haiku-4-5-20251001")
    if provider == "mistral":
        return _mistral(prompt, api_key, model or "mistral-small-latest")

    raise ValueError(
        f"Ismeretlen LLM provider: '{provider}'. "
        "Érvényes értékek: openai, gemini, anthropic, mistral"
    )


# ── Provider implementációk ────────────────────────────────────────────────────

def _openai(prompt: str, api_key: str, model: str) -> str:
    from openai import OpenAI
    client   = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def _gemini(prompt: str, api_key: str, model: str) -> str:
    from google import genai
    client   = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text


def _anthropic(prompt: str, api_key: str, model: str) -> str:
    import anthropic
    client   = anthropic.Anthropic(api_key=api_key)
    message  = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _mistral(prompt: str, api_key: str, model: str) -> str:
    from mistralai import Mistral
    client   = Mistral(api_key=api_key)
    response = client.chat.complete(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
