import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.enums import EarningsOutcome, EventType


class HistoricalReactionBase(BaseModel):
    ticker_id: uuid.UUID
    event_id: uuid.UUID | None = None
    event_type: EventType
    event_date: date
    close_before: Decimal | None = None
    open_after: Decimal | None = None
    close_after: Decimal | None = None
    pct_change_1d: Decimal | None = None
    pct_change_3d: Decimal | None = None
    pct_change_5d: Decimal | None = None
    volume_before: int | None = None
    volume_after: int | None = None
    notes: str | None = None
    eps_estimate: Decimal | None = None
    eps_actual: Decimal | None = None
    revenue_estimate: int | None = None
    revenue_actual: int | None = None
    outcome: EarningsOutcome = EarningsOutcome.UNKNOWN


class HistoricalReactionCreate(HistoricalReactionBase):
    pass


class HistoricalReactionRead(HistoricalReactionBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime

    # Computed enrichment field -- not stored in DB; populated by the router
    eps_surprise_pct: float | None = None   # uncapped (eps_actual - eps_estimate) / |eps_estimate| x 100; None when |estimate| < EPS_SURPRISE_DOLLAR_FLOOR
    eps_surprise_dollars: float | None = None   # eps_actual - eps_estimate, always when both exist
    eps_surprise_display_pct: float | None = None   # percent to print, capped at +/- EPS_SURPRISE_PCT_CAP
    eps_surprise_capped: bool = False
    report_timing: str | None = None        # bmo | amc | unknown
    basis_mismatch: bool = False            # eps_basis_checks: actual and estimate on different bases; outcome is absent
    outcome_reason: str | None = None       # why the outcome is absent, when it is (basis_exclusion.BASIS_UNCLEAR_REASON)
    # NOTE: gap/intraday decomposition (open_after/close_before − 1, close_after/open_after − 1)
    # is misleading for after-close reporters: stored open_after/close_after are pre-print event-day
    # prices, not the post-earnings reaction. Meaningful decomposition requires next-day OHLCV
    # (T+1 open), which is not currently stored. Revisit when price-history data is richer.


class LabelRule(BaseModel):
    label: str
    rule: str


class ReactionSummaryRead(BaseModel):
    """Aggregate insights for a ticker's earnings reaction history."""
    symbol: str
    sector: str | None
    total_quarters: int
    beat_count: int
    miss_count: int
    meet_count: int
    beat_rate_pct: float
    beat_but_dropped_count: int             # beats where T+1 was negative
    beat_but_dropped_rate_pct: float | None # beat_but_dropped / beat_count × 100
    avg_1d_on_beat: float | None
    avg_1d_on_miss: float | None
    avg_abs_1d: float | None                # average |pct_change_1d| across all quarters
    sector_avg_abs_1d: float | None         # same metric across sector peers (None if <5 peers)
    sector_peer_count: int                  # distinct peer tickers used for sector avg
    sector_as_of: str | None = None         # ISO date of sector peer snapshot
    priced_in: LabelRule | None = None      # interpretive label for beat-but-dropped rate
    last_event_date: str | None = None      # ISO date of most recent earnings in sample
    mixed_versions: bool = False            # True while reseed in progress (some rows < v3)
    basis_excluded: int = 0                 # quarters left out of every count above: EPS basis unclear
    basis_excluded_note: str | None = None  # sentence to show next to any rate when basis_excluded > 0
    price_history_excluded: bool = False    # the ticker is on the RV exclusion list; rows exist but are not shown
    exclusion_reason: str | None = None


class ConditionalEarningsRead(BaseModel):
    """Conditional earnings intelligence: how does this ticker move on beats vs misses?"""
    symbol: str
    total_quarters: int
    has_sufficient_history: bool             # total_quarters >= MIN_QUARTERS (8)

    # ── Outcome breakdown (beat + miss + meet + unknown == total_quarters) ───
    beat_count: int
    miss_count: int
    meet_count: int
    unknown_count: int
    basis_excluded: int = 0                 # quarters left out of the counts above: EPS basis unclear
    basis_excluded_note: str | None = None
    price_history_excluded: bool = False    # the ticker is on the RV exclusion list; rows exist but are not shown
    exclusion_reason: str | None = None

    # ── Conditional 1d moves ─────────────────────────────────────────────────
    avg_1d_on_beat: float | None
    median_1d_on_beat: float | None

    avg_1d_on_miss: float | None
    median_1d_on_miss: float | None

    # ── Follow-through: does the 1d move hold by day 5? ──────────────────────
    beat_avg_5d: float | None
    beat_continuation_rate_pct: float | None  # % of beats where sign(5d) == sign(1d)
    beat_5d_sample: int                        # beats with non-null pct_change_5d

    miss_avg_5d: float | None
    miss_continuation_rate_pct: float | None
    miss_5d_sample: int

    # ── Magnitude trend: last 4 prints vs prior 4 ───────────────────────────
    recent_avg_abs_1d: float | None            # last 4 prints avg |pct_change_1d|
    prior_avg_abs_1d: float | None             # prior 4 prints avg |pct_change_1d|
    magnitude_trend: str | None                # "increasing" | "decreasing" | "stable"
    magnitude_trend_labeled: LabelRule | None = None  # human-friendly label + rule
    last_event_date: str | None = None         # ISO date of most recent earnings in sample


class SectorPeerItem(BaseModel):
    symbol: str
    avg_abs_1d: float
    quarter_count: int


class SectorPeersRead(BaseModel):
    symbol: str
    sector: str | None
    own_avg_abs_1d: float | None
    sector_avg_abs_1d: float | None
    peer_count: int
    as_of: str | None
    peers: list[SectorPeerItem]


class AnalystDetailItem(BaseModel):
    event_date: str
    firm: str | None = None
    action: str | None = None        # "up" | "down" | "init" | "reit" | etc.
    from_grade: str | None = None
    to_grade: str | None = None
    pct_change_1d: float | None = None
    pct_change_5d: float | None = None


class AnalystDetailRead(BaseModel):
    rows: list[AnalystDetailItem]
    total_with_moves: int            # rows with non-null pct_change_1d
    total_all: int                   # all rows including null moves
    price_history_excluded: bool = False    # the ticker is on the RV exclusion list; rows exist but are not shown
    exclusion_reason: str | None = None


class AnalystReactionStatsRead(BaseModel):
    """Precomputed per-ticker stats: how does this stock move on upgrades vs downgrades?"""
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    computed_at: datetime | None = None

    # ── Upgrades ─────────────────────────────────────────────────────────────
    upgrade_count: int                     # actions
    upgrade_sessions: int = 0              # distinct sessions the upgrade statistics are taken over
    avg_1d_upgrade: float | None
    median_1d_upgrade: float | None
    avg_5d_upgrade: float | None
    upgrade_5d_continuation_pct: float | None
    upgrade_5d_sample: int

    # ── Downgrades ───────────────────────────────────────────────────────────
    downgrade_count: int                   # actions
    downgrade_sessions: int = 0            # distinct sessions the downgrade statistics are taken over
    avg_1d_downgrade: float | None
    median_1d_downgrade: float | None
    avg_5d_downgrade: float | None
    downgrade_5d_continuation_pct: float | None
    downgrade_5d_sample: int
    sample_count: int = 0                  # total actions (upgrade + downgrade)
    session_count: int = 0                 # total distinct sessions (upgrade + downgrade)
    last_event_date: str | None = None     # ISO date of most recent analyst action
    price_history_excluded: bool = False    # the ticker is on the RV exclusion list; rows exist but are not shown
    exclusion_reason: str | None = None
