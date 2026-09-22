from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Control Plane runtime configuration, sourced from environment variables.

    Field names intentionally mirror the placeholders in the repo root
    `.env.example` so the same `.env` file can be shared across services.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    healer_env: str = "development"

    database_url: str = "postgresql+psycopg2://healer:changeme@localhost:5432/healer"
    redis_url: str = "redis://localhost:6379/0"

    control_plane_host: str = "0.0.0.0"
    control_plane_port: int = 8000
    control_plane_secret_key: str = "change-me-dev-secret"

    service_name: str = "control-plane"
    service_version: str = "0.1.0"


settings = Settings()
