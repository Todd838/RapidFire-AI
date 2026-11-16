"""Adaptive agent learning stays bounded and never invents bypasses."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import PaperTrade
from services import adaptive_agent
from services.signal_engine import SignalResult


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_weights_clamp_on_learn() -> None:
    db = _session()
    snap = {
        "indicators": {
            "rsi": {"score": 1},
            "macd": {"score": 1},
            "bollinger": {"score": 0},
            "volume": {"score": 0},
            "trend": {"score": 1},
            "atr_context": {"score": 0},
        }
    }
    trade = PaperTrade(
        ticker="AAPL",
        quantity=1,
        entry_price=100,
        exit_price=110,
        status="closed",
        realized_pnl=10.0,
        closed_at=datetime.now(timezone.utc),
        signal_snapshot_json=__import__("json").dumps(snap),
    )
    db.add(trade)
    db.commit()

    result = adaptive_agent.learn_from_closed_trade(db, trade)
    assert result["adapted"] is True
    for w in result["weights"].values():
        assert adaptive_agent.WEIGHT_MIN <= w <= adaptive_agent.WEIGHT_MAX

    # Second call is idempotent
    again = adaptive_agent.learn_from_closed_trade(db, trade)
    assert again["adapted"] is False


def test_apply_policy_changes_score_total() -> None:
    policy = adaptive_agent.default_policy()
    policy.weights["trend"] = 2.0
    policy.weights["rsi"] = 0.25
    signal = SignalResult(
        ticker="TEST",
        action="NEUTRAL",
        confidence=45,
        indicators={
            "rsi": {"score": 1},
            "macd": {"score": 0},
            "bollinger": {"score": 0},
            "volume": {"score": 0},
            "trend": {"score": 1},
            "atr_context": {"score": 0},
            "score_total": 2,
        },
        reasoning="raw",
    )
    adapted = adaptive_agent.apply_policy(signal, policy)
    # 1*0.25 + 1*2.0 = 2.25
    assert adapted.indicators["score_total"] == 2.25
    assert "Adaptive" in adapted.reasoning


def test_reset_policy() -> None:
    db = _session()
    adaptive_agent.get_policy(db)
    state = adaptive_agent._ensure_state(db)
    state.weights_json = __import__("json").dumps({k: 2.0 for k in adaptive_agent.INDICATOR_KEYS})
    state.min_confidence = 80.0
    db.commit()
    policy = adaptive_agent.reset_policy(db)
    assert policy["min_confidence"] == 70.0
    assert policy["weights"]["rsi"] == 1.0
