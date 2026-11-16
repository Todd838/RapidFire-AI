"""APScheduler jobs for auto-trader, position monitor, and daily snapshots."""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from database import SessionLocal
from services.auto_trader import AutoTrader
from services.performance_tracker import take_daily_snapshot
from services import adaptive_agent

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def _job_scan() -> None:
    db = SessionLocal()
    try:
        summary = AutoTrader(db).run_scan_cycle()
        logger.info("Scheduled scan complete: %s", summary)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scheduled scan failed: %s", type(exc).__name__)
    finally:
        db.close()


def _job_monitor() -> None:
    db = SessionLocal()
    try:
        summary = AutoTrader(db).monitor_positions()
        logger.info("Position monitor: %s", summary)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Position monitor failed: %s", type(exc).__name__)
    finally:
        db.close()


def _job_snapshot() -> None:
    db = SessionLocal()
    try:
        snap = take_daily_snapshot(db)
        logger.info(
            "Daily snapshot %s value=%s",
            snap.snapshot_date,
            snap.account_value,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Daily snapshot failed: %s", type(exc).__name__)
    finally:
        db.close()


def _job_adapt() -> None:
    db = SessionLocal()
    try:
        result = adaptive_agent.run_adaptation_cycle(db)
        logger.info("Adaptation cycle processed=%s", result.get("processed"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Adaptation cycle failed: %s", type(exc).__name__)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    sched = BackgroundScheduler(timezone="America/New_York")
    sched.add_job(
        _job_scan,
        IntervalTrigger(minutes=15),
        id="auto_trader_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _job_monitor,
        IntervalTrigger(minutes=5),
        id="monitor_positions",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _job_snapshot,
        CronTrigger(hour=16, minute=5, timezone="America/New_York"),
        id="daily_snapshot",
        replace_existing=True,
        max_instances=1,
    )
    sched.add_job(
        _job_adapt,
        IntervalTrigger(minutes=30),
        id="adaptive_learn",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    logger.info(
        "APScheduler started (scan 15m, monitor 5m, adapt 30m, snapshot 16:05 ET)"
    )
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
    _scheduler = None
