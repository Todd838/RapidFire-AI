"""Journal: educational article packs + personal lesson logs."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from services import journal_feed, portfolio_service

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("/articles")
def articles() -> dict:
    """Curated learning links + live RSS headlines for markets / AI finance / agents."""
    return journal_feed.get_journal_articles()


@router.get("/lessons")
def lessons(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    rows = portfolio_service.list_lessons(db, limit=limit)
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
