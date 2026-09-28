from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://alert:alert@localhost:5432/alertdb"
    database_url_sync: str = "postgresql+psycopg2://alert:alert@localhost:5432/alertdb"

    @field_validator("database_url_sync")
    @classmethod
    def _name_the_sync_driver(cls, v: str) -> str:
        """A bare postgresql:// URL means whatever driver the installed SQLAlchemy defaults to
        (psycopg2 in 2.0, psycopg v3 in 2.1). The image ships psycopg2, so say so."""
        if v.startswith("postgresql://"):
            return "postgresql+psycopg2://" + v[len("postgresql://"):]
        return v

    # App
    debug: bool = False
    secret_key: str = "changeme"
    cors_origins: str = "http://localhost:3000"  # comma-separated origins
    admin_token: str = ""  # if set, gates AI-powered endpoints
    refresh_enabled: bool = True  # startup + loop refresh pipeline

    # Clerk auth (empty = disabled, admin-token-only mode)
    clerk_jwks_url: str = ""            # https://<frontend-api>/.well-known/jwks.json
    clerk_authorized_party: str = ""    # http://localhost:3000

    # External APIs
    anthropic_api_key: str = ""
    finnhub_api_key: str = ""
    polygon_api_key: str = ""
    fred_api_key: str = ""
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"


settings = Settings()
