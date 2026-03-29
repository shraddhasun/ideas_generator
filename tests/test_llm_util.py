from ideas_generator.config import Settings
from ideas_generator.llm_util import llm_screen_enabled


def test_llm_screen_openai_key():
    assert llm_screen_enabled(Settings(openai_api_key="sk-x", llm_provider="openai"))


def test_llm_screen_gemini_key():
    assert llm_screen_enabled(
        Settings(llm_provider="gemini", gemini_api_key="g-x", openai_api_key=None)
    )


def test_llm_screen_disabled_without_key():
    assert not llm_screen_enabled(Settings(llm_provider="openai", openai_api_key=None))


def test_bare_openai_api_key_in_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-bare-env")
    monkeypatch.delenv("IDEAS_OPENAI_API_KEY", raising=False)
    s = Settings(openai_api_key=None)
    assert s.openai_api_key == "sk-from-bare-env"


def test_bare_gemini_api_key_in_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-from-bare-env")
    monkeypatch.delenv("IDEAS_GEMINI_API_KEY", raising=False)
    s = Settings(gemini_api_key=None)
    assert s.gemini_api_key == "g-from-bare-env"
