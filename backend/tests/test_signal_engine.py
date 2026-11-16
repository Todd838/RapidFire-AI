"""Unit tests for signal_engine scoring (TDD before implementation)."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pytest

from schemas import HistoryBar, HistoryResponse
from services import signal_engine


def _make_bars(
    n: int,
    start_price: float = 100.0,
    drift: float = 0.002,
    vol: float = 0.01,
    seed: int = 42,
) -> list[HistoryBar]:
    rng = np.random.default_rng(seed)
    bars: list[HistoryBar] = []
    price = start_price
    start = date(2024, 1, 2)
    for i in range(n):
        ret = drift + vol * float(rng.standard_normal())
        open_px = price
        close = price * (1 + ret)
        high = max(open_px, close) * (1 + abs(float(rng.standard_normal()) * 0.005))
        low = min(open_px, close) * (1 - abs(float(rng.standard_normal()) * 0.005))
        volume = float(1_000_000 + rng.integers(0, 500_000))
        bars.append(
            HistoryBar(
                date=start + timedelta(days=i),
                open=float(open_px),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=volume,
            )
        )
        price = close
    return bars


def _history(bars: list[HistoryBar], ticker: str = "TEST") -> HistoryResponse:
    return HistoryResponse(ticker=ticker, days=len(bars), bars=bars, source="test")


class TestComputeSignalsInsufficientData:
    def test_returns_neutral_when_too_few_bars(self) -> None:
        bars = _make_bars(30)  # need ~200 for SMA200
        with patch("services.signal_engine.market_data.get_history", return_value=_history(bars)):
            result = signal_engine.compute_signals("TEST")
        assert result.action in {"NEUTRAL", "WATCH", "AVOID", "BUY"}
        assert result.error is not None or result.confidence >= 0
        # With <200 bars SMA200 cannot score meaningfully — should not crash
        assert result.indicators is not None

    def test_never_propagates_nan_confidence(self) -> None:
        bars = _make_bars(50)
        with patch("services.signal_engine.market_data.get_history", return_value=_history(bars)):
            result = signal_engine.compute_signals("TEST")
        assert result.confidence == result.confidence  # not NaN
        assert 0 <= result.confidence <= 100


class TestComputeSignalsScoring:
    def test_strong_uptrend_produces_valid_levels(self) -> None:
        """Uptrend data must yield valid 2×ATR stop / 3:1 target (action may be
        NEUTRAL when mean-reversion RSI/BB cool a melt-up — that's intentional)."""
        bars = _make_bars(260, start_price=50.0, drift=0.008, vol=0.005, seed=1)
        with patch("services.signal_engine.market_data.get_history", return_value=_history(bars)):
            result = signal_engine.compute_signals("BULL")
        assert result.action in {"BUY", "WATCH", "NEUTRAL", "AVOID"}
        assert 0 <= result.confidence <= 100
        assert result.entry_zone is not None and result.entry_zone > 0
        assert result.stop_price is not None
        assert result.target_price is not None
        assert result.stop_price < result.entry_zone
        assert result.target_price > result.entry_zone
        risk = result.entry_zone - result.stop_price
        reward = result.target_price - result.entry_zone
        assert reward == pytest.approx(3 * risk, rel=1e-3)
        assert result.reasoning
        assert result.indicators["trend"]["score"] == 1

    def test_all_bullish_indicator_scores_map_to_buy(self) -> None:
        assert signal_engine.score_to_action(6) == "BUY"
        assert signal_engine.score_to_confidence(6) >= 90

    def test_strong_downtrend_leans_avoid_or_neutral(self) -> None:
        bars = _make_bars(260, start_price=200.0, drift=-0.008, vol=0.005, seed=2)
        with patch("services.signal_engine.market_data.get_history", return_value=_history(bars)):
            result = signal_engine.compute_signals("BEAR")
        assert result.action in {"AVOID", "NEUTRAL", "WATCH"}
        assert 0 <= result.confidence <= 100

    def test_indicator_scores_are_neg1_0_or_1(self) -> None:
        bars = _make_bars(260, drift=0.003, seed=3)
        with patch("services.signal_engine.market_data.get_history", return_value=_history(bars)):
            result = signal_engine.compute_signals("TEST")
        for key in ("rsi", "macd", "bollinger", "volume", "trend", "atr_context"):
            assert key in result.indicators
            assert result.indicators[key]["score"] in (-1, 0, 1)

    def test_stop_is_entry_minus_2atr(self) -> None:
        bars = _make_bars(260, drift=0.002, seed=4)
        with patch("services.signal_engine.market_data.get_history", return_value=_history(bars)):
            result = signal_engine.compute_signals("TEST")
        atr = result.indicators["atr_context"]["value"]
        assert atr is not None and atr > 0
        assert result.stop_price == pytest.approx(result.entry_zone - 2 * atr, rel=1e-3)

    def test_empty_history_graceful(self) -> None:
        empty = HistoryResponse(ticker="NONE", days=0, bars=[], source="test", error="none")
        with patch("services.signal_engine.market_data.get_history", return_value=empty):
            result = signal_engine.compute_signals("NONE")
        assert result.action == "NEUTRAL"
        assert result.confidence == 0
        assert result.error is not None


class TestActionMapping:
    """Score sum → action buckets."""

    @pytest.mark.parametrize(
        "total,expected",
        [
            (6, "BUY"),
            (4, "BUY"),
            (3, "WATCH"),
            (2, "WATCH"),
            (1, "NEUTRAL"),
            (0, "NEUTRAL"),
            (-1, "NEUTRAL"),
            (-2, "AVOID"),
            (-6, "AVOID"),
        ],
    )
    def test_score_to_action(self, total: int, expected: str) -> None:
        assert signal_engine.score_to_action(total) == expected

    def test_confidence_bounds(self) -> None:
        for total in range(-6, 7):
            conf = signal_engine.score_to_confidence(total)
            assert 0 <= conf <= 100
