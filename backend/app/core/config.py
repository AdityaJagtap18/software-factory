from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SF_", extra="ignore")

    database_url: str = "postgresql+psycopg2://sf:sf@localhost:5433/software_factory"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    cors_origins: list[str] = ["http://localhost:4200"]
    credential_encryption_key: str = "dev-credential-key-change-me"
    neo4j_uri: str = "bolt://localhost:7688"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "sfgraphpass123"
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_webhook_secret: str = ""
    github_api_base_url: str = "https://api.github.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
