from functools import lru_cache
from typing import Literal

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

    # Датасет синтетических заёмщиков от ML (.jsonl или .json) - из него отвечают моки ЕГРЮЛ,
    # ФНС и БКИ. ИНН, которых в датасете нет, генерируются на лету
    borrower_dataset_path: str | None = None

    # Реализация скоринга из services/scoring.py: rules - правила, ml - сервис ML
    scoring_model: str = "rules"
    # Сервис инференса ML (ml/service); при недоступности скоринг откатывается на правила
    ml_service_url: str = "http://ml:8000"
    ml_timeout_seconds: float = 10.0

    # Кто готовит договор после принятия оффера: auto - система сразу; analyst - кредитный
    # аналитик командой POST /backoffice/applications/{id}/contract (как на доске от 23.10)
    contract_preparation: Literal["auto", "analyst"] = "auto"

    # LLM для формулировки ответов ИИ-агента в чате: OpenAI-совместимый API сервера с моделью
    # с открытыми весами (Ollama, llama.cpp server, vLLM), например http://ollama:11434/v1.
    # Не задан - ответы по шаблонам из данных заявки; при ошибке модели - тоже шаблоны
    llm_base_url: str | None = None
    llm_model: str = "qwen2.5:3b-instruct"
    llm_api_key: str | None = None
    llm_timeout_seconds: float = 30.0

    # Файлы документов заявок; в docker-compose - отдельный том
    document_storage_dir: str = "var/documents"
    document_max_size_mb: int = 20

    # Срок действия оффера на доске не задан - открытый вопрос
    offer_validity_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
