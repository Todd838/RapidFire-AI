"""Paper portfolio using REAL market prices for P&L (never random)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from models import LessonLog, PaperTrade, WatchlistItem
from services import market_data
from services.risk_manager import RiskManager
from services.validation import validate_ticker

logger = logging.getLogger(__name__)

DEFAULT_STARTING_CASH = 10_000.0


def _quote_price(ticker: str, asset_type: str) -> Optional[float]:
    if asset_type == "crypto":
        q = market_data.get_crypto_quote(ticker)
    else:
        q = market_data.get_stock_quote(ticker)
    if q.error or q.price <= 0:
        return None
    return float(q.price)


def unrealized_pnl(trade: PaperTrade) -> Optional[float]:
    if trade.status != "open":
        return trade.realized_pnl
    px = _quote_price(trade.ticker, trade.asset_type or "equity")
    if px is None:
        return None
    return (px - trade.entry_price) * trade.quantity


def list_trades(db: Session, *, status: Optional[str] = None) -> list[PaperTrade]:
    q = db.query(PaperTrade).order_by(PaperTrade.opened_at.desc())
    if status:
        q = q.filter(PaperTrade.status == status)
    return q.all()


def add_trade(
    db: Session,
    *,
    ticker: str,
    quantity: float,
    entry_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    target_price: Optional[float] = None,
    asset_type: str = "equity",
    rationale: Optional[str] = None,
    account_value: float = DEFAULT_STARTING_CASH,
) -> tuple[Optional[PaperTrade], str]:
    """Open a paper trade after RiskManager gate. Uses live quote if entry omitted."""
    symbol = validate_ticker(ticker)
    if quantity <= 0:
        return None, "Quantity must be positive"

    px = entry_price
    if px is None or px <= 0:
        live = _quote_price(symbol, asset_type)
        if live is None:
            return None, f"Could not fetch live price for {symbol}"
        px = live

    stop = stop_price if stop_price is not None else px * 0.98
    open_count = db.query(PaperTrade).filter(PaperTrade.status == "open").count()
    daily = daily_realized_pnl(db)
    risk = RiskManager().check_trade_allowed(
        account_value=account_value,
        open_positions=open_count,
        daily_pnl=daily,
        entry=px,
        stop=stop,
        asset_type=asset_type,
        ticker=symbol,
        is_live=False,
    )
    if not risk.allowed:
        return None, f"RiskManager: {risk.reason}"

    # Cap manual size to suggested when larger.
    qty = min(quantity, risk.suggested_size) if risk.suggested_size > 0 else quantity
    if qty <= 0:
        return None, "Suggested size is zero"

    trade = PaperTrade(
        ticker=symbol,
        asset_type=asset_type,
        side="long",
        quantity=qty,
        entry_price=px,
        stop_price=stop,
        target_price=target_price or (px + 3 * (px - stop)),
        status="open",
        rationale=rationale,
        is_live=False,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade, "ok"


def close_trade(db: Session, trade_id: int) -> tuple[Optional[PaperTrade], str]:
    trade = db.query(PaperTrade).filter(PaperTrade.id == trade_id).first()
    if not trade:
        return None, "Trade not found"
    if trade.status != "open":
        return None, "Trade already closed"

    px = _quote_price(trade.ticker, trade.asset_type or "equity")
    if px is None:
        return None, f"Could not fetch live exit price for {trade.ticker}"

    trade.exit_price = px
    trade.realized_pnl = (px - trade.entry_price) * trade.quantity
    trade.status = "closed"
    trade.closed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(trade)
    try:
        from services import adaptive_agent

        adaptive_agent.learn_from_closed_trade(db, trade)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Adaptive learn on close failed: %s", type(exc).__name__)
    return trade, "ok"


def daily_realized_pnl(db: Session) -> float:
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    today = datetime.now(et).date()
    total = 0.0
    for t in db.query(PaperTrade).filter(PaperTrade.status == "closed").all():
        if t.closed_at is None or t.realized_pnl is None:
            continue
        closed = t.closed_at
        if closed.tzinfo is None:
            closed = closed.replace(tzinfo=timezone.utc)
        if closed.astimezone(et).date() == today:
            total += float(t.realized_pnl)
    return total


def portfolio_stats(db: Session, *, starting_cash: float = DEFAULT_STARTING_CASH) -> dict[str, Any]:
    opens = list_trades(db, status="open")
    closed = list_trades(db, status="closed")

    realized = sum(float(t.realized_pnl or 0) for t in closed)
    open_pnl = 0.0
    open_pnl_known = True
    for t in opens:
        u = unrealized_pnl(t)
        if u is None:
            open_pnl_known = False
        else:
            open_pnl += u

    wins = [t for t in closed if (t.realized_pnl or 0) > 0]
    losses = [t for t in closed if (t.realized_pnl or 0) < 0]
    win_rate = (len(wins) / len(closed) * 100.0) if closed else None

    account_value = starting_cash + realized + (open_pnl if open_pnl_known else 0.0)
    return {
        "starting_cash": starting_cash,
        "account_value": round(account_value, 2),
        "open_pnl": round(open_pnl, 2) if open_pnl_known else None,
        "realized_pnl": round(realized, 2),
        "daily_pnl": round(daily_realized_pnl(db), 2),
        "win_rate": round(win_rate, 2) if win_rate is not None else None,
        "open_positions": len(opens),
        "closed_trades": len(closed),
    }


def trade_to_dict(trade: PaperTrade) -> dict[str, Any]:
    u = unrealized_pnl(trade) if trade.status == "open" else trade.realized_pnl
    mark = None
    if trade.status == "open":
        mark = _quote_price(trade.ticker, trade.asset_type or "equity")
    return {
        "id": trade.id,
        "ticker": trade.ticker,
        "asset_type": trade.asset_type,
        "side": trade.side,
        "quantity": trade.quantity,
        "entry_price": trade.entry_price,
        "stop_price": trade.stop_price,
        "target_price": trade.target_price,
        "exit_price": trade.exit_price,
        "mark_price": mark,
        "unrealized_pnl": u,
        "realized_pnl": trade.realized_pnl,
        "status": trade.status,
        "rationale": trade.rationale,
        "alpaca_order_id": trade.alpaca_order_id,
        "opened_at": trade.opened_at.isoformat() if trade.opened_at else None,
        "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
        "is_live": trade.is_live,
    }


def list_watchlist(db: Session) -> list[WatchlistItem]:
    return db.query(WatchlistItem).order_by(WatchlistItem.ticker).all()


def add_watchlist(db: Session, ticker: str, asset_type: str = "equity", notes: Optional[str] = None) -> WatchlistItem:
    symbol = validate_ticker(ticker)
    existing = db.query(WatchlistItem).filter(WatchlistItem.ticker == symbol).first()
    if existing:
        return existing
    item = WatchlistItem(ticker=symbol, asset_type=asset_type, notes=notes)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def remove_watchlist(db: Session, ticker: str) -> bool:
    symbol = validate_ticker(ticker)
    item = db.query(WatchlistItem).filter(WatchlistItem.ticker == symbol).first()
    if not item:
        return False
    db.delete(item)
    db.commit()
    return True


def list_lessons(db: Session, limit: int = 50) -> list[LessonLog]:
    return (
        db.query(LessonLog)
        .order_by(LessonLog.created_at.desc())
        .limit(limit)
        .all()
    )
