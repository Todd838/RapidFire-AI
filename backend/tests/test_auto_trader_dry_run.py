"""AutoTrader dry-run logs decisions without placing broker orders."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AutoTradeLog, WatchlistItem
from services.auto_trader import AutoTrader
from services.risk_manager import RiskCheckResult
from services.signal_engine import SignalResult


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_dry_run_writes_would_trade_not_order() -> None:
    db = _session()
    db.add(WatchlistItem(ticker="AAPL", asset_type="equity"))
    db.commit()

    fake_signal = SignalResult(
        ticker="AAPL",
        action="BUY",
        confidence=85.0,
        entry_zone=100.0,
        stop_price=90.0,
        target_price=130.0,
        reasoning="test setup",
        indicators={},
    )
    alpaca = MagicMock()
    trader = AutoTrader(db, dry_run=True, alpaca=alpaca, account_value=10_000.0)

    with (
        patch.object(trader, "is_market_open", return_value=True),
        patch("services.auto_trader.compute_signals", return_value=fake_signal),
    ):
        summary = trader.run_scan_cycle()

    assert summary["dry_run"] is True
    assert summary["would_trade"] == 1
    assert summary["traded"] == 0
    alpaca.place_market_order.assert_not_called()

    logs = db.query(AutoTradeLog).filter(AutoTradeLog.action == "would_trade").all()
    assert len(logs) == 1
    assert "AAPL" in logs[0].reason


def test_non_dry_run_still_requires_risk_before_order() -> None:
    db = _session()
    db.add(WatchlistItem(ticker="AAPL", asset_type="equity"))
    db.commit()

    fake_signal = SignalResult(
        ticker="AAPL",
        action="BUY",
        confidence=90.0,
        entry_zone=100.0,
        stop_price=90.0,
        target_price=130.0,
        reasoning="test",
        indicators={},
    )
    alpaca = MagicMock()
    alpaca.place_market_order.return_value = MagicMock(
        ok=True, order_id="oid-1", status="filled", detail="ok", dry_run=False
    )
    trader = AutoTrader(db, dry_run=False, alpaca=alpaca, account_value=10_000.0)

    with (
        patch.object(trader, "is_market_open", return_value=True),
        patch("services.auto_trader.compute_signals", return_value=fake_signal),
    ):
        summary = trader.run_scan_cycle()

    assert summary["traded"] == 1
    assert alpaca.place_market_order.called
    risk_arg = alpaca.place_market_order.call_args.kwargs["risk"]
    assert isinstance(risk_arg, RiskCheckResult)
    assert risk_arg.allowed is True
