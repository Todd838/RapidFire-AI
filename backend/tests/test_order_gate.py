"""Orders must never place without a passing RiskManager result."""

from __future__ import annotations

import pytest

from services.alpaca_service import AlpacaService, RiskGateError
from services.risk_manager import RiskCheckResult, RiskManager


def test_place_order_rejects_missing_risk() -> None:
    svc = AlpacaService(paper=True)
    with pytest.raises(TypeError):
        # risk is keyword-only required
        svc.place_market_order(ticker="AAPL", qty=1, side="buy")  # type: ignore[call-arg]


def test_place_order_rejects_denied_risk() -> None:
    svc = AlpacaService(paper=True)
    denied = RiskCheckResult(False, "Max open positions reached", 0.0)
    with pytest.raises(RiskGateError, match="RiskManager"):
        svc.place_market_order(ticker="AAPL", qty=1, side="buy", risk=denied, dry_run=True)


def test_place_order_rejects_qty_above_suggested() -> None:
    svc = AlpacaService(paper=True)
    allowed = RiskCheckResult(True, "Allowed", 5.0)
    with pytest.raises(RiskGateError, match="exceeds"):
        svc.place_market_order(ticker="AAPL", qty=10, side="buy", risk=allowed, dry_run=True)


def test_place_order_dry_run_with_passing_risk() -> None:
    svc = AlpacaService(paper=True)
    risk = RiskManager().check_trade_allowed(
        account_value=10_000,
        open_positions=0,
        daily_pnl=0,
        entry=100,
        stop=90,
        ticker="AAPL",
    )
    assert risk.allowed
    result = svc.place_market_order(
        ticker="AAPL",
        qty=risk.suggested_size,
        side="buy",
        risk=risk,
        dry_run=True,
    )
    assert result.ok is True
    assert result.dry_run is True
    assert result.order_id is None


def test_live_url_blocked_when_env_false() -> None:
    svc = AlpacaService(paper=False)
    with pytest.raises(PermissionError, match="LIVE_TRADING_ENABLED"):
        _ = svc.base_url
