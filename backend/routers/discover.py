"""Discover panel data endpoints."""

from fastapi import APIRouter

from schemas import IpoListResponse, MarketMoversResponse, QuoteResponse
from services import market_data

router = APIRouter(prefix="/api/discover", tags=["discover"])


@router.get("/movers", response_model=MarketMoversResponse)
def movers() -> MarketMoversResponse:
    return market_data.get_market_movers()


@router.get("/ipos", response_model=IpoListResponse)
def ipos() -> IpoListResponse:
    return market_data.get_new_ipos()


@router.get("/crypto/{ticker}", response_model=QuoteResponse)
def crypto(ticker: str) -> QuoteResponse:
    from services.validation import validate_ticker

    return market_data.get_crypto_quote(validate_ticker(ticker))
