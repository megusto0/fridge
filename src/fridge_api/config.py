import shutil
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
    auto_create_schema: bool = False
    app_name: str = "Fridge backend"
    environment: str = "development"
    upload_directory: str = "./data/uploads"
    upload_max_bytes: int = 10 * 1024 * 1024
    web_ui_directory: str = "./web_ui"
    cors_allow_origins: list[str] = [
        "http://127.0.0.1:8011",
        "http://localhost:8011",
        "https://megusto.duckdns.org:1338",
        "https://megusto.duckdns.org",
    ]
    open_food_facts_base_url: str = "https://world.openfoodfacts.org"
    open_food_facts_user_agent: str = (
        "FridgeBackend/0.1 (personal food inventory; https://megusto.duckdns.org)"
    )
    enrichment_http_timeout_seconds: float = 20.0
    enrichment_poll_seconds: float = 60.0
    enrichment_reference_food_fallback: bool = True
    enrichment_yandex_eda_fallback: bool = True
    enrichment_hermes_fallback: bool = True
    enrichment_hermes_bin: str = "hermes"
    enrichment_hermes_timeout_seconds: float = 240.0
    naming_hermes_timeout_seconds: float = 90.0

    def resolve_hermes_bin(self) -> str:
        """Resolve hermes executable searching in PATH and standard user locations."""
        if Path(self.enrichment_hermes_bin).is_file():
            return self.enrichment_hermes_bin
        found = shutil.which(self.enrichment_hermes_bin)
        if found:
            return found
        user_local = Path.home() / ".local" / "bin" / "hermes"
        if user_local.is_file():
            return str(user_local)
        return self.enrichment_hermes_bin

    def prepare_local_directories(self) -> None:
        if self.database_url.startswith("sqlite:///./"):
            raw = self.database_url.removeprefix("sqlite:///./")
            Path(raw).parent.mkdir(parents=True, exist_ok=True)
        Path(self.upload_directory).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
