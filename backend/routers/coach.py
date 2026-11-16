"""Claude coaching endpoints — SSE for ask, JSON for the rest."""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services import claude_service, market_data
from services.signal_engine import compute_signals
from services.validation import validate_ticker

router = APIRouter(prefix="/api/coach", tags=["coach"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    context: Optional[str] = Field(default=None, max_length=8000)
    stream: bool = True


class AnalyzeSignalRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    signal: Optional[dict[str, Any]] = None


class ReviewPortfolioRequest(BaseModel):
    positions: list[dict[str, Any]] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


class DiscoverRequest(BaseModel):
    focus: str = Field(default="general", max_length=500)


class CoachTextResponse(BaseModel):
    text: str


@router.post("/ask")
def ask(body: AskRequest):
    """Educational Q&A. SSE when stream=true, else JSON {text}."""
    if body.stream:

        def event_gen():
            for chunk in claude_service.ask_coach_stream(body.question, body.context):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield "data: {\"done\": true}\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    return CoachTextResponse(text=claude_service.ask_coach(body.question, body.context))


@router.post("/analyze-signal", response_model=CoachTextResponse)
def analyze_signal(body: AnalyzeSignalRequest) -> CoachTextResponse:
    symbol = validate_ticker(body.ticker)
    signal = body.signal
    if signal is None:
        result = compute_signals(symbol)
        signal = {
            "ticker": result.ticker,
            "action": result.action,
            "confidence": result.confidence,
            "entry_zone": result.entry_zone,
            "stop_price": result.stop_price,
            "target_price": result.target_price,
            "reasoning": result.reasoning,
            "indicators": result.indicators,
        }
    return CoachTextResponse(text=claude_service.analyze_signal(signal))


@router.post("/review-portfolio", response_model=CoachTextResponse)
def review_portfolio(body: ReviewPortfolioRequest) -> CoachTextResponse:
    return CoachTextResponse(
        text=claude_service.review_portfolio(body.positions, body.stats)
    )


@router.post("/discover", response_model=CoachTextResponse)
def discover(body: DiscoverRequest) -> CoachTextResponse:
    movers = market_data.get_market_movers()
    ipos = market_data.get_new_ipos()
    snapshot = {
        "gainers": [m.model_dump() for m in movers.gainers[:5]],
        "losers": [m.model_dump() for m in movers.losers[:5]],
        "ipos": [i.model_dump() for i in ipos.items[:5]],
        "ipo_note": ipos.error,
    }
    return CoachTextResponse(
        text=claude_service.discover_assets(body.focus, snapshot)
    )
