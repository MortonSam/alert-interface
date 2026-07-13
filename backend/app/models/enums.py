import enum


class EventType(str, enum.Enum):
    EARNINGS = "earnings"
    MACRO = "macro"
    FDA = "fda"
    EX_DIVIDEND = "ex_dividend"
    PRODUCT_LAUNCH = "product_launch"
    FOMC = "fomc"
    OTHER = "other"


class DataSource(str, enum.Enum):
    YFINANCE = "yfinance"
    EDGAR = "edgar"
    FRED = "fred"
    FDA = "fda"
    POLYGON = "polygon"
    MANUAL = "manual"


class EarningsOutcome(str, enum.Enum):
    BEAT    = "beat"
    MISS    = "miss"
    MEET    = "meet"
    UNKNOWN = "unknown"
