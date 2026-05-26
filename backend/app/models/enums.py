import enum


class EventType(str, enum.Enum):
    EARNINGS = "earnings"
    MACRO = "macro"
    FDA = "fda"
    EX_DIVIDEND = "ex_dividend"
    PRODUCT_LAUNCH = "product_launch"
    OTHER = "other"


class DataSource(str, enum.Enum):
    YFINANCE = "yfinance"
    EDGAR = "edgar"
    FRED = "fred"
    FDA = "fda"
    POLYGON = "polygon"
    MANUAL = "manual"
