"""Application configuration — the single source of truth for environment-driven settings.

Every other module reads configuration through `get_settings()`, never through `os.environ`
directly. This keeps the domain and application layers free of environment coupling, and
gives tests one seam to override. See architecture doc §4 (infrastructure layer).
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App -------------------------------------------------------------------
    app_env: str = Field(default="local", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Database ----------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://bridge_ai:bridge_ai@localhost:5432/bridge_ai",
        alias="DATABASE_URL",
    )

    # --- Featherless (OpenAI-compatible LLM) — consumed by
    # app/integrations/llm/featherless_client.py, scoped to the four permitted LLM tasks only.
    featherless_api_key: str = Field(default="", alias="FEATHERLESS_API_KEY")
    featherless_base_url: str = Field(
        default="https://api.featherless.ai/v1", alias="FEATHERLESS_BASE_URL"
    )
    featherless_model: str = Field(default="", alias="FEATHERLESS_MODEL")
    # Featherless's recommended attribution headers (Part 5) — both optional; a blank referer
    # is intentionally valid (FeatherlessClient omits the header rather than sending "").
    featherless_http_referer: str = Field(default="", alias="FEATHERLESS_HTTP_REFERER")
    featherless_x_title: str = Field(default="Bridge AI", alias="FEATHERLESS_X_TITLE")

    # --- LLM request tuning — shared across all Featherless-backed LLM calls --------
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=2048, alias="LLM_MAX_TOKENS")
    llm_timeout_seconds: int = Field(default=60, alias="LLM_TIMEOUT_SECONDS")
    # Bounded exponential backoff for transient Featherless failures (429/5xx/timeouts) —
    # FeatherlessClient never retries malformed model output, only transport/server failures.
    llm_max_retries: int = Field(default=3, alias="LLM_MAX_RETRIES")
    llm_retry_backoff_seconds: float = Field(default=1.0, alias="LLM_RETRY_BACKOFF_SECONDS")

    # --- Caspian SDK (Phase 6.6) — consumed by app/integrations/real_caspian_client.py and
    # app/infrastructure/caspian_poller.py. `caspian_api_key` empty means production falls
    # back to LocalCaspianClient (see di_container.build_container) rather than failing
    # startup — the same "degrade, don't fail" posture as an out-of-pack policy topic.
    caspian_api_key: str = Field(default="", alias="CASPIAN_API_KEY")
    caspian_base_url: str = Field(default="", alias="CASPIAN_BASE_URL")
    """Blank uses caspian_sdk.CommClient's own default (https://api.trycaspianai.com)."""
    caspian_workspace_id: str = Field(default="", alias="CASPIAN_WORKSPACE_ID")
    """Not read by the real caspian-sdk's connection model (there is no workspace concept in
    its API — see client.py) — kept for a future multi-workspace need, unused today."""
    caspian_email_username: str = Field(default="", alias="CASPIAN_EMAIL_USERNAME")
    """Optional readable mailbox name (e.g. "bridge-ai" -> bridge-ai@agents.trycaspianai.com)
    passed to connect_email(); blank lets Caspian assign one."""
    caspian_inbound_poll_interval_seconds: int = Field(
        default=5, alias="CASPIAN_INBOUND_POLL_INTERVAL_SECONDS"
    )

    # --- Channels — read by channel adapters, not wired yet --------------------------
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    email_smtp_host: str = Field(default="", alias="EMAIL_SMTP_HOST")
    email_smtp_port: int = Field(default=587, alias="EMAIL_SMTP_PORT")
    email_smtp_username: str = Field(default="", alias="EMAIL_SMTP_USERNAME")
    email_smtp_password: str = Field(default="", alias="EMAIL_SMTP_PASSWORD")
    email_from_address: str = Field(default="", alias="EMAIL_FROM_ADDRESS")

    # --- Follow-up scheduler (Part 8) — infrastructure/scheduler.py -----------------
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_interval_seconds: int = Field(default=60, alias="SCHEDULER_INTERVAL_SECONDS")

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton — env parsing happens once per process."""
    return Settings()
