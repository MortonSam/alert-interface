import enum


class EventType(str, enum.Enum):
    EARNINGS = "earnings"
    MACRO = "macro"
    FDA = "fda"
    EX_DIVIDEND = "ex_dividend"
    PRODUCT_LAUNCH = "product_launch"
    FOMC = "fomc"
    SPLIT = "split"
    ANALYST_ACTION = "analyst_action"
    SPIN_OFF = "spin_off"            # a distribution or separation adjustment yfinance once recorded as a split; never a split
    OTHER = "other"


class DataSource(str, enum.Enum):
    YFINANCE = "yfinance"
    EDGAR = "edgar"
    FRED = "fred"
    FDA = "fda"
    POLYGON = "polygon"
    MANUAL = "manual"
    FINNHUB = "finnhub"
    INTRINIO = "intrinio"


class EarningsOutcome(str, enum.Enum):
    BEAT    = "beat"
    MISS    = "miss"
    MEET    = "meet"
    UNKNOWN = "unknown"
