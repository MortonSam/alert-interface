# Import all models here so SQLAlchemy metadata and Alembic autogenerate see them.
from app.models.base import Base  # noqa: F401
from app.models.event import Event  # noqa: F401
from app.models.historical_reaction import HistoricalReaction  # noqa: F401
from app.models.research_note import ResearchNote  # noqa: F401
from app.models.system_metadata import SystemMetadata  # noqa: F401
from app.models.ticker import Ticker  # noqa: F401
from app.models.watchlist import Watchlist, WatchlistTicker  # noqa: F401
from app.models.rv_snapshot import RVSnapshot  # noqa: F401
from app.models.thesis import Thesis  # noqa: F401
