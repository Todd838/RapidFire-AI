"""Signal computation endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from schemas import RiskCheckRequest, RiskCheckResponse, SignalResponse
from services import adaptive_agent
from services.risk_manager import RiskManager
from services.signal_engine import compute_signals
from services.validation import validate_ticker

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/{ticker}", response_model=SignalResponse)
def get_signal(
    ticker: str,
    adaptive: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> SignalResponse:
    """Compute technical signals for a validated ticker (adaptive weights on by default)."""
    symbol = validate_ticker(ticker)
    result = compute_signals(symbol)
    if adaptive:
        result = adaptive_agent.apply_policy(result, adaptive_agent.get_policy(db))
    return SignalResponse(
        ticker=result.ticker,
        action=result.action,
        confidence=result.confidence,
        entry_zone=result.entry_zone,
        stop_price=result.stop_price,
        target_price=result.target_price,
        reasoning=result.reasoning,
        indicators=result.indicators,
        error=result.error,
    )


@router.post("/risk-check", response_model=RiskCheckResponse)
def risk_check(body: RiskCheckRequest) -> RiskCheckResponse:
    """Run RiskManager.check_trade_allowed (no order is placed)."""
    symbol = validate_ticker(body.ticker)
    result = RiskManager().check_trade_allowed(
        account_value=body.account_value,
        open_positions=body.open_positions,
        daily_pnl=body.daily_pnl,
        entry=body.entry,
        stop=body.stop,
        asset_type=body.asset_type,
        ticker=symbol,
        is_live=body.is_live,
    )
    return RiskCheckResponse(
        allowed=result.allowed,
        reason=result.reason,
        suggested_size=result.suggested_size,
    )
