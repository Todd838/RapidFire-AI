"""Pydantic v2 schemas for API request/response models."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Liveness / readiness probe payload."""

    status: str = "ok"
    service: str = "rapidfire"
    live_trading_enabled: bool = False
    alpaca_paper: bool = True


class QuoteResponse(BaseModel):
    """Normalized quote for stocks or crypto."""

    ticker: str
    price: float
    change_pct: Optional[float] = None
    volume: Optional[float] = None
    currency: str = "USD"
    source: str = "yfinance"
    as_of: datetime
    error: Optional[str] = None


class HistoryBar(BaseModel):
    """Single OHLCV bar."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class HistoryResponse(BaseModel):
    """Historical OHLCV series."""

    ticker: str
    days: int
    bars: list[HistoryBar]
    source: str = "yfinance"
    error: Optional[str] = None


class MoverItem(BaseModel):
    """A market mover row."""

    ticker: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    volume: Optional[float] = None


class MarketMoversResponse(BaseModel):
    """Gainers / losers snapshot."""

    gainers: list[MoverItem] = Field(default_factory=list)
    losers: list[MoverItem] = Field(default_factory=list)
    source: str = "yfinance"
    error: Optional[str] = None


class IpoItem(BaseModel):
    """Recent or upcoming IPO listing (best-effort)."""

    ticker: str
    name: Optional[str] = None
    exchange: Optional[str] = None
    ipo_date: Optional[str] = None
    notes: Optional[str] = None


class IpoListResponse(BaseModel):
    """IPO list response."""

    items: list[IpoItem] = Field(default_factory=list)
    source: str = "yfinance"
    error: Optional[str] = None


# --- ORM-backed schemas (used in later stages; defined early for consistency) ---


class PaperTradeBase(BaseModel):
    ticker: str
    asset_type: str = "equity"
    side: str = "long"
    quantity: float
    entry_price: float
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    rationale: Optional[str] = None


class PaperTradeRead(PaperTradeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    exit_price: Optional[float] = None
    status: str
    alpaca_order_id: Optional[str] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    realized_pnl: Optional[float] = None
    is_live: bool = False


class WatchlistItemCreate(BaseModel):
    ticker: str
    asset_type: str = "equity"
    notes: Optional[str] = None


class WatchlistItemRead(WatchlistItemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class SignalResponse(BaseModel):
    """Technical signal payload."""

    ticker: str
    action: str
    confidence: float
    entry_zone: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    reasoning: str = ""
    indicators: dict = Field(default_factory=dict)
    error: Optional[str] = None


class RiskCheckResponse(BaseModel):
    allowed: bool
    reason: str
    suggested_size: float


class RiskCheckRequest(BaseModel):
    account_value: float = Field(gt=0)
    open_positions: int = Field(ge=0, default=0)
    daily_pnl: float = 0.0
    entry: float = Field(gt=0)
    stop: float
    asset_type: str = Field(default="equity", pattern="^(equity|crypto)$")
    ticker: str = Field(min_length=1, max_length=12)
    is_live: bool = False


class AutoTraderScanResponse(BaseModel):
    dry_run: bool
    scanned: int
    skipped: int
    would_trade: int
    traded: int
    errors: int


class AutoTraderStatusResponse(BaseModel):
    dry_run: bool
    live_trading_enabled_env: bool
    live_session_active: bool
    note: str


class EnableLiveRequest(BaseModel):
    confirmation: str
    # readiness_passed injected by server from performance tracker later;
    # clients cannot force it true via this field in Stage 7.

