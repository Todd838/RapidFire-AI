"""Input validation helpers for HTTP endpoints."""

from __future__ import annotations

import re

from fastapi import HTTPException

# Tickers: 1–12 chars, letters/digits/.- (covers BRK.B, BTC-USD).
_TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,11}$")


def validate_ticker(ticker: str) -> str:
    """Normalize and validate a ticker path/query param."""
    cleaned = (ticker or "").strip().upper()
    if not cleaned or not _TICKER_RE.match(cleaned):
        raise HTTPException(
            status_code=422,
            detail="Invalid ticker. Use 1–12 chars: letters, digits, '.', or '-'.",
        )
    return cleaned
