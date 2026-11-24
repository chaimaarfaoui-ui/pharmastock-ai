from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PharmaStock AI"
    database_url: str = "postgresql+psycopg://pharma:pharma@db:5432/pharmastock"
    # Must be overridden via environment in any real deployment.
    secret_key: str = "CHANGE_ME_IN_ENV_dev_only_do_not_use_in_production"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cors_origins: list[str] = ["http://localhost:3000"]
    login_rate_limit: str = "10/minute"
    use_celery: bool = False
    redis_url: str = "redis://redis:6379/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
