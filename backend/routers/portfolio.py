"""Paper portfolio HTTP endpoints — real market prices for P&L."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from schemas import WatchlistItemCreate, WatchlistItemRead
from services import portfolio_service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class AddTradeRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    quantity: float = Field(gt=0)
    entry_price: Optional[float] = Field(default=None, gt=0)
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    asset_type: str = Field(default="equity", pattern="^(equity|crypto)$")
    rationale: Optional[str] = Field(default=None, max_length=4000)


@router.get("/trades")
def get_trades(
    status: Optional[str] = Query(default=None, pattern="^(open|closed)$"),
    db: Session = Depends(get_db),
) -> list[dict]:
    trades = portfolio_service.list_trades(db, status=status)
    return [portfolio_service.trade_to_dict(t) for t in trades]


@router.post("/trades")
def create_trade(body: AddTradeRequest, db: Session = Depends(get_db)) -> dict:
    trade, msg = portfolio_service.add_trade(
        db,
        ticker=body.ticker,
        quantity=body.quantity,
        entry_price=body.entry_price,
        stop_price=body.stop_price,
        target_price=body.target_price,
        asset_type=body.asset_type,
        rationale=body.rationale,
    )
    if trade is None:
        raise HTTPException(status_code=400, detail=msg)
    return portfolio_service.trade_to_dict(trade)


@router.post("/trades/{trade_id}/close")
def close_trade(trade_id: int, db: Session = Depends(get_db)) -> dict:
    trade, msg = portfolio_service.close_trade(db, trade_id)
    if trade is None:
        raise HTTPException(status_code=400, detail=msg)
    return portfolio_service.trade_to_dict(trade)


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    return portfolio_service.portfolio_stats(db)


@router.get("/watchlist", response_model=list[WatchlistItemRead])
def watchlist(db: Session = Depends(get_db)):
    return portfolio_service.list_watchlist(db)


@router.post("/watchlist", response_model=WatchlistItemRead)
def add_watch(body: WatchlistItemCreate, db: Session = Depends(get_db)):
    return portfolio_service.add_watchlist(
        db, body.ticker, asset_type=body.asset_type, notes=body.notes
    )


@router.delete("/watchlist/{ticker}")
def del_watch(ticker: str, db: Session = Depends(get_db)) -> dict:
    ok = portfolio_service.remove_watchlist(db, ticker)
    if not ok:
        raise HTTPException(status_code=404, detail="Not on watchlist")
    return {"removed": ticker.upper()}


@router.get("/lessons")
def lessons(db: Session = Depends(get_db)) -> list[dict]:
    rows = portfolio_service.list_lessons(db)
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
