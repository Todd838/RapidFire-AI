"""Market data HTTP endpoints."""

from fastapi import APIRouter, Query

from schemas import (
    HistoryResponse,
    IpoListResponse,
    MarketMoversResponse,
    QuoteResponse,
)
from services import market_data
from services.validation import validate_ticker

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/quote/{ticker}", response_model=QuoteResponse)
def stock_quote(ticker: str) -> QuoteResponse:
    """Get a stock quote (cached ~30s)."""
    return market_data.get_stock_quote(validate_ticker(ticker))


@router.get("/crypto/{ticker}", response_model=QuoteResponse)
def crypto_quote(ticker: str) -> QuoteResponse:
    """Get a crypto quote (CoinGecko → yfinance fallback)."""
    return market_data.get_crypto_quote(validate_ticker(ticker))


@router.get("/history/{ticker}", response_model=HistoryResponse)
def history(
    ticker: str,
    days: int = Query(default=90, ge=1, le=3650),
) -> HistoryResponse:
    """Get daily OHLCV history."""
    return market_data.get_history(validate_ticker(ticker), days=days)


@router.get("/movers", response_model=MarketMoversResponse)
def movers() -> MarketMoversResponse:
    """Get gainers / losers from a liquid universe."""
    return market_data.get_market_movers()


@router.get("/ipos", response_model=IpoListResponse)
def ipos() -> IpoListResponse:
    """Get recent/upcoming IPOs when a data provider supports it."""
    return market_data.get_new_ipos()
