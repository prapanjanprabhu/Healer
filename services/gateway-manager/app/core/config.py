from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Gateway Manager runtime configuration.

    This service must never bind to a public interface. `gateway_manager_host`
    defaults to loopback on purpose — see docs/security-boundaries.md.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    healer_env: str = "development"
    gateway_manager_host: str = "127.0.0.1"
    gateway_manager_port: int = 8100
    gateway_manager_shared_secret: str = "change-me-internal-secret"

    service_name: str = "gateway-manager"
    service_version: str = "0.1.0"


settings = Settings()
