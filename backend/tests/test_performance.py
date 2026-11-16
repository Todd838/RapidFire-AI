"""Performance math unit tests."""

from services.performance_tracker import (
    compute_max_drawdown_pct,
    compute_profit_factor,
    compute_sharpe,
)


def test_sharpe_zero_std_returns_none() -> None:
    assert compute_sharpe([0.01, 0.01, 0.01]) is None


def test_sharpe_positive() -> None:
    rets = [0.01, -0.005, 0.02, 0.0, 0.015]
    s = compute_sharpe(rets)
    assert s is not None
    assert s > 0


def test_max_drawdown() -> None:
    dd = compute_max_drawdown_pct([100, 110, 90, 95])
    assert dd == compute_max_drawdown_pct([100, 110, 90, 95])
    assert dd is not None
    assert abs(dd - (20 / 110 * 100)) < 0.01


def test_profit_factor() -> None:
    assert compute_profit_factor([10, -5, 20, -5]) == 30 / 10
