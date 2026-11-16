"""Technical signal engine — RSI, MACD, Bollinger, volume, trend, ATR.

Every indicator is guarded against insufficient data / NaN propagation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from schemas import HistoryBar
from services import market_data

logger = logging.getLogger(__name__)

# Minimum bars needed for SMA200 + warm-up.
MIN_BARS_FULL = 210
MIN_BARS_PARTIAL = 30


@dataclass
class SignalResult:
    """Structured output of compute_signals."""

    ticker: str
    action: str  # BUY | WATCH | NEUTRAL | AVOID
    confidence: float  # 0-100
    entry_zone: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    reasoning: str = ""
    indicators: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


def score_to_action(total: int) -> str:
    """Map indicator score sum (−6…+6) to an action label."""
    if total >= 4:
        return "BUY"
    if total >= 2:
        return "WATCH"
    if total <= -2:
        return "AVOID"
    return "NEUTRAL"


def score_to_confidence(total: int) -> float:
    """Map score sum to a 0–100 confidence. Symmetric around neutral."""
    # |total| / 6 * 100, floored at 0, capped at 100; neutral totals get low confidence.
    magnitude = min(abs(total), 6) / 6.0
    # Keep a floor so NEUTRAL isn't always 0 when total is 0/±1.
    if total == 0:
        return 35.0
    if abs(total) == 1:
        return 45.0
    return round(50.0 + magnitude * 50.0, 1) if total > 0 else round(40.0 + magnitude * 40.0, 1)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _bars_to_frame(bars: list[HistoryBar]) -> pd.DataFrame:
    rows = [
        {
            "date": b.date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("date").reset_index(drop=True)
    return df


def _score_rsi(close: pd.Series) -> tuple[int, Optional[float]]:
    if len(close) < 15:
        return 0, None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    last_gain = _safe_float(gain.iloc[-1])
    last_loss = _safe_float(loss.iloc[-1])
    if last_gain is None or last_loss is None:
        return 0, None
    if last_loss == 0:
        val = 100.0 if last_gain > 0 else 50.0
    else:
        rs = last_gain / last_loss
        val = 100.0 - (100.0 / (1.0 + rs))
    val = _safe_float(val)
    if val is None:
        return 0, None
    if val < 30:
        return 1, val  # oversold → bullish lean
    if val > 70:
        return -1, val  # overbought → bearish lean
    return 0, val


def _score_macd(close: pd.Series) -> tuple[int, Optional[float], Optional[float]]:
    if len(close) < 35:
        return 0, None, None
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    m = _safe_float(macd.iloc[-1])
    h = _safe_float(hist.iloc[-1])
    if m is None or h is None:
        return 0, m, h
    if h > 0 and m > 0:
        return 1, m, h
    if h < 0 and m < 0:
        return -1, m, h
    return 0, m, h


def _score_bollinger(close: pd.Series) -> tuple[int, Optional[float], Optional[float], Optional[float]]:
    if len(close) < 20:
        return 0, None, None, None
    mid = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    upper = mid + 2 * std
    lower = mid - 2 * std
    c = _safe_float(close.iloc[-1])
    u = _safe_float(upper.iloc[-1])
    m = _safe_float(mid.iloc[-1])
    l = _safe_float(lower.iloc[-1])
    if None in (c, u, m, l):
        return 0, u, m, l
    # Near lower band → bullish lean; near upper → bearish lean.
    assert c is not None and u is not None and l is not None and m is not None
    band_width = u - l
    if band_width <= 0:
        return 0, u, m, l
    pos = (c - l) / band_width
    if pos <= 0.2:
        return 1, u, m, l
    if pos >= 0.8:
        return -1, u, m, l
    return 0, u, m, l


def _score_volume(volume: pd.Series) -> tuple[int, Optional[float]]:
    if len(volume) < 11:
        return 0, None
    avg10 = volume.iloc[-11:-1].mean()
    last = _safe_float(volume.iloc[-1])
    avg = _safe_float(avg10)
    if last is None or avg is None or avg <= 0:
        return 0, None
    ratio = last / avg
    if ratio >= 1.5:
        return 1, ratio
    if ratio <= 0.7:
        return -1, ratio
    return 0, ratio


def _score_trend(close: pd.Series) -> tuple[int, Optional[float], Optional[float]]:
    sma50 = _safe_float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    sma200 = _safe_float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
    price = _safe_float(close.iloc[-1])
    if price is None:
        return 0, sma50, sma200
    if sma50 is not None and sma200 is not None:
        if price > sma50 > sma200:
            return 1, sma50, sma200
        if price < sma50 < sma200:
            return -1, sma50, sma200
        return 0, sma50, sma200
    if sma50 is not None:
        if price > sma50:
            return 1, sma50, sma200
        if price < sma50:
            return -1, sma50, sma200
    return 0, sma50, sma200


def _atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    if len(df) < period + 1:
        return None
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return _safe_float(atr)


def _score_atr_context(atr: Optional[float], price: Optional[float]) -> tuple[int, Optional[float]]:
    """ATR itself is used for stops; score mild mean-reversion on extreme ATR%."""
    if atr is None or price is None or price <= 0:
        return 0, atr
    atr_pct = atr / price
    # Very high volatility → cautious (−1); calm → slight positive.
    if atr_pct >= 0.05:
        return -1, atr
    if atr_pct <= 0.015:
        return 1, atr
    return 0, atr


def compute_signals(ticker: str) -> SignalResult:
    """Compute technical signals for a ticker and return scored action + levels."""
    symbol = ticker.upper().strip()
    history = market_data.get_history(symbol, days=260)
    if history.error or not history.bars:
        return SignalResult(
            ticker=symbol,
            action="NEUTRAL",
            confidence=0.0,
            reasoning="Insufficient market data to compute signals.",
            error=history.error or "No history bars",
            indicators={},
        )

    df = _bars_to_frame(history.bars)
    if len(df) < MIN_BARS_PARTIAL:
        return SignalResult(
            ticker=symbol,
            action="NEUTRAL",
            confidence=0.0,
            reasoning=f"Only {len(df)} bars available; need at least {MIN_BARS_PARTIAL}.",
            error="insufficient_data",
            indicators={},
        )

    close = df["close"]
    volume = df["volume"]
    price = _safe_float(close.iloc[-1])

    rsi_score, rsi_val = _score_rsi(close)
    macd_score, macd_val, macd_hist = _score_macd(close)
    bb_score, bb_u, bb_m, bb_l = _score_bollinger(close)
    vol_score, vol_ratio = _score_volume(volume)
    trend_score, sma50, sma200 = _score_trend(close)
    atr_val = _atr(df)
    atr_score, atr_out = _score_atr_context(atr_val, price)

    total = rsi_score + macd_score + bb_score + vol_score + trend_score + atr_score
    action = score_to_action(total)
    confidence = score_to_confidence(total)
    # Cap confidence when SMA200 unavailable (partial data).
    if len(df) < MIN_BARS_FULL:
        confidence = min(confidence, 55.0)

    entry = price
    stop: Optional[float] = None
    target: Optional[float] = None
    if entry is not None and atr_val is not None and atr_val > 0:
        stop = entry - 2 * atr_val
        risk = entry - stop
        target = entry + 3 * risk

    indicators: dict[str, Any] = {
        "rsi": {"score": rsi_score, "value": rsi_val},
        "macd": {"score": macd_score, "value": macd_val, "histogram": macd_hist},
        "bollinger": {"score": bb_score, "upper": bb_u, "mid": bb_m, "lower": bb_l},
        "volume": {"score": vol_score, "ratio": vol_ratio},
        "trend": {"score": trend_score, "sma50": sma50, "sma200": sma200},
        "atr_context": {"score": atr_score, "value": atr_out},
        "score_total": total,
    }

    parts = [
        f"{symbol} scored {total:+d}/6 → {action} (confidence {confidence:.0f}).",
        f"RSI={rsi_val:.1f}" if rsi_val is not None else "RSI=n/a",
        f"MACD hist={macd_hist:.4f}" if macd_hist is not None else "MACD=n/a",
        f"vol ratio={vol_ratio:.2f}" if vol_ratio is not None else "vol=n/a",
        f"trend SMA50/200={'above' if trend_score > 0 else 'below' if trend_score < 0 else 'mixed'}.",
    ]
    if stop is not None and target is not None and entry is not None:
        parts.append(
            f"Educational levels only (not advice): entry≈{entry:.2f}, "
            f"stop≈{stop:.2f} (2×ATR), target≈{target:.2f} (3:1 R:R)."
        )
    if len(df) < MIN_BARS_FULL:
        parts.append("Note: fewer than 210 bars — SMA200 incomplete; treat confidence as capped.")

    return SignalResult(
        ticker=symbol,
        action=action,
        confidence=float(confidence),
        entry_zone=entry,
        stop_price=stop,
        target_price=target,
        reasoning=" ".join(parts),
        indicators=indicators,
    )
