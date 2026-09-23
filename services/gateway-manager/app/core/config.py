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

    # The one central Nginx installation this service is colocated with and
    # exclusively permitted to manage — see app/services/nginx_manager.py.
    nginx_binary: str = "nginx"
    nginx_managed_dir: str = "/etc/nginx/conf.d/healer"
    nginx_reload_timeout_seconds: float = 10.0

    service_name: str = "gateway-manager"
    service_version: str = "0.1.0"


settings = Settings()
