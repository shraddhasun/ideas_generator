from __future__ import annotations

from ideas_generator.config import Settings


def llm_screen_enabled(settings: Settings) -> bool:
    """True when `ideas llm-screen` should filter clustering (provider + key present)."""
    if settings.llm_provider == "gemini":
        return bool((settings.gemini_api_key or "").strip())
    return bool((settings.openai_api_key or "").strip())
