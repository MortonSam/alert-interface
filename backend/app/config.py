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
    # Comma-separated reviewer keys. A request carrying one reads the ledger (desk, Ivy trades, Ivy home)
    # while LEDGER_PUBLIC is false, exactly as the admin token does, and nothing else: no personal data,
    # no writes, no admin endpoints, and it is never attributed to admin-local (see app.auth).
    reviewer_tokens: str = ""
    refresh_enabled: bool = True  # startup + loop refresh pipeline
    # The free-text question box under the question strip (services/ask_ivy). Off in production until launched; on locally.
    ask_ivy_enabled: bool = False
    ask_ivy_daily_cap_usd: float = 15.0   # site-wide estimated spend per UTC day at which the box pauses

    # Clerk auth (empty = disabled, admin-token-only mode)
    clerk_jwks_url: str = ""            # https://<frontend-api>/.well-known/jwks.json
    clerk_authorized_party: str = ""    # http://localhost:3000

    # External APIs
    anthropic_api_key: str = ""
    finnhub_api_key: str = ""
    intrinio_api_key: str = ""          # Intrinio (security records, shadow price bars); read from .env locally, a Railway variable in production
    polygon_api_key: str = ""
    fred_api_key: str = ""
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"


settings = Settings()
