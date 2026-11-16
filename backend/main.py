"""RapidFire AI — FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database import init_db
from routers import (
    agent,
    auto_trader,
    coach,
    discover,
    journal,
    market,
    performance,
    portfolio,
    signals,
)
from schemas import HealthResponse
from services.logging_filters import install_secret_redaction
from services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
install_secret_redaction()
logger = logging.getLogger("rapidfire")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create DB tables and start background jobs."""
    logger.info("Starting RapidFire AI — initializing database tables")
    init_db()
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("Shutting down RapidFire AI")


app = FastAPI(
    title="RapidFire AI",
    description="Educational trading coach with paper-first autonomous trading.",
    version="0.6.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market.router)
app.include_router(signals.router)
app.include_router(auto_trader.router)
app.include_router(coach.router)
app.include_router(portfolio.router)
app.include_router(discover.router)
app.include_router(performance.router)
app.include_router(journal.router)
app.include_router(agent.router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — does not expose secrets."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="rapidfire",
        live_trading_enabled=settings.live_trading_enabled,
        alpaca_paper=settings.alpaca_paper,
    )
