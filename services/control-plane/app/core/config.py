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

    # Auth (Phase 3). Access tokens are short-lived and stateless (JWT);
    # refresh sessions are DB-backed and revocable — see docs/auth.md.
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    # Cookies must be Secure in any real deployment; defaults to False only
    # so local http://localhost dev works without TLS. Set true in prod.
    cookie_secure: bool = False
    dashboard_origin: str = "http://localhost:3000"

    # Agent protocol (Phase 4). "TLS-ready" means the server accepts a wss://
    # URL here for any real deployment — dev defaults to plain ws:// since
    # there's no local TLS termination.
    agent_ws_public_url: str = "ws://localhost:8000/ws/agent"

    service_name: str = "control-plane"
    service_version: str = "0.1.0"


settings = Settings()
