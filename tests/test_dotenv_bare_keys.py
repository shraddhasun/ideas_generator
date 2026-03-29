from ideas_generator.config import get_settings


def test_openai_key_in_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-from-dotenv-file\n", encoding="utf-8")
    s = get_settings()
    assert s.openai_api_key == "sk-from-dotenv-file"
