"""Unit tests for position sizing math (TDD — written before implementation)."""

from __future__ import annotations

import math

import pytest

from services.risk_manager import RiskManager, size_position


class TestSizePositionEquity:
    """Equity shares are floored to whole shares."""

    def test_basic_2pct_risk_whole_shares(self) -> None:
        # account=10_000, risk 2% = 200; entry=100, stop=90 → risk/share=10 → 20 shares
        size = size_position(
            account_value=10_000.0,
            entry=100.0,
            stop=90.0,
            risk_pct=0.02,
            asset_type="equity",
        )
        assert size == 20.0

    def test_floors_partial_shares(self) -> None:
        # 200 / 7 = 28.571… → floor to 28
        size = size_position(
            account_value=10_000.0,
            entry=100.0,
            stop=93.0,
            risk_pct=0.02,
            asset_type="equity",
        )
        assert size == 28.0
        assert size == math.floor(200.0 / 7.0)

    def test_zero_when_stop_equals_entry(self) -> None:
        size = size_position(
            account_value=10_000.0,
            entry=50.0,
            stop=50.0,
            risk_pct=0.02,
            asset_type="equity",
        )
        assert size == 0.0

    def test_zero_when_stop_above_entry_long(self) -> None:
        size = size_position(
            account_value=10_000.0,
            entry=50.0,
            stop=55.0,
            risk_pct=0.02,
            asset_type="equity",
        )
        assert size == 0.0

    def test_zero_when_account_non_positive(self) -> None:
        assert (
            size_position(
                account_value=0.0,
                entry=100.0,
                stop=90.0,
                risk_pct=0.02,
                asset_type="equity",
            )
            == 0.0
        )

    def test_custom_risk_pct(self) -> None:
        # 1% of 10k = 100; risk/share=5 → 20 shares
        size = size_position(
            account_value=10_000.0,
            entry=100.0,
            stop=95.0,
            risk_pct=0.01,
            asset_type="equity",
        )
        assert size == 20.0


class TestSizePositionCrypto:
    """Crypto may be fractional (not floored to integers)."""

    def test_allows_fractional_shares(self) -> None:
        # 200 / 1000 = 0.2 BTC
        size = size_position(
            account_value=10_000.0,
            entry=50_000.0,
            stop=49_000.0,
            risk_pct=0.02,
            asset_type="crypto",
        )
        assert size == pytest.approx(0.2)

    def test_rounds_to_reasonable_precision(self) -> None:
        size = size_position(
            account_value=5_000.0,
            entry=64_000.0,
            stop=62_000.0,
            risk_pct=0.02,
            asset_type="crypto",
        )
        # 100 / 2000 = 0.05
        assert size == pytest.approx(0.05)
        assert size > 0


class TestRiskManagerSizingIntegration:
    def test_check_includes_suggested_size(self) -> None:
        rm = RiskManager()
        result = rm.check_trade_allowed(
            account_value=10_000.0,
            open_positions=0,
            daily_pnl=0.0,
            entry=100.0,
            stop=90.0,
            asset_type="equity",
        )
        assert result.allowed is True
        assert result.suggested_size == 20.0
