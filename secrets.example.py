"""
secrets.example.py – Sablon az API kulcsokhoz.
Másold le secrets.py néven, és töltsd ki a saját kulcsaiddal.
A secrets.py fájl NEM kerül verziókövetésbe.

A config.py-ban a LLM_PROVIDER változóval választható ki, melyik kulcsot
használja a rendszer: "openai" | "gemini" | "anthropic" | "mistral"
"""

# ── Nyelvi modellek ────────────────────────────────────────────────────────────
CHAT_GPT_API_KEY   = "ide_az_openai_kulcs"       # platform.openai.com/api-keys
GEMINI_API_KEY     = "ide_a_gemini_kulcs"         # aistudio.google.com/apikey
ANTHROPIC_API_KEY  = "ide_az_anthropic_kulcs"     # console.anthropic.com/settings/keys
MISTRAL_API_KEY    = "ide_a_mistral_kulcs"        # console.mistral.ai/api-keys

# ── Hang (TTS) ─────────────────────────────────────────────────────────────────
ELEVENLABS_API_KEY = "ide_az_elevenlabs_kulcs"    # elevenlabs.io/app/settings/api-keys
