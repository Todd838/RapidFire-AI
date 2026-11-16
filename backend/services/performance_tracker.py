"""Daily performance snapshots and live go-readiness gate."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy.orm import Session

from models import LessonLog, PaperTrade, PerformanceSnapshot
from services import claude_service, portfolio_service

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Go-readiness thresholds (all must pass).
MIN_DAYS = 30
MIN_CLOSED_TRADES = 40
MIN_WIN_RATE = 52.0  # percent
MIN_PROFIT_FACTOR = 1.3
MIN_SHARPE = 1.0
MAX_DRAWDOWN_PCT = 12.0
MAX_SINGLE_DAY_LOSS_PCT = 4.0


def _closed_pnls(db: Session) -> list[float]:
    rows = db.query(PaperTrade).filter(PaperTrade.status == "closed").all()
    return [float(t.realized_pnl or 0) for t in rows]


def _daily_returns_from_snapshots(snapshots: list[PerformanceSnapshot]) -> list[float]:
    if len(snapshots) < 2:
        return []
    ordered = sorted(snapshots, key=lambda s: s.snapshot_date)
    rets: list[float] = []
    for prev, cur in zip(ordered, ordered[1:]):
        if prev.account_value and prev.account_value > 0:
            rets.append((cur.account_value - prev.account_value) / prev.account_value)
    return rets


def compute_sharpe(daily_returns: list[float]) -> Optional[float]:
    """Annualized Sharpe from daily returns (sqrt(252)). Zero std → None."""
    if len(daily_returns) < 2:
        return None
    arr = np.array(daily_returns, dtype=float)
    std = float(arr.std(ddof=1))
    if std == 0 or math.isnan(std):
        return None
    mean = float(arr.mean())
    return float((mean / std) * math.sqrt(252))


def compute_max_drawdown_pct(equity_curve: list[float]) -> Optional[float]:
    if not equity_curve:
        return None
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak * 100.0
            max_dd = max(max_dd, dd)
    return max_dd


def compute_profit_factor(pnls: list[float]) -> Optional[float]:
    gains = sum(p for p in pnls if p > 0)
    losses = sum(-p for p in pnls if p < 0)
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def take_daily_snapshot(db: Session, *, starting_cash: float = 10_000.0) -> PerformanceSnapshot:
    """Create/update today's PerformanceSnapshot (intended for 16:05 ET job)."""
    stats = portfolio_service.portfolio_stats(db, starting_cash=starting_cash)
    pnls = _closed_pnls(db)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    avg_win = float(np.mean(wins)) if wins else None
    avg_loss = float(np.mean(losses)) if losses else None
    pf = compute_profit_factor(pnls)
    if pf == float("inf"):
        pf = 999.0

    today = datetime.now(ET).date()
    existing = (
        db.query(PerformanceSnapshot)
        .filter(PerformanceSnapshot.snapshot_date == today)
        .first()
    )
    prior = (
        db.query(PerformanceSnapshot)
        .order_by(PerformanceSnapshot.snapshot_date.asc())
        .all()
    )
    curve = [s.account_value for s in prior if s.snapshot_date != today]
    curve.append(float(stats["account_value"]))
    rets = _daily_returns_from_snapshots(
        [s for s in prior if s.snapshot_date != today]
        + [
            PerformanceSnapshot(
                snapshot_date=today,
                account_value=float(stats["account_value"]),
                daily_pnl=float(stats["daily_pnl"]),
            )
        ]
    )
    # Rebuild rets properly from prior+new value
    temp_vals = [s.account_value for s in prior if s.snapshot_date != today] + [
        float(stats["account_value"])
    ]
    rets = []
    for a, b in zip(temp_vals, temp_vals[1:]):
        if a > 0:
            rets.append((b - a) / a)

    sharpe = compute_sharpe(rets)
    max_dd = compute_max_drawdown_pct(curve)

    fields = dict(
        account_value=float(stats["account_value"]),
        daily_pnl=float(stats["daily_pnl"]),
        win_rate=stats["win_rate"],
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=pf,
        sharpe=sharpe,
        max_drawdown=max_dd,
        open_positions=int(stats["open_positions"]),
        closed_trades_total=int(stats["closed_trades"]),
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        snap = existing
    else:
        snap = PerformanceSnapshot(snapshot_date=today, **fields)
        db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def compute_readiness_checks(db: Session) -> dict[str, Any]:
    """Deterministic readiness math only (no Claude — safe for frequent polls)."""
    snaps = (
        db.query(PerformanceSnapshot)
        .order_by(PerformanceSnapshot.snapshot_date.asc())
        .all()
    )
    closed = db.query(PaperTrade).filter(PaperTrade.status == "closed").all()
    pnls = [float(t.realized_pnl or 0) for t in closed]
    days = len(snaps)
    n_closed = len(closed)
    wins = [p for p in pnls if p > 0]
    win_rate = (len(wins) / n_closed * 100.0) if n_closed else 0.0
    pf = compute_profit_factor(pnls)
    pf_val = 999.0 if pf == float("inf") else (pf or 0.0)

    curve = [s.account_value for s in snaps]
    rets = []
    for a, b in zip(curve, curve[1:]):
        if a > 0:
            rets.append((b - a) / a)
    sharpe = compute_sharpe(rets) or 0.0
    max_dd = compute_max_drawdown_pct(curve) or 0.0

    worst_day_pct = 0.0
    for s in snaps:
        base = s.account_value - s.daily_pnl if s.account_value else 10_000.0
        if base > 0:
            day_pct = abs(min(0.0, s.daily_pnl) / base * 100.0)
            worst_day_pct = max(worst_day_pct, day_pct)

    checks = {
        "days_of_data": {
            "value": days,
            "threshold": MIN_DAYS,
            "pass": days >= MIN_DAYS,
        },
        "closed_trades": {
            "value": n_closed,
            "threshold": MIN_CLOSED_TRADES,
            "pass": n_closed >= MIN_CLOSED_TRADES,
        },
        "win_rate_pct": {
            "value": round(win_rate, 2),
            "threshold": MIN_WIN_RATE,
            "pass": win_rate >= MIN_WIN_RATE,
        },
        "profit_factor": {
            "value": round(pf_val, 3),
            "threshold": MIN_PROFIT_FACTOR,
            "pass": pf_val >= MIN_PROFIT_FACTOR,
        },
        "sharpe": {
            "value": round(sharpe, 3),
            "threshold": MIN_SHARPE,
            "pass": sharpe >= MIN_SHARPE,
        },
        "max_drawdown_pct": {
            "value": round(max_dd, 2),
            "threshold": MAX_DRAWDOWN_PCT,
            "pass": max_dd <= MAX_DRAWDOWN_PCT,
        },
        "worst_single_day_loss_pct": {
            "value": round(worst_day_pct, 2),
            "threshold": MAX_SINGLE_DAY_LOSS_PCT,
            "pass": worst_day_pct <= MAX_SINGLE_DAY_LOSS_PCT,
        },
    }
    all_pass = all(c["pass"] for c in checks.values())
    return {
        "passed": all_pass,
        "checks": checks,
        "note": (
            "40 trades is a minimum for sanity, not proof of an edge. "
            "Treat passing as 'not obviously broken' and keep live size small."
        ),
    }


def get_live_go_readiness(db: Session, *, include_verdict: bool = True) -> dict[str, Any]:
    """Require ALL thresholds. Optionally attach a Claude-written verdict."""
    from config import get_settings

    base = compute_readiness_checks(db)
    if not include_verdict:
        base["verdict"] = None
        return base

    settings = get_settings()
    if not settings.anthropic_api_key.strip():
        base["verdict"] = (
            "Claude verdict skipped (ANTHROPIC_API_KEY not set). "
            f"Checklist passed={base['passed']}."
        )
        return base

    base["verdict"] = claude_service.write_readiness_verdict(
        {
            "all_pass": base["passed"],
            "checks": base["checks"],
            "note": "40 trades is sanity minimum, not edge proof",
        }
    )
    return base


def list_snapshots(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(PerformanceSnapshot)
        .order_by(PerformanceSnapshot.snapshot_date.asc())
        .all()
    )
    return [
        {
            "snapshot_date": r.snapshot_date.isoformat(),
            "account_value": r.account_value,
            "daily_pnl": r.daily_pnl,
            "win_rate": r.win_rate,
            "avg_win": r.avg_win,
            "avg_loss": r.avg_loss,
            "profit_factor": r.profit_factor,
            "sharpe": r.sharpe,
            "max_drawdown": r.max_drawdown,
            "open_positions": r.open_positions,
            "closed_trades_total": r.closed_trades_total,
        }
        for r in rows
    ]


def monthly_report(db: Session) -> dict[str, Any]:
    """Claude monthly analysis saved to LessonLog."""
    snaps = list_snapshots(db)
    closed = db.query(PaperTrade).filter(PaperTrade.status == "closed").all()
    losers = [
        portfolio_service.trade_to_dict(t)
        for t in closed
        if (t.realized_pnl or 0) < 0
    ]
    metrics = {
        "snapshots": snaps[-60:],
        "closed_count": len(closed),
        "stats": portfolio_service.portfolio_stats(db),
    }
    text = claude_service.write_monthly_report(metrics, losers)
    lesson = LessonLog(
        topic=f"Monthly report {datetime.now(ET).strftime('%Y-%m')}",
        content=text,
        source="monthly",
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return {
        "id": lesson.id,
        "topic": lesson.topic,
        "content": lesson.content,
        "created_at": lesson.created_at.isoformat() if lesson.created_at else None,
    }
