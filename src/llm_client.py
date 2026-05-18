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
    system_prompt: str = None,
    provider: str = None,
    api_key: str = None,
    model: str = None,
) -> str:
    """
    Szöveget generál a konfigurált LLM providerrel.

    Args:
        prompt:        Felhasználói tartalom (user üzenet).
        system_prompt: Rendszerszintű instrukció (system üzenet). None = nincs külön system prompt.
        provider:      "openai" | "gemini" | "anthropic" | "mistral" – None = config.LLM_PROVIDER
        api_key:       Felülírja a config.LLM_API_KEY értékét.
        model:         Felülírja a config.LLM_MODEL értékét.

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
        return _openai(prompt, api_key, model or "gpt-4o-mini", system_prompt)
    if provider == "gemini":
        return _gemini(prompt, api_key, model or "gemini-2.0-flash-lite", system_prompt)
    if provider == "anthropic":
        return _anthropic(prompt, api_key, model or "claude-haiku-4-5-20251001", system_prompt)
    if provider == "mistral":
        return _mistral(prompt, api_key, model or "mistral-small-latest", system_prompt)

    raise ValueError(
        f"Ismeretlen LLM provider: '{provider}'. "
        "Érvényes értékek: openai, gemini, anthropic, mistral"
    )


# ── Provider implementációk ────────────────────────────────────────────────────

def _openai(prompt: str, api_key: str, model: str, system_prompt: str = None) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"} if system_prompt and "JSON" in system_prompt else None,
    )
    return response.choices[0].message.content


def _gemini(prompt: str, api_key: str, model: str, system_prompt: str = None) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)
    config_kwargs = {}
    if system_prompt:
        config_kwargs["system_instruction"] = system_prompt
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs) if config_kwargs else None,
    )
    return response.text


def _anthropic(prompt: str, api_key: str, model: str, system_prompt: str = None) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    kwargs = {
        "model": model,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    message = client.messages.create(**kwargs)
    return message.content[0].text


def _mistral(prompt: str, api_key: str, model: str, system_prompt: str = None) -> str:
    from mistralai import Mistral
    client = Mistral(api_key=api_key)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    response = client.chat.complete(
        model=model,
        messages=messages,
    )
    return response.choices[0].message.content
