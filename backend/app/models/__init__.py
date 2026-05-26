# Import all models here so SQLAlchemy metadata and Alembic autogenerate see them.
from app.models.base import Base  # noqa: F401
from app.models.event import Event  # noqa: F401
from app.models.historical_reaction import HistoricalReaction  # noqa: F401
from app.models.ticker import Ticker  # noqa: F401
from app.models.watchlist import Watchlist, WatchlistTicker  # noqa: F401
