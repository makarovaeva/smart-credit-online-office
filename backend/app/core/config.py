from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Smart Credit Office API"
    environment: str = "local"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://credit:credit@localhost:5432/credit"

    cors_origins: list[str] = ["http://localhost:3000"]

    # Для локального запуска и тестов; в docker-compose задаётся через окружение
    jwt_secret: str = "dev-secret-change-me"
    access_token_ttl_minutes: int = 12 * 60

    # Срок действия оффера на доске не задан - открытый вопрос
    offer_validity_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
