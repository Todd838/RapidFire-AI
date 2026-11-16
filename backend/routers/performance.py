"""Performance snapshots, go-readiness, monthly report (+ frontend aliases)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models import AutoTradeLog, LessonLog
from services import performance_tracker, portfolio_service

router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("/snapshots")
def snapshots(db: Session = Depends(get_db)) -> list[dict]:
    return performance_tracker.list_snapshots(db)


@router.post("/snapshot")
def force_snapshot(db: Session = Depends(get_db)) -> dict:
    """Manual snapshot (scheduler also runs at 16:05 ET)."""
    snap = performance_tracker.take_daily_snapshot(db)
    return {
        "snapshot_date": snap.snapshot_date.isoformat(),
        "account_value": snap.account_value,
        "daily_pnl": snap.daily_pnl,
        "win_rate": snap.win_rate,
        "sharpe": snap.sharpe,
        "max_drawdown": snap.max_drawdown,
        "profit_factor": snap.profit_factor,
    }


@router.get("/go-readiness")
def go_readiness(db: Session = Depends(get_db)) -> dict:
    return performance_tracker.get_live_go_readiness(db)


@router.post("/monthly-report")
def monthly_report(db: Session = Depends(get_db)) -> dict:
    return performance_tracker.monthly_report(db)


# --- Frontend-friendly aliases (same data, shapes the UI expects) ---


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict:
    stats = portfolio_service.portfolio_stats(db)
    snaps = performance_tracker.list_snapshots(db)
    latest = snaps[-1] if snaps else {}
    return {
        "account_value": stats.get("account_value"),
        "daily_pnl": stats.get("daily_pnl"),
        "win_rate": stats.get("win_rate"),
        "profit_factor": latest.get("profit_factor"),
        "sharpe": latest.get("sharpe"),
        "max_drawdown": latest.get("max_drawdown"),
        "closed_trades_total": stats.get("closed_trades"),
        "open_positions": stats.get("open_positions"),
        "realized_pnl": stats.get("realized_pnl"),
        "open_pnl": stats.get("open_pnl"),
    }


@router.get("/equity")
def equity(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "date": s["snapshot_date"],
            "account_value": s["account_value"],
            "daily_pnl": s.get("daily_pnl"),
        }
        for s in performance_tracker.list_snapshots(db)
    ]


@router.get("/trade-log")
def trade_log(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    rows = (
        db.query(AutoTradeLog)
        .order_by(AutoTradeLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "action": r.action,
            "reason": r.reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/readiness")
def readiness_alias(db: Session = Depends(get_db)) -> dict:
    """UI-shaped readiness: {ready, checks:[{name,passed,detail}], verdict}."""
    raw = performance_tracker.get_live_go_readiness(db)
    checks = []
    for name, c in (raw.get("checks") or {}).items():
        checks.append(
            {
                "name": name,
                "passed": bool(c.get("pass")),
                "detail": f"value={c.get('value')} threshold={c.get('threshold')}",
            }
        )
    return {
        "ready": bool(raw.get("passed")),
        "passed": bool(raw.get("passed")),
        "checks": checks,
        "verdict": raw.get("verdict"),
        "note": raw.get("note"),
    }


@router.get("/lessons")
def lessons(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    rows = (
        db.query(LessonLog)
        .order_by(LessonLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "topic": r.topic,
            "content": r.content,
            "source": r.source,
            "related_trade_id": r.related_trade_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
