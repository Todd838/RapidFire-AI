"""AutoTrader control endpoints — dry-run by default."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from schemas import AutoTraderScanResponse, AutoTraderStatusResponse, EnableLiveRequest
from services.auto_trader import AutoTrader
from services.live_gate import (
    LIVE_CONFIRMATION_PHRASE,
    attempt_enable_live,
    get_live_gate_status,
    reset_live_session_state,
)

router = APIRouter(prefix="/api/auto-trader", tags=["auto-trader"])


@router.get("/status", response_model=AutoTraderStatusResponse)
def status(db: Session = Depends(get_db)) -> AutoTraderStatusResponse:
    from services.performance_tracker import compute_readiness_checks

    settings = get_settings()
    readiness = compute_readiness_checks(db)
    gate = get_live_gate_status(readiness_passed=bool(readiness.get("passed")))
    mode = "LIVE" if gate.live_session_active else "PAPER"
    return AutoTraderStatusResponse(
        dry_run=settings.auto_trader_dry_run,
        live_trading_enabled_env=settings.live_trading_enabled,
        live_session_active=gate.live_session_active,
        note=(
            f"Mode={mode}. Dry-run={settings.auto_trader_dry_run}. "
            "Live requires env + readiness + typed confirmation."
        ),
    )


@router.post("/scan", response_model=AutoTraderScanResponse)
def run_scan(db: Session = Depends(get_db)) -> AutoTraderScanResponse:
    """Run one scan cycle (honors AUTO_TRADER_DRY_RUN)."""
    trader = AutoTrader(db)
    summary = trader.run_scan_cycle()
    return AutoTraderScanResponse(**summary)


@router.post("/emergency-close")
def emergency_close(db: Session = Depends(get_db)) -> dict:
    """Close all open paper positions and engage a 24h trading lock."""
    trader = AutoTrader(db)
    return trader.emergency_close_all()


@router.post("/monitor")
def monitor(db: Session = Depends(get_db)) -> dict:
    """Run one crypto stop/target + stale-thesis monitor pass."""
    return AutoTrader(db).monitor_positions()


@router.post("/enable-live")
def enable_live(body: EnableLiveRequest, db: Session = Depends(get_db)) -> dict:
    """Enable live session only with env + readiness + exact confirmation phrase."""
    from services.performance_tracker import compute_readiness_checks

    readiness_passed = bool(compute_readiness_checks(db).get("passed"))
    status_gate = attempt_enable_live(
        body.confirmation,
        readiness_passed=readiness_passed,
    )
    return {
        "activated": status_gate.all_conditions_met,
        "env_enabled": status_gate.env_enabled,
        "readiness_passed": status_gate.readiness_passed,
        "ui_confirmed": status_gate.ui_confirmed,
        "live_session_active": status_gate.live_session_active,
        "blockers": status_gate.blockers,
        "required_phrase": LIVE_CONFIRMATION_PHRASE,
    }


@router.post("/disable-live")
def disable_live() -> dict:
    """Instant live disable — clears UI confirmation and session."""
    reset_live_session_state()
    return {"live_session_active": False, "disabled": True}
