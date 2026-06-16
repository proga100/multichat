"""
Central configuration — the single source of truth for all settings.

Everything tunable (keys, model names, ports, synthesis choice) is loaded here
from the .env file into a typed object. The rest of the app imports `settings`
and never reads os.environ directly. To change a model, edit .env — not code.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Provider API keys (BYOK)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Model selection — default (mid-tier) vs premium, per provider.
    anthropic_model_default: str = "claude-sonnet-4-6"
    anthropic_model_premium: str = "claude-opus-4-8"
    anthropic_max_tokens: int = 1024
    openai_model_default: str = "gpt-5-mini"
    openai_model_premium: str = "gpt-5"
    gemini_model_default: str = "gemini-2.5-flash"
    gemini_model_premium: str = "gemini-2.5-pro"

    # Debate-mode synthesis: which provider writes the final combined answer.
    synthesis_provider: str = "anthropic"

    # Telegram (step 8)
    telegram_bot_token: str = ""
    telegram_allowed_user_id: int | None = None

    # Storage / server
    database_path: str = "./multichat.db"
    host: str = "127.0.0.1"
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env is parsed once per process."""
    return Settings()


settings = get_settings()
