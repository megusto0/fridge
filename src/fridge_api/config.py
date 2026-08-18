from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FRIDGE_",
        extra="ignore",
    )

    database_url: str = "sqlite:///./data/fridge.db"
    auto_create_schema: bool = True
    app_name: str = "Fridge backend"
    environment: str = "development"
    upload_directory: str = "./data/uploads"
    upload_max_bytes: int = 10 * 1024 * 1024
    web_ui_directory: str = "./web_ui"
    mockup_directory: str = "./web_ui"
    open_food_facts_base_url: str = "https://world.openfoodfacts.org"
    open_food_facts_user_agent: str = (
        "FridgeBackend/0.1 (personal food inventory; https://glucoscope.ru)"
    )
    enrichment_http_timeout_seconds: float = 20.0
    enrichment_poll_seconds: float = 60.0
    enrichment_reference_food_fallback: bool = True
    enrichment_yandex_eda_fallback: bool = True
    enrichment_hermes_fallback: bool = True
    enrichment_hermes_bin: str = "/home/megusto/.local/bin/hermes"
    enrichment_hermes_timeout_seconds: float = 240.0
    naming_hermes_timeout_seconds: float = 90.0

    def prepare_local_directories(self) -> None:
        if self.database_url.startswith("sqlite:///./"):
            raw = self.database_url.removeprefix("sqlite:///./")
            Path(raw).parent.mkdir(parents=True, exist_ok=True)
        Path(self.upload_directory).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
