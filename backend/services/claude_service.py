"""All Claude/Anthropic calls go through this module. Model from CLAUDE_MODEL."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any, Optional

from anthropic import Anthropic, APIError
from config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are RapidFire AI, an educational trading coach — not a financial advisor.

Rules:
- Always frame output as education. Never present recommendations as financial advice.
- Explain WHY: setup quality, risks, entry zone, stop, invalidation criteria.
- Be clear, structured, and concise. Prefer bullet points for risks and levels.
- If data is incomplete, say what is missing instead of inventing numbers.
- End substantial answers with a short reminder that this is educational only.
"""


def _client() -> Anthropic:
    settings = get_settings()
    if not settings.anthropic_api_key.strip():
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    # Official SDK; timeout via http client default — wrap calls with try/except.
    return Anthropic(api_key=settings.anthropic_api_key, timeout=60.0)


def _model() -> str:
    return get_settings().claude_model


def _complete(user_content: str, *, max_tokens: int = 1200) -> str:
    """Non-streaming completion. Returns graceful error text on failure."""
    try:
        client = _client()
        msg = client.messages.create(
            model=_model(),
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        parts = []
        for block in msg.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts).strip() or "(empty response)"
    except RuntimeError as exc:
        return f"Coach unavailable: {exc}"
    except APIError as exc:
        logger.warning("Anthropic API error: %s", type(exc).__name__)
        return f"Coach API error: {type(exc).__name__}. Try again shortly."
    except Exception as exc:  # noqa: BLE001
        logger.warning("Claude call failed: %s", type(exc).__name__)
        return f"Coach error: {type(exc).__name__}"


def ask_coach(question: str, context: Optional[str] = None) -> str:
    """Answer an educational trading question."""
    body = question.strip()
    if context:
        body = f"Context:\n{context}\n\nQuestion:\n{body}"
    return _complete(body)


def ask_coach_stream(question: str, context: Optional[str] = None) -> Iterator[str]:
    """Yield text deltas for SSE streaming."""
    body = question.strip()
    if context:
        body = f"Context:\n{context}\n\nQuestion:\n{body}"
    try:
        client = _client()
        with client.messages.stream(
            model=_model(),
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": body}],
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield text
    except RuntimeError as exc:
        yield f"Coach unavailable: {exc}"
    except APIError as exc:
        logger.warning("Anthropic stream error: %s", type(exc).__name__)
        yield f"Coach API error: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Claude stream failed: %s", type(exc).__name__)
        yield f"Coach error: {type(exc).__name__}"


def analyze_signal(signal: dict[str, Any]) -> str:
    """Explain a technical signal educationally."""
    prompt = (
        "Analyze this technical signal for a student. Cover setup quality, risks, "
        "entry, stop, invalidation, and what would change your view. Data:\n"
        f"{signal}"
    )
    return _complete(prompt)


def review_portfolio(positions: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    """Educational portfolio review."""
    prompt = (
        "Review this paper portfolio for learning. Discuss concentration, open risk, "
        "and what to watch — not what to buy/sell as advice.\n"
        f"Stats: {stats}\nPositions: {positions}"
    )
    return _complete(prompt, max_tokens=1500)


def discover_assets(focus: str, market_snapshot: dict[str, Any]) -> str:
    """Educational discovery of themes / assets."""
    prompt = (
        f"Student focus: {focus}\nMarket snapshot: {market_snapshot}\n"
        "Suggest educational areas to study (IPOs, micro-caps caution, crypto, options basics). "
        "Emphasize risks and research process, not tips."
    )
    return _complete(prompt)


def write_trade_postmortem(trade: dict[str, Any]) -> str:
    """Post-mortem lesson for a closed trade."""
    prompt = (
        "Write an educational trade postmortem. What was the thesis, what happened, "
        "what lesson to keep?\n"
        f"Trade: {trade}"
    )
    return _complete(prompt)


def review_thesis_still_holds(trade: dict[str, Any], signal: dict[str, Any]) -> str:
    """Ask whether a multi-day thesis still holds (educational)."""
    prompt = (
        "This paper position has been open more than 5 days. Does the original thesis "
        "still hold based on the latest signal? Explain for learning purposes.\n"
        f"Trade: {trade}\nLatest signal: {signal}"
    )
    return _complete(prompt)


def write_monthly_report(metrics: dict[str, Any], losing_trades: list[dict[str, Any]]) -> str:
    """Monthly performance analysis for LessonLog."""
    prompt = (
        "Write a monthly educational performance report. Analyze win/loss patterns, "
        "drawdowns, and habits to improve. Not financial advice.\n"
        f"Metrics: {metrics}\nLosing trades sample: {losing_trades[:20]}"
    )
    return _complete(prompt, max_tokens=2000)


def write_readiness_verdict(checklist: dict[str, Any]) -> str:
    """Claude verdict for go-readiness (educational framing)."""
    prompt = (
        "Given this go-readiness checklist for graduating from paper to tiny live size, "
        "write a short verdict. Passing means 'not obviously broken', not proof of edge. "
        f"Checklist: {checklist}"
    )
    return _complete(prompt, max_tokens=800)
