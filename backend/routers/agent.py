"""Adaptive agent policy endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from services import adaptive_agent

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/policy")
def get_policy(db: Session = Depends(get_db)) -> dict:
    return adaptive_agent.policy_to_dict(adaptive_agent.get_policy(db))


@router.get("/events")
def events(db: Session = Depends(get_db)) -> list[dict]:
    return adaptive_agent.list_events(db)


@router.post("/adapt")
def adapt(db: Session = Depends(get_db)) -> dict:
    """Run a learning pass over closed paper trades not yet consumed."""
    return adaptive_agent.run_adaptation_cycle(db)


@router.post("/reset")
def reset(db: Session = Depends(get_db)) -> dict:
    """Reset weights to defaults (equal / confidence 70)."""
    return adaptive_agent.reset_policy(db)
