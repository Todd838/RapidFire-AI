"""Educational journal feeds: curated learning links + live RSS headlines.

Categories:
- stock_market — markets & investing literacy
- ai_finance — AI applied to finance / trading education
- ai_agents — AI agents & autonomous systems (general)
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

# Curated educational resources (stable public URLs — not invented API endpoints).
CURATED: dict[str, list[dict[str, str]]] = {
    "stock_market": [
        {
            "title": "How the Stock Market Works (Investor.gov)",
            "url": "https://www.investor.gov/introduction-investing/investing-basics/how-stock-markets-work",
            "source": "SEC Investor.gov",
            "summary": "Plain-language intro to exchanges, brokers, and how stocks are bought and sold.",
        },
        {
            "title": "Investing Basics",
            "url": "https://www.investor.gov/introduction-investing/investing-basics",
            "source": "SEC Investor.gov",
            "summary": "Foundational topics: goals, risk, diversification, and common products.",
        },
        {
            "title": "Stocks — Investopedia Guide",
            "url": "https://www.investopedia.com/terms/s/stock.asp",
            "source": "Investopedia",
            "summary": "What equity ownership means, types of stock, and key vocabulary.",
        },
        {
            "title": "Market Indexes Explained",
            "url": "https://www.investopedia.com/terms/m/marketindex.asp",
            "source": "Investopedia",
            "summary": "How indexes like the S&P 500 summarize market performance.",
        },
        {
            "title": "Risk and Return",
            "url": "https://www.investor.gov/introduction-investing/investing-basics/investment-products",
            "source": "SEC Investor.gov",
            "summary": "How different products carry different risk/return tradeoffs.",
        },
    ],
    "ai_finance": [
        {
            "title": "Artificial Intelligence in Finance (overview)",
            "url": "https://www.investopedia.com/terms/a/artificial-intelligence-ai.asp",
            "source": "Investopedia",
            "summary": "High-level AI concepts with finance context — start here for vocabulary.",
        },
        {
            "title": "Algorithmic Trading Basics",
            "url": "https://www.investopedia.com/articles/active-trading/101014/basics-algorithmic-trading-concepts-and-examples.asp",
            "source": "Investopedia",
            "summary": "How rules-based systems execute trades; educational, not a how-to for live risk.",
        },
        {
            "title": "Robo-Advisors Explained",
            "url": "https://www.investopedia.com/terms/r/roboadvisor-roboadviser.asp",
            "source": "Investopedia",
            "summary": "How automated portfolio tools use algorithms — useful context for AI in wealth.",
        },
        {
            "title": "FINRA — Artificial Intelligence",
            "url": "https://www.finra.org/rules-guidance/key-topics/fintech/artificial-intelligence",
            "source": "FINRA",
            "summary": "Regulatory and industry perspective on AI use in financial services.",
        },
        {
            "title": "BIS — Fintech topic hub",
            "url": "https://www.bis.org/topic/fintech.htm",
            "source": "Bank for International Settlements",
            "summary": "Central-bank research hub on fintech, digital finance, and related risks.",
        },
    ],
    "ai_agents": [
        {
            "title": "Anthropic — Building Effective Agents",
            "url": "https://www.anthropic.com/engineering/building-effective-agents",
            "source": "Anthropic",
            "summary": "Practical patterns for agent workflows, tools, and evaluation.",
        },
        {
            "title": "Anthropic Docs — Claude API",
            "url": "https://docs.anthropic.com/en/docs/welcome",
            "source": "Anthropic Docs",
            "summary": "Official docs for calling Claude safely with structured prompts.",
        },
        {
            "title": "OpenAI — Agents / Assistants concepts",
            "url": "https://platform.openai.com/docs/guides/agents",
            "source": "OpenAI Docs",
            "summary": "General agent architecture concepts useful across providers.",
        },
        {
            "title": "LangChain — Agents conceptual guide",
            "url": "https://python.langchain.com/docs/concepts/agents/",
            "source": "LangChain",
            "summary": "How tool-using agents plan and act in loops (framework-level education).",
        },
        {
            "title": "Hugging Face — Agents course intro",
            "url": "https://huggingface.co/learn/agents-course/en/unit0/introduction",
            "source": "Hugging Face",
            "summary": "Free course intro on building and evaluating AI agents.",
        },
    ],
}

# Public RSS feeds (HTTP GET + XML parse). Failures fall back to curated only.
RSS_FEEDS: list[dict[str, str]] = [
    {
        "category": "stock_market",
        "name": "CNBC Top News",
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    },
    {
        "category": "stock_market",
        "name": "Yahoo Finance headlines",
        "url": "https://finance.yahoo.com/news/rssindex",
    },
    {
        "category": "ai_agents",
        "name": "Google AI Blog",
        "url": "https://blog.google/technology/ai/rss/",
    },
]


def _text(el: Optional[ET.Element]) -> str:
    if el is None or el.text is None:
        return ""
    return " ".join(el.text.split())


def _parse_rss(xml_bytes: bytes, *, limit: int = 8) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items

    # RSS 2.0
    for item in root.findall(".//item")[:limit]:
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        desc = _text(item.find("description"))
        if not title or not link:
            continue
        items.append(
            {
                "title": title[:200],
                "url": link,
                "summary": desc[:280] if desc else "Live headline from RSS.",
            }
        )

    # Atom
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//a:entry", ns)[:limit]:
            title = _text(entry.find("a:title", ns))
            link_el = entry.find("a:link", ns)
            href = link_el.get("href") if link_el is not None else ""
            summary = _text(entry.find("a:summary", ns)) or _text(entry.find("a:content", ns))
            if title and href:
                items.append(
                    {
                        "title": title[:200],
                        "url": href,
                        "summary": (summary[:280] if summary else "Live Atom entry."),
                    }
                )
    return items


def _fetch_rss(feed_url: str) -> list[dict[str, str]]:
    settings = get_settings()
    try:
        with httpx.Client(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "RapidFireAI/0.6 (educational; journal feed)"},
        ) as client:
            resp = client.get(feed_url)
            resp.raise_for_status()
            return _parse_rss(resp.content)
    except Exception as exc:  # noqa: BLE001
        host = urlparse(feed_url).netloc
        logger.warning("RSS fetch failed host=%s err=%s", host, type(exc).__name__)
        return []


def get_journal_articles() -> dict[str, Any]:
    """Return curated learning packs + best-effort live headlines per category."""
    live: dict[str, list[dict[str, Any]]] = {
        "stock_market": [],
        "ai_finance": [],
        "ai_agents": [],
    }
    feed_errors: list[str] = []

    for feed in RSS_FEEDS:
        rows = _fetch_rss(feed["url"])
        cat = feed["category"]
        if not rows:
            feed_errors.append(feed["name"])
            continue
        for row in rows[:6]:
            live[cat].append(
                {
                    **row,
                    "source": feed["name"],
                    "kind": "live",
                }
            )

    # Deduplicate ai_finance live from stock feed keywords when dedicated feed fails.
    if not live["ai_finance"]:
        for row in live["stock_market"]:
            blob = (row.get("title", "") + " " + row.get("summary", "")).lower()
            if any(k in blob for k in ("ai ", "artificial intelligence", "machine learning", "fintech")):
                live["ai_finance"].append({**row, "kind": "live"})

    categories = []
    meta = [
        (
            "stock_market",
            "Stock market",
            "Core literacy: how markets work, indexes, risk, and vocabulary.",
        ),
        (
            "ai_finance",
            "AI in finance",
            "How AI shows up in markets, algos, and financial services — educational only.",
        ),
        (
            "ai_agents",
            "AI agents",
            "Building and evaluating autonomous AI agents (tools, loops, safety).",
        ),
    ]
    for key, label, blurb in meta:
        curated = [{**a, "kind": "curated"} for a in CURATED.get(key, [])]
        categories.append(
            {
                "id": key,
                "label": label,
                "blurb": blurb,
                "curated": curated,
                "live": live.get(key, []),
            }
        )

    return {
        "categories": categories,
        "disclaimer": (
            "Educational reading list only — not financial advice. "
            "Live headlines are best-effort RSS; curated links are stable learning resources."
        ),
        "feed_errors": feed_errors,
    }
