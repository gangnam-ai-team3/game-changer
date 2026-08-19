import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    voyage_api_key: str
    database_url: str
    claim_extract_model: str = "claude-sonnet-5"
    claim_judge_model: str = "claude-sonnet-5"
    embedding_model: str = "voyage-3"
    top_n_candidates: int = 8
    judge_concurrency: int = 5


def get_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        voyage_api_key=os.environ["VOYAGE_API_KEY"],
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./audit.db"),
    )
