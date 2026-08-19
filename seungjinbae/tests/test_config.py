from app.config import get_settings


def test_get_settings_reads_required_env_and_defaults(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-123")
    monkeypatch.setenv("VOYAGE_API_KEY", "vk-456")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = get_settings()

    assert settings.anthropic_api_key == "ak-123"
    assert settings.voyage_api_key == "vk-456"
    assert settings.database_url == "sqlite:///./audit.db"
    assert settings.claim_extract_model == "claude-sonnet-5"
    assert settings.claim_judge_model == "claude-sonnet-5"
    assert settings.embedding_model == "voyage-3"
    assert settings.top_n_candidates == 8
    assert settings.judge_concurrency == 5


def test_get_settings_reads_database_url_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-123")
    monkeypatch.setenv("VOYAGE_API_KEY", "vk-456")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")

    settings = get_settings()

    assert settings.database_url == "postgresql://x/y"
