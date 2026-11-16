"""Adaptive paper-trading agent — learns bounded weight updates from outcomes.

Hard rules:
- Never bypasses RiskManager.
- Weights and confidence stay inside safe bands.
- Learning is from paper (or mirrored) closed trades only.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from models import AdaptationEvent, AdaptiveAgentState, LessonLog, PaperTrade
from services.signal_engine import SignalResult, score_to_action, score_to_confidence

logger = logging.getLogger(__name__)

INDICATOR_KEYS = ("rsi", "macd", "bollinger", "volume", "trend", "atr_context")

DEFAULT_WEIGHTS: dict[str, float] = {k: 1.0 for k in INDICATOR_KEYS}

WEIGHT_MIN = 0.25
WEIGHT_MAX = 2.0
CONF_MIN = 55.0
CONF_MAX = 85.0
DEFAULT_MIN_CONFIDENCE = 70.0
LEARNING_RATE = 0.08
STATE_ID = 1


@dataclass
class AgentPolicy:
    weights: dict[str, float]
    min_confidence: float
    version: int
    trades_learned: int
    last_lesson: Optional[str]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def default_policy() -> AgentPolicy:
    return AgentPolicy(
        weights=dict(DEFAULT_WEIGHTS),
        min_confidence=DEFAULT_MIN_CONFIDENCE,
        version=1,
        trades_learned=0,
        last_lesson="Fresh policy — equal indicator weights, confidence gate 70.",
    )


def _ensure_state(db: Session) -> AdaptiveAgentState:
    row = db.query(AdaptiveAgentState).filter(AdaptiveAgentState.id == STATE_ID).first()
    if row:
        return row
    row = AdaptiveAgentState(
        id=STATE_ID,
        version=1,
        weights_json=json.dumps(DEFAULT_WEIGHTS),
        min_confidence=DEFAULT_MIN_CONFIDENCE,
        trades_learned=0,
        last_lesson="Initialized adaptive agent.",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_policy(db: Session) -> AgentPolicy:
    row = _ensure_state(db)
    try:
        weights = json.loads(row.weights_json)
    except json.JSONDecodeError:
        weights = dict(DEFAULT_WEIGHTS)
    for k in INDICATOR_KEYS:
        weights.setdefault(k, 1.0)
        weights[k] = _clamp(float(weights[k]), WEIGHT_MIN, WEIGHT_MAX)
    return AgentPolicy(
        weights=weights,
        min_confidence=_clamp(float(row.min_confidence), CONF_MIN, CONF_MAX),
        version=int(row.version),
        trades_learned=int(row.trades_learned),
        last_lesson=row.last_lesson,
    )


def policy_to_dict(policy: AgentPolicy) -> dict[str, Any]:
    return {
        "weights": policy.weights,
        "min_confidence": policy.min_confidence,
        "version": policy.version,
        "trades_learned": policy.trades_learned,
        "last_lesson": policy.last_lesson,
        "bounds": {
            "weight_min": WEIGHT_MIN,
            "weight_max": WEIGHT_MAX,
            "confidence_min": CONF_MIN,
            "confidence_max": CONF_MAX,
        },
        "note": (
            "Adaptive weights only reshape signal scoring. "
            "Every order still must pass RiskManager."
        ),
    }


def weighted_score_total(indicators: dict[str, Any], weights: dict[str, float]) -> float:
    total = 0.0
    for key in INDICATOR_KEYS:
        block = indicators.get(key) or {}
        score = block.get("score", 0)
        try:
            s = float(score)
        except (TypeError, ValueError):
            s = 0.0
        w = float(weights.get(key, 1.0))
        total += s * w
    return total


def apply_policy(signal: SignalResult, policy: AgentPolicy) -> SignalResult:
    """Re-score a raw SignalResult with learned weights."""
    if not signal.indicators or signal.error:
        return signal

    total = weighted_score_total(signal.indicators, policy.weights)
    # Map continuous weighted total onto discrete-ish action using rounded sum.
    discrete = int(round(total))
    action = score_to_action(discrete)
    confidence = score_to_confidence(discrete)
    # Blend toward magnitude of weighted total for finer confidence.
    magnitude = min(abs(total) / 6.0, 1.0)
    if total > 0:
        confidence = max(confidence, 50.0 + magnitude * 50.0)
    elif total < 0:
        confidence = max(40.0, min(confidence, 40.0 + magnitude * 40.0))
    confidence = _clamp(float(confidence), 0.0, 100.0)

    adapted = deepcopy(signal)
    adapted.action = action
    adapted.confidence = confidence
    adapted.indicators = dict(signal.indicators)
    adapted.indicators["score_total"] = round(total, 3)
    adapted.indicators["score_total_raw"] = signal.indicators.get("score_total")
    adapted.indicators["adaptive_weights"] = dict(policy.weights)
    adapted.indicators["adaptive_version"] = policy.version
    adapted.reasoning = (
        f"[Adaptive v{policy.version}] weighted_score={total:+.2f} → {action} "
        f"(conf {confidence:.0f}, gate {policy.min_confidence:.0f}). "
        + signal.reasoning
    )
    return adapted


def snapshot_from_signal(signal: SignalResult) -> str:
    payload = {
        "action": signal.action,
        "confidence": signal.confidence,
        "indicators": {
            k: {"score": (signal.indicators.get(k) or {}).get("score", 0)}
            for k in INDICATOR_KEYS
        },
        "score_total": signal.indicators.get("score_total"),
    }
    return json.dumps(payload)


def _update_weights_from_trade(
    weights: dict[str, float],
    snapshot: dict[str, Any],
    *,
    won: bool,
) -> dict[str, float]:
    """Reinforce indicator votes that aligned with a winning long; punish on losses."""
    updated = dict(weights)
    indicators = snapshot.get("indicators") or {}
    for key in INDICATOR_KEYS:
        score = float((indicators.get(key) or {}).get("score") or 0)
        if score == 0:
            continue
        # Long-only system: +1 votes supported the buy.
        if won:
            if score > 0:
                updated[key] = _clamp(updated[key] + LEARNING_RATE, WEIGHT_MIN, WEIGHT_MAX)
            elif score < 0:
                # Contrary signal was wrong to fade — slight bump to contrary? skip
                updated[key] = _clamp(updated[key] - LEARNING_RATE * 0.5, WEIGHT_MIN, WEIGHT_MAX)
        else:
            if score > 0:
                updated[key] = _clamp(updated[key] - LEARNING_RATE, WEIGHT_MIN, WEIGHT_MAX)
            elif score < 0:
                updated[key] = _clamp(updated[key] + LEARNING_RATE * 0.5, WEIGHT_MIN, WEIGHT_MAX)
    return updated


def _adjust_confidence_gate(min_conf: float, recent_closed: list[PaperTrade]) -> float:
    if len(recent_closed) < 5:
        return min_conf
    wins = sum(1 for t in recent_closed if (t.realized_pnl or 0) > 0)
    rate = wins / len(recent_closed)
    if rate < 0.45:
        return _clamp(min_conf + 1.5, CONF_MIN, CONF_MAX)
    if rate > 0.60:
        return _clamp(min_conf - 1.0, CONF_MIN, CONF_MAX)
    return min_conf


def learn_from_closed_trade(db: Session, trade: PaperTrade) -> dict[str, Any]:
    """Update policy after a closed paper trade. Idempotent-ish per trade via events."""
    if trade.status != "closed" or trade.realized_pnl is None:
        return {"adapted": False, "reason": "Trade not closed with PnL"}

    existing = (
        db.query(AdaptationEvent)
        .filter(
            AdaptationEvent.trade_id == trade.id,
            AdaptationEvent.trigger == "close",
        )
        .first()
    )
    if existing:
        return {"adapted": False, "reason": "Already learned from this trade"}

    state = _ensure_state(db)
    before = get_policy(db)
    weights = dict(before.weights)
    lesson_parts: list[str] = []

    snapshot: dict[str, Any] = {}
    if trade.signal_snapshot_json:
        try:
            snapshot = json.loads(trade.signal_snapshot_json)
        except json.JSONDecodeError:
            snapshot = {}

    won = float(trade.realized_pnl) > 0
    if snapshot.get("indicators"):
        weights = _update_weights_from_trade(weights, snapshot, won=won)
        lesson_parts.append(
            f"{'Win' if won else 'Loss'} on {trade.ticker}: "
            f"adjusted weights from entry signal snapshot."
        )
    else:
        lesson_parts.append(
            f"{'Win' if won else 'Loss'} on {trade.ticker}: "
            f"no signal snapshot — confidence gate only."
        )

    recent = (
        db.query(PaperTrade)
        .filter(PaperTrade.status == "closed")
        .order_by(PaperTrade.closed_at.desc())
        .limit(10)
        .all()
    )
    new_conf = _adjust_confidence_gate(before.min_confidence, recent)
    if new_conf != before.min_confidence:
        lesson_parts.append(
            f"Confidence gate {before.min_confidence:.1f} → {new_conf:.1f} "
            f"from last {len(recent)} closes."
        )

    # Optional Claude one-liner when key present (non-blocking educational note).
    try:
        from config import get_settings
        from services import claude_service

        if get_settings().anthropic_api_key.strip() and snapshot:
            tip = claude_service.ask_coach(
                "In one short paragraph for a student: what should an adaptive "
                "paper-trading agent learn from this closed trade? Educational only.\n"
                f"Trade PnL={trade.realized_pnl}, ticker={trade.ticker}, snapshot={snapshot}"
            )
            if tip and not tip.startswith("Coach unavailable") and not tip.startswith("Coach API"):
                lesson_parts.append(tip[:500])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Adaptive Claude tip skipped: %s", type(exc).__name__)

    lesson = " ".join(lesson_parts)
    after_weights = weights
    after_conf = new_conf

    state.weights_json = json.dumps(after_weights)
    state.min_confidence = after_conf
    state.version = int(state.version) + 1
    state.trades_learned = int(state.trades_learned) + 1
    state.last_lesson = lesson
    state.updated_at = datetime.now(timezone.utc)

    event = AdaptationEvent(
        trade_id=trade.id,
        trigger="close",
        before_json=json.dumps(policy_to_dict(before)),
        after_json=json.dumps(
            {
                "weights": after_weights,
                "min_confidence": after_conf,
                "version": state.version,
            }
        ),
        lesson=lesson,
    )
    db.add(event)
    db.add(
        LessonLog(
            topic=f"Adaptive learn · {trade.ticker}",
            content=lesson,
            source="adaptive",
            related_trade_id=trade.id,
        )
    )
    db.commit()

    return {
        "adapted": True,
        "version": state.version,
        "weights": after_weights,
        "min_confidence": after_conf,
        "lesson": lesson,
    }


def run_adaptation_cycle(db: Session) -> dict[str, Any]:
    """Learn from any closed trades not yet processed."""
    learned = []
    closed = (
        db.query(PaperTrade)
        .filter(PaperTrade.status == "closed", PaperTrade.realized_pnl.isnot(None))
        .order_by(PaperTrade.closed_at.asc())
        .all()
    )
    for trade in closed:
        result = learn_from_closed_trade(db, trade)
        if result.get("adapted"):
            learned.append({"trade_id": trade.id, "ticker": trade.ticker, **result})
    policy = get_policy(db)
    return {
        "processed": len(learned),
        "events": learned[-20:],
        "policy": policy_to_dict(policy),
    }


def reset_policy(db: Session) -> dict[str, Any]:
    state = _ensure_state(db)
    before = get_policy(db)
    state.weights_json = json.dumps(DEFAULT_WEIGHTS)
    state.min_confidence = DEFAULT_MIN_CONFIDENCE
    state.version = int(state.version) + 1
    state.trades_learned = 0
    state.last_lesson = "Policy reset to equal weights / confidence 70."
    state.updated_at = datetime.now(timezone.utc)
    after = {
        "weights": dict(DEFAULT_WEIGHTS),
        "min_confidence": DEFAULT_MIN_CONFIDENCE,
        "version": state.version,
        "trades_learned": 0,
        "last_lesson": state.last_lesson,
    }
    db.add(
        AdaptationEvent(
            trade_id=None,
            trigger="reset",
            before_json=json.dumps(policy_to_dict(before)),
            after_json=json.dumps(after),
            lesson=state.last_lesson,
        )
    )
    db.commit()
    return policy_to_dict(get_policy(db))


def list_events(db: Session, limit: int = 30) -> list[dict[str, Any]]:
    rows = (
        db.query(AdaptationEvent)
        .order_by(AdaptationEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "trade_id": r.trade_id,
            "trigger": r.trigger,
            "lesson": r.lesson,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "after": json.loads(r.after_json) if r.after_json else None,
        }
        for r in rows
    ]
