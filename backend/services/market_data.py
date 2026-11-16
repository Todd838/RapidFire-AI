"""Market data service: yfinance first, Polygon when a key is present.

Every external call uses a timeout, error handling, and graceful fallback.
Quotes are cached for 30 seconds to reduce rate-limit pressure.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx
import yfinance as yf

from config import get_settings
from schemas import (
    HistoryBar,
    HistoryResponse,
    IpoItem,
    IpoListResponse,
    MarketMoversResponse,
    MoverItem,
    QuoteResponse,
)

logger = logging.getLogger(__name__)

# Simple in-process quote cache: ticker -> (expires_at_epoch, QuoteResponse)
_quote_cache: dict[str, tuple[float, QuoteResponse]] = {}

# Common liquid names used when scanning movers via yfinance (no invented APIs).
_MOVER_UNIVERSE = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "AMD",
    "NFLX",
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "JPM",
    "BAC",
    "XOM",
    "CVX",
    "COST",
    "WMT",
    "DIS",
]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _cache_get(ticker: str) -> Optional[QuoteResponse]:
    settings = get_settings()
    entry = _quote_cache.get(ticker.upper())
    if not entry:
        return None
    expires_at, quote = entry
    if time.time() >= expires_at:
        _quote_cache.pop(ticker.upper(), None)
        return None
    # Respect configured TTL (already baked into expires_at).
    _ = settings.quote_cache_ttl_seconds
    return quote


def _cache_set(ticker: str, quote: QuoteResponse) -> None:
    settings = get_settings()
    _quote_cache[ticker.upper()] = (
        time.time() + settings.quote_cache_ttl_seconds,
        quote,
    )


def _polygon_configured() -> bool:
    return bool(get_settings().polygon_api_key.strip())


def _polygon_get(path: str, params: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """GET from Polygon REST API. Returns None on any failure."""
    settings = get_settings()
    if not settings.polygon_api_key.strip():
        return None

    url = f"https://api.polygon.io{path}"
    query = dict(params or {})
    query["apiKey"] = settings.polygon_api_key

    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.get(url, params=query)
            response.raise_for_status()
            return response.json()
    except Exception as exc:  # noqa: BLE001 — graceful fallback required
        logger.warning("Polygon request failed for %s: %s", path, type(exc).__name__)
        return None


def _yfinance_quote(ticker: str) -> QuoteResponse:
    """Fetch a quote via yfinance with graceful error payload."""
    symbol = ticker.upper().strip()
    try:
        info_ticker = yf.Ticker(symbol)
        # Prefer fast_info when available; fall back to last close from history.
        price: Optional[float] = None
        change_pct: Optional[float] = None
        volume: Optional[float] = None

        try:
            fast = info_ticker.fast_info
            price = float(getattr(fast, "last_price", None) or getattr(fast, "lastPrice", None) or 0) or None
            prev = getattr(fast, "previous_close", None) or getattr(fast, "previousClose", None)
            if price and prev:
                change_pct = ((price - float(prev)) / float(prev)) * 100.0
            vol = getattr(fast, "last_volume", None) or getattr(fast, "lastVolume", None)
            if vol is not None:
                volume = float(vol)
        except Exception:  # noqa: BLE001
            price = None

        if price is None or price <= 0:
            hist = info_ticker.history(period="5d", auto_adjust=True)
            if hist is None or hist.empty:
                return QuoteResponse(
                    ticker=symbol,
                    price=0.0,
                    source="yfinance",
                    as_of=_now_utc(),
                    error=f"No quote data for {symbol}",
                )
            closes = hist["Close"].dropna()
            price = float(closes.iloc[-1])
            if len(closes) >= 2:
                prev_close = float(closes.iloc[-2])
                if prev_close:
                    change_pct = ((price - prev_close) / prev_close) * 100.0
            if "Volume" in hist.columns:
                volume = float(hist["Volume"].dropna().iloc[-1])

        return QuoteResponse(
            ticker=symbol,
            price=float(price),
            change_pct=change_pct,
            volume=volume,
            source="yfinance",
            as_of=_now_utc(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance quote failed for %s: %s", symbol, type(exc).__name__)
        return QuoteResponse(
            ticker=symbol,
            price=0.0,
            source="yfinance",
            as_of=_now_utc(),
            error=f"Quote fetch failed for {symbol}",
        )


def _polygon_stock_quote(ticker: str) -> Optional[QuoteResponse]:
    """Try Polygon previous-day aggregate as a quote proxy."""
    symbol = ticker.upper().strip()
    data = _polygon_get(f"/v2/aggs/ticker/{symbol}/prev", {"adjusted": "true"})
    if not data or data.get("status") not in {"OK", "DELAYED"}:
        return None
    results = data.get("results") or []
    if not results:
        return None
    bar = results[0]
    close = float(bar.get("c") or 0)
    open_px = float(bar.get("o") or 0)
    change_pct = ((close - open_px) / open_px * 100.0) if open_px else None
    return QuoteResponse(
        ticker=symbol,
        price=close,
        change_pct=change_pct,
        volume=float(bar.get("v") or 0) or None,
        source="polygon",
        as_of=_now_utc(),
    )


def get_stock_quote(ticker: str) -> QuoteResponse:
    """Return a stock quote. Polygon if configured, else yfinance. Cached 30s."""
    symbol = ticker.upper().strip()
    cached = _cache_get(symbol)
    if cached is not None:
        return cached

    quote: Optional[QuoteResponse] = None
    if _polygon_configured():
        quote = _polygon_stock_quote(symbol)

    if quote is None or quote.price <= 0 or quote.error:
        quote = _yfinance_quote(symbol)

    if quote.error is None and quote.price > 0:
        _cache_set(symbol, quote)
    return quote


def get_crypto_quote(ticker: str) -> QuoteResponse:
    """Return a crypto quote. Accepts BTC-USD / ETH-USD style tickers.

    Uses CoinGecko as a free fallback path, then yfinance.
    """
    symbol = ticker.upper().strip()
    cached = _cache_get(f"crypto:{symbol}")
    if cached is not None:
        return cached

    # Map common symbols to CoinGecko ids.
    cg_map = {
        "BTC-USD": "bitcoin",
        "BTC": "bitcoin",
        "ETH-USD": "ethereum",
        "ETH": "ethereum",
        "SOL-USD": "solana",
        "SOL": "solana",
    }
    cg_id = cg_map.get(symbol)
    settings = get_settings()

    if cg_id:
        try:
            with httpx.Client(timeout=settings.http_timeout_seconds) as client:
                resp = client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={
                        "ids": cg_id,
                        "vs_currencies": "usd",
                        "include_24hr_change": "true",
                    },
                )
                resp.raise_for_status()
                payload = resp.json().get(cg_id) or {}
                price = float(payload.get("usd") or 0)
                if price > 0:
                    quote = QuoteResponse(
                        ticker=symbol if "-" in symbol else f"{symbol}-USD",
                        price=price,
                        change_pct=float(payload["usd_24h_change"])
                        if payload.get("usd_24h_change") is not None
                        else None,
                        source="coingecko",
                        as_of=_now_utc(),
                    )
                    _cache_set(f"crypto:{symbol}", quote)
                    return quote
        except Exception as exc:  # noqa: BLE001
            logger.warning("CoinGecko quote failed for %s: %s", symbol, type(exc).__name__)

    # Fallback: yfinance expects tickers like BTC-USD.
    yf_symbol = symbol if "-" in symbol else f"{symbol}-USD"
    quote = _yfinance_quote(yf_symbol)
    quote.source = "yfinance"
    if quote.error is None and quote.price > 0:
        _cache_set(f"crypto:{symbol}", quote)
    return quote


def get_history(ticker: str, days: int = 90) -> HistoryResponse:
    """Return daily OHLCV history. Polygon if configured, else yfinance."""
    symbol = ticker.upper().strip()
    days = max(1, min(days, 3650))

    if _polygon_configured():
        # Polygon aggregates: /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}
        end = date.today()
        start = date.fromordinal(end.toordinal() - days - 5)
        data = _polygon_get(
            f"/v2/aggs/ticker/{symbol}/range/1/day/{start.isoformat()}/{end.isoformat()}",
            {"adjusted": "true", "sort": "asc", "limit": 50000},
        )
        if data and data.get("results"):
            bars: list[HistoryBar] = []
            for row in data["results"]:
                ts_ms = row.get("t")
                if ts_ms is None:
                    continue
                bar_date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
                bars.append(
                    HistoryBar(
                        date=bar_date,
                        open=float(row.get("o") or 0),
                        high=float(row.get("h") or 0),
                        low=float(row.get("l") or 0),
                        close=float(row.get("c") or 0),
                        volume=float(row.get("v") or 0),
                    )
                )
            # Keep the most recent `days` bars.
            bars = bars[-days:]
            if bars:
                return HistoryResponse(ticker=symbol, days=days, bars=bars, source="polygon")

    try:
        hist = yf.Ticker(symbol).history(period=f"{days + 10}d", auto_adjust=True)
        if hist is None or hist.empty:
            return HistoryResponse(
                ticker=symbol,
                days=days,
                bars=[],
                source="yfinance",
                error=f"No history for {symbol}",
            )
        bars = []
        for idx, row in hist.tail(days).iterrows():
            bar_date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
            bars.append(
                HistoryBar(
                    date=bar_date,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row.get("Volume") or 0),
                )
            )
        return HistoryResponse(ticker=symbol, days=days, bars=bars, source="yfinance")
    except Exception as exc:  # noqa: BLE001
        logger.warning("History fetch failed for %s: %s", symbol, type(exc).__name__)
        return HistoryResponse(
            ticker=symbol,
            days=days,
            bars=[],
            source="yfinance",
            error=f"History fetch failed for {symbol}",
        )


def get_market_movers() -> MarketMoversResponse:
    """Return simple gainers/losers from a liquid universe (yfinance).

    Polygon snapshot endpoints require a paid plan; we avoid inventing access
    and use a deterministic scan of liquid tickers instead.
    """
    quotes: list[MoverItem] = []
    for symbol in _MOVER_UNIVERSE:
        q = get_stock_quote(symbol)
        if q.error or q.price <= 0 or q.change_pct is None:
            continue
        quotes.append(
            MoverItem(
                ticker=q.ticker,
                price=q.price,
                change_pct=q.change_pct,
                volume=q.volume,
            )
        )

    if not quotes:
        return MarketMoversResponse(
            source="yfinance",
            error="Unable to compute movers right now",
        )

    ranked = sorted(quotes, key=lambda m: m.change_pct or 0.0, reverse=True)
    return MarketMoversResponse(
        gainers=ranked[:5],
        losers=list(reversed(ranked[-5:])),
        source="yfinance",
    )


def get_new_ipos() -> IpoListResponse:
    """Best-effort IPO list.

    yfinance does not expose a stable public IPO calendar API. When Polygon is
    configured we attempt their vX reference endpoint; otherwise return a clear
    empty result with an explanatory error (no invented data).
    """
    if _polygon_configured():
        # Official Polygon reference IPOs endpoint (docs: /vX/reference/ipos).
        data = _polygon_get("/vX/reference/ipos", {"limit": 20, "order": "desc", "sort": "listing_date"})
        if data and data.get("results"):
            items: list[IpoItem] = []
            for row in data["results"]:
                items.append(
                    IpoItem(
                        ticker=str(row.get("ticker") or row.get("issuer_name") or "UNKNOWN"),
                        name=row.get("issuer_name") or row.get("company_name"),
                        exchange=row.get("primary_exchange") or row.get("exchange"),
                        ipo_date=str(row.get("listing_date") or row.get("announced_date") or ""),
                        notes=row.get("ipo_status"),
                    )
                )
            return IpoListResponse(items=items, source="polygon")

    return IpoListResponse(
        items=[],
        source="none",
        error=(
            "IPO calendar requires Polygon.io (set POLYGON_API_KEY). "
            "yfinance has no stable public IPO endpoint; no synthetic IPOs are returned."
        ),
    )
