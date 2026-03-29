import pytest


@pytest.fixture(autouse=True)
def _isolate_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a developer shell or .env from turning on LLM filters in unit tests."""
    for key in (
        "OPENAI_API_KEY",
        "IDEAS_OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "IDEAS_GEMINI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
