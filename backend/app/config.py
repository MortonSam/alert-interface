from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://alert:alert@localhost:5432/alertdb"
    database_url_sync: str = "postgresql+psycopg2://alert:alert@localhost:5432/alertdb"

    # App
    debug: bool = False
    secret_key: str = "changeme"
    cors_origins: str = "http://localhost:3000"  # comma-separated origins
    admin_token: str = ""  # if set, gates AI-powered endpoints
    refresh_enabled: bool = True  # startup + loop refresh pipeline

    # External APIs
    anthropic_api_key: str = ""
    finnhub_api_key: str = ""
    polygon_api_key: str = ""
    fred_api_key: str = ""
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"


settings = Settings()
