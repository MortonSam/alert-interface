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
from app.models.analyst_reaction_stats import AnalystReactionStats  # noqa: F401
from app.models.alert_pick import AlertPick  # noqa: F401
from app.models.analyst_recommendation import AnalystRecommendation  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.credit_shadow_pick import CreditShadowPick  # noqa: F401
from app.models.earnings_feature import EarningsFeature  # noqa: F401
from app.models.sector_peer_snapshot import SectorPeerSnapshot  # noqa: F401
from app.models.magnitude_trend_snapshot import MagnitudeTrendSnapshot  # noqa: F401
from app.models.put_call_snapshot import PutCallSnapshot  # noqa: F401
from app.models.earnings_report_timing import EarningsReportTiming  # noqa: F401
from app.models.ivy_train_log import IvyTrainLog  # noqa: F401
