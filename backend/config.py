"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Secrets come only from .env — never hardcode keys."""

    model_config = SettingsConfigDict(
        # Support running from backend/ or repo root.
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    claude_model: str = Field(
        default="claude-sonnet-5-5",
        alias="CLAUDE_MODEL",
    )

    polygon_api_key: str = Field(default="", alias="POLYGON_API_KEY")

    alpaca_api_key: str = Field(default="", alias="ALPACA_API_KEY")
    alpaca_secret_key: str = Field(default="", alias="ALPACA_SECRET_KEY")
    alpaca_paper: bool = Field(default=True, alias="ALPACA_PAPER")

    # Live trading stays OFF unless explicitly enabled in .env (and other gates).
    # Env alone is NEVER enough — see services/live_gate.py.
    live_trading_enabled: bool = Field(default=False, alias="LIVE_TRADING_ENABLED")

    # AutoTrader dry-run defaults ON so a full day of decisions can be observed
    # before any paper orders are sent.
    auto_trader_dry_run: bool = Field(default=True, alias="AUTO_TRADER_DRY_RUN")

    database_url: str = Field(
        default="sqlite:///./rapidfire.db",
        alias="DATABASE_URL",
    )

    # External HTTP timeouts (seconds)
    http_timeout_seconds: float = 15.0
    quote_cache_ttl_seconds: int = 30


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
