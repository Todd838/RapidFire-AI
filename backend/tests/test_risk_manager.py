"""Unit tests for RiskManager — every branch (TDD before implementation)."""

from __future__ import annotations

from services.risk_manager import RiskManager


def _allowed(**kwargs):
    defaults = dict(
        account_value=10_000.0,
        open_positions=0,
        daily_pnl=0.0,
        entry=100.0,
        stop=90.0,
        asset_type="equity",
        ticker="AAPL",
    )
    defaults.update(kwargs)
    return RiskManager().check_trade_allowed(**defaults)


class TestCheckTradeAllowedHappyPath:
    def test_allows_valid_trade(self) -> None:
        result = _allowed()
        assert result.allowed is True
        assert result.suggested_size > 0
        assert "ok" in result.reason.lower() or "allowed" in result.reason.lower()


class TestMaxOpenPositions:
    def test_rejects_at_max_positions(self) -> None:
        result = _allowed(open_positions=10)
        assert result.allowed is False
        assert result.suggested_size == 0.0
        assert "position" in result.reason.lower()

    def test_allows_at_nine_positions(self) -> None:
        result = _allowed(open_positions=9)
        assert result.allowed is True

    def test_rejects_above_max(self) -> None:
        result = _allowed(open_positions=11)
        assert result.allowed is False


class TestDailyLossKillSwitch:
    def test_rejects_when_daily_loss_hits_5pct(self) -> None:
        # -5% of 10k = -500
        result = _allowed(daily_pnl=-500.0)
        assert result.allowed is False
        assert "kill" in result.reason.lower() or "daily" in result.reason.lower()

    def test_rejects_when_daily_loss_exceeds_5pct(self) -> None:
        result = _allowed(daily_pnl=-600.0)
        assert result.allowed is False

    def test_allows_loss_just_under_5pct(self) -> None:
        result = _allowed(daily_pnl=-499.0)
        assert result.allowed is True

    def test_allows_positive_daily_pnl(self) -> None:
        result = _allowed(daily_pnl=250.0)
        assert result.allowed is True


class TestInvalidInputs:
    def test_rejects_non_positive_account(self) -> None:
        result = _allowed(account_value=0.0)
        assert result.allowed is False
        assert result.suggested_size == 0.0

    def test_rejects_negative_account(self) -> None:
        result = _allowed(account_value=-1.0)
        assert result.allowed is False

    def test_rejects_non_positive_entry(self) -> None:
        result = _allowed(entry=0.0)
        assert result.allowed is False

    def test_rejects_stop_not_below_entry(self) -> None:
        result = _allowed(entry=100.0, stop=100.0)
        assert result.allowed is False
        assert result.suggested_size == 0.0

    def test_rejects_stop_above_entry(self) -> None:
        result = _allowed(entry=100.0, stop=105.0)
        assert result.allowed is False

    def test_rejects_when_size_rounds_to_zero(self) -> None:
        # Tiny account / wide stop → size floors to 0
        result = _allowed(
            account_value=50.0,
            entry=500.0,
            stop=100.0,
            asset_type="equity",
        )
        assert result.allowed is False
        assert result.suggested_size == 0.0


class TestRiskCaps:
    def test_default_max_risk_pct_is_2(self) -> None:
        rm = RiskManager()
        assert rm.max_risk_pct == 0.02

    def test_default_max_positions_is_10(self) -> None:
        rm = RiskManager()
        assert rm.max_open_positions == 10

    def test_default_daily_loss_limit_is_5pct(self) -> None:
        rm = RiskManager()
        assert rm.daily_loss_limit_pct == 0.05

    def test_no_bypass_flag_on_check(self) -> None:
        """check_trade_allowed must not accept a bypass/skip_risk kwarg."""
        import inspect

        sig = inspect.signature(RiskManager.check_trade_allowed)
        forbidden = {"bypass", "skip_risk", "force", "ignore_risk"}
        assert forbidden.isdisjoint(sig.parameters.keys())


class TestLivePhase1Limits:
    """When is_live=True, tighter Phase-1 caps apply (constants, not bypassable)."""

    def test_live_rejects_over_max_position_notional(self) -> None:
        rm = RiskManager()
        # suggested size at 2% risk could exceed $500 notional — live must cap/reject
        result = rm.check_trade_allowed(
            account_value=100_000.0,
            open_positions=0,
            daily_pnl=0.0,
            entry=200.0,
            stop=190.0,
            asset_type="equity",
            ticker="AAPL",
            is_live=True,
        )
        # Either rejected or size capped so notional <= 500
        if result.allowed:
            assert result.suggested_size * 200.0 <= 500.0 + 1e-6
        else:
            assert result.suggested_size == 0.0 or "live" in result.reason.lower()

    def test_live_rejects_non_whitelist_ticker(self) -> None:
        result = RiskManager().check_trade_allowed(
            account_value=10_000.0,
            open_positions=0,
            daily_pnl=0.0,
            entry=100.0,
            stop=90.0,
            asset_type="equity",
            ticker="GME",
            is_live=True,
        )
        assert result.allowed is False
        assert "whitelist" in result.reason.lower()

    def test_live_max_three_open_positions(self) -> None:
        result = RiskManager().check_trade_allowed(
            account_value=10_000.0,
            open_positions=3,
            daily_pnl=0.0,
            entry=100.0,
            stop=90.0,
            asset_type="equity",
            ticker="AAPL",
            is_live=True,
        )
        assert result.allowed is False
