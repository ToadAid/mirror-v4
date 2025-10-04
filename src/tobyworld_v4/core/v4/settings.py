from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    APP_NAME: str = "Mirror V4"
    SCROLLS_DIR: str = "lore-scrolls"
    WEB_DIR: str = "web"
    LEDGER_DB: str = "mirror-v4.db"
    HARMONY_THRESHOLD: float = Field(0.7, ge=0.0, le=1.0)

    # flags
    TEMPORAL_CONTEXT: bool = True
    CONVERSATION_WEAVE: bool = True
    SYMBOL_RESONANCE: bool = False
    SHOW_SOURCES: bool = False
    DISABLE_STARTUP_INDEX: bool = False

    # metrics
    PROMETHEUS_MULTIPROC_DIR: str | None = None

    # LLM
    MIRROR_LLM_ENABLED: int = 1
    LLM_BASE_URL: str | None = None
    LLM_MODEL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_TIMEOUT_SECS: int = 45

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

SETTINGS = Settings()
