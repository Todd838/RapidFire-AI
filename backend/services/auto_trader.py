"""Autonomous paper trader with mandatory dry-run-first safety.

Dry-run (default): runs the full decision pipeline and writes AutoTradeLog
rows for what *would* be traded — no broker orders are placed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from config import get_settings
from models import AutoTradeLog, PaperTrade, WatchlistItem
from services.alpaca_service import AlpacaService, RiskGateError
from services.risk_manager import RiskManager
from services.signal_engine import compute_signals

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

DEFAULT_MIN_CONFIDENCE = 70.0
MAX_NEW_TRADES_PER_DAY = 3


class AutoTrader:
    """Scan watchlist, gate with RiskManager, optionally place (or dry-run) orders."""

    def __init__(
        self,
        db: Session,
        *,
        dry_run: Optional[bool] = None,
        risk_manager: Optional[RiskManager] = None,
        alpaca: Optional[AlpacaService] = None,
        account_value: float = 10_000.0,
    ) -> None:
        settings = get_settings()
        self.db = db
        self.dry_run = settings.auto_trader_dry_run if dry_run is None else dry_run
        self.risk = risk_manager or RiskManager()
        self.alpaca = alpaca or AlpacaService(paper=True)
        self.account_value = account_value
        self._trading_locked_until: Optional[datetime] = None

    def _log(
        self,
        action: str,
        reason: str,
        *,
        ticker: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> AutoTradeLog:
        row = AutoTradeLog(
            ticker=ticker,
            action=action,
            reason=reason,
            details_json=json.dumps(details) if details else None,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        logger.info(
            "AutoTradeLog action=%s ticker=%s reason=%s dry_run=%s",
            action,
            ticker,
            reason,
            self.dry_run,
        )
        return row

    def is_market_open(self, *, asset_type: str = "equity", now: Optional[datetime] = None) -> bool:
        """Stocks: weekdays 9:30–15:45 ET. Crypto: 24/7."""
        if asset_type == "crypto":
            return True
        now_et = (now or datetime.now(timezone.utc)).astimezone(ET)
        if now_et.weekday() >= 5:
            return False
        start = time(9, 30)
        end = time(15, 45)
        t = now_et.time()
        return start <= t <= end

    def _open_position_count(self) -> int:
        return (
            self.db.query(PaperTrade)
            .filter(PaperTrade.status == "open")
            .count()
        )

    def _daily_realized_pnl(self) -> float:
        today = datetime.now(ET).date()
        rows = (
            self.db.query(PaperTrade)
            .filter(PaperTrade.status == "closed", PaperTrade.closed_at.isnot(None))
            .all()
        )
        total = 0.0
        for trade in rows:
            if trade.closed_at is None or trade.realized_pnl is None:
                continue
            closed_et = trade.closed_at
            if closed_et.tzinfo is None:
                closed_et = closed_et.replace(tzinfo=timezone.utc)
            if closed_et.astimezone(ET).date() == today:
                total += float(trade.realized_pnl)
        return total

    def _trades_opened_today(self) -> int:
        """Count real trades + dry-run would_trade decisions for today's cap."""
        today = datetime.now(ET).date()
        count = 0
        for trade in self.db.query(PaperTrade).all():
            opened = trade.opened_at
            if opened is None:
                continue
            if opened.tzinfo is None:
                opened = opened.replace(tzinfo=timezone.utc)
            if opened.astimezone(ET).date() == today:
                count += 1
        for row in self.db.query(AutoTradeLog).filter(AutoTradeLog.action == "would_trade").all():
            created = row.created_at
            if created is None:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created.astimezone(ET).date() == today:
                count += 1
        return count

    def run_scan_cycle(self) -> dict[str, Any]:
        """One scan pass over the watchlist. max_instances=1 is enforced by scheduler later."""
        summary: dict[str, Any] = {
            "dry_run": self.dry_run,
            "scanned": 0,
            "skipped": 0,
            "would_trade": 0,
            "traded": 0,
            "errors": 0,
        }

        if self._trading_locked_until and datetime.now(timezone.utc) < self._trading_locked_until:
            self._log(
                "skip",
                f"Trading lock active until {self._trading_locked_until.isoformat()}",
            )
            summary["skipped"] += 1
            return summary

        daily_pnl = self._daily_realized_pnl()
        # Kill-switch pre-check via RiskManager with dummy levels.
        kill = self.risk.check_trade_allowed(
            account_value=self.account_value,
            open_positions=self._open_position_count(),
            daily_pnl=daily_pnl,
            entry=100.0,
            stop=90.0,
            asset_type="equity",
            ticker="SPY",
            is_live=False,
        )
        if not kill.allowed and "kill" in kill.reason.lower():
            self._log("skip", kill.reason)
            summary["skipped"] += 1
            return summary

        watchlist = self.db.query(WatchlistItem).all()
        if not watchlist:
            self._log("skip", "Watchlist empty — nothing to scan")
            return summary

        new_today = self._trades_opened_today()

        for item in watchlist:
            summary["scanned"] += 1
            ticker = item.ticker.upper()
            asset_type = item.asset_type or "equity"

            if not self.is_market_open(asset_type=asset_type):
                self._log("skip", "Outside market hours", ticker=ticker)
                summary["skipped"] += 1
                continue

            if new_today >= MAX_NEW_TRADES_PER_DAY:
                self._log(
                    "skip",
                    f"Max new trades/day reached ({MAX_NEW_TRADES_PER_DAY})",
                    ticker=ticker,
                )
                summary["skipped"] += 1
                continue

            try:
                from services import adaptive_agent

                policy = adaptive_agent.get_policy(self.db)
                raw = compute_signals(ticker)
                signal = adaptive_agent.apply_policy(raw, policy)
                min_conf = policy.min_confidence
            except Exception as exc:  # noqa: BLE001
                self._log(
                    "error",
                    f"Signal computation failed: {type(exc).__name__}",
                    ticker=ticker,
                )
                summary["errors"] += 1
                continue

            if signal.confidence < min_conf or signal.action != "BUY":
                self._log(
                    "skip",
                    f"Signal {signal.action} conf={signal.confidence:.0f} below gate "
                    f"(need BUY >= {min_conf:.0f})",
                    ticker=ticker,
                    details={"action": signal.action, "confidence": signal.confidence},
                )
                summary["skipped"] += 1
                continue

            if signal.entry_zone is None or signal.stop_price is None:
                self._log("skip", "Missing entry/stop from signal", ticker=ticker)
                summary["skipped"] += 1
                continue

            risk = self.risk.check_trade_allowed(
                account_value=self.account_value,
                open_positions=self._open_position_count(),
                daily_pnl=daily_pnl,
                entry=signal.entry_zone,
                stop=signal.stop_price,
                asset_type=asset_type,
                ticker=ticker,
                is_live=False,
            )
            if not risk.allowed:
                self._log("skip", f"RiskManager: {risk.reason}", ticker=ticker)
                summary["skipped"] += 1
                continue

            from services import adaptive_agent as _aa

            details = {
                "action": signal.action,
                "confidence": signal.confidence,
                "entry": signal.entry_zone,
                "stop": signal.stop_price,
                "target": signal.target_price,
                "size": risk.suggested_size,
                "reasoning": signal.reasoning,
                "dry_run": self.dry_run,
                "adaptive_version": policy.version,
                "signal_snapshot": json.loads(_aa.snapshot_from_signal(signal)),
            }

            if self.dry_run:
                self._log(
                    "would_trade",
                    f"DRY-RUN would buy {risk.suggested_size} {ticker} @≈{signal.entry_zone}",
                    ticker=ticker,
                    details=details,
                )
                summary["would_trade"] += 1
                new_today += 1
                continue

            # Live execution path — still must pass AlpacaService risk gate.
            try:
                order = self.alpaca.place_market_order(
                    ticker=ticker,
                    qty=risk.suggested_size,
                    side="buy",
                    risk=risk,
                    dry_run=False,
                    stop_price=signal.stop_price,
                    take_profit=signal.target_price,
                    use_bracket=(asset_type == "equity"),
                )
            except RiskGateError as exc:
                self._log("error", str(exc), ticker=ticker)
                summary["errors"] += 1
                continue

            if not order.ok:
                self._log("error", order.detail, ticker=ticker, details={"status": order.status})
                summary["errors"] += 1
                continue

            trade = PaperTrade(
                ticker=ticker,
                asset_type=asset_type,
                side="long",
                quantity=risk.suggested_size,
                entry_price=signal.entry_zone,
                stop_price=signal.stop_price,
                target_price=signal.target_price,
                status="open",
                rationale=signal.reasoning,
                signal_snapshot_json=_aa.snapshot_from_signal(signal),
                alpaca_order_id=order.order_id,
                is_live=False,
            )
            self.db.add(trade)
            self.db.commit()
            self._log(
                "trade",
                f"Bought {risk.suggested_size} {ticker}",
                ticker=ticker,
                details={**details, "order_id": order.order_id},
            )
            summary["traded"] += 1
            new_today += 1

        return summary

    def emergency_close_all(self) -> dict[str, Any]:
        """Close everything at live quotes, set 24h trading lock, log every action."""
        from services import portfolio_service

        closed = 0
        opens = self.db.query(PaperTrade).filter(PaperTrade.status == "open").all()
        for trade in opens:
            px = portfolio_service._quote_price(trade.ticker, trade.asset_type or "equity")
            if px is None:
                # Last resort: flat close if quote unavailable (still log).
                px = trade.entry_price
                self._log(
                    "error",
                    f"Emergency close used entry as exit (quote unavailable) for {trade.ticker}",
                    ticker=trade.ticker,
                )
            trade.exit_price = px
            trade.realized_pnl = (px - trade.entry_price) * trade.quantity
            trade.status = "closed"
            trade.closed_at = datetime.now(timezone.utc)
            closed += 1
            self._log(
                "close",
                f"Emergency close {trade.ticker} qty={trade.quantity} @ {px}",
                ticker=trade.ticker,
            )
        self.db.commit()
        self._trading_locked_until = datetime.now(timezone.utc) + timedelta(hours=24)
        self._log(
            "skip",
            f"Emergency lock engaged until {self._trading_locked_until.isoformat()}",
        )
        return {
            "closed": closed,
            "locked_until": self._trading_locked_until.isoformat(),
            "dry_run": self.dry_run,
        }

    def monitor_positions(self) -> dict[str, Any]:
        """Enforce crypto stops/targets (Alpaca has no crypto brackets).

        Equities rely on broker bracket orders; crypto is monitored here every 5 min.
        Also flags positions held > 5 days for thesis review.
        """
        from services import claude_service, portfolio_service

        summary = {"checked": 0, "closed": 0, "flagged": 0, "errors": 0}
        opens = self.db.query(PaperTrade).filter(PaperTrade.status == "open").all()
        now = datetime.now(timezone.utc)

        for trade in opens:
            summary["checked"] += 1
            opened = trade.opened_at
            if opened.tzinfo is None:
                opened = opened.replace(tzinfo=timezone.utc)
            age_days = (now - opened).total_seconds() / 86400.0

            if age_days > 5:
                summary["flagged"] += 1
                try:
                    sig = compute_signals(trade.ticker)
                    thesis = claude_service.review_thesis_still_holds(
                        portfolio_service.trade_to_dict(trade),
                        {
                            "action": sig.action,
                            "confidence": sig.confidence,
                            "reasoning": sig.reasoning,
                        },
                    )
                    self._log(
                        "skip",
                        f"Thesis review (>5d): {thesis[:500]}",
                        ticker=trade.ticker,
                        details={"age_days": age_days, "signal": sig.action},
                    )
                except Exception as exc:  # noqa: BLE001
                    self._log(
                        "error",
                        f"Thesis review failed: {type(exc).__name__}",
                        ticker=trade.ticker,
                    )
                    summary["errors"] += 1

            # Crypto stop/target enforcement (equities: brackets at broker).
            if (trade.asset_type or "equity") != "crypto":
                continue

            px = portfolio_service._quote_price(trade.ticker, "crypto")
            if px is None:
                summary["errors"] += 1
                self._log("error", "Crypto monitor: quote unavailable", ticker=trade.ticker)
                continue

            hit_stop = trade.stop_price is not None and px <= trade.stop_price
            hit_target = trade.target_price is not None and px >= trade.target_price
            if not (hit_stop or hit_target):
                continue

            if self.dry_run:
                self._log(
                    "would_trade",
                    f"DRY-RUN would close crypto {trade.ticker} @ {px} "
                    f"({'stop' if hit_stop else 'target'})",
                    ticker=trade.ticker,
                )
                continue

            trade.exit_price = px
            trade.realized_pnl = (px - trade.entry_price) * trade.quantity
            trade.status = "closed"
            trade.closed_at = now
            self.db.commit()
            summary["closed"] += 1
            self._log(
                "close",
                f"Crypto {'stop' if hit_stop else 'target'} hit @ {px}",
                ticker=trade.ticker,
            )
            try:
                from services import adaptive_agent

                adaptive_agent.learn_from_closed_trade(self.db, trade)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Adaptive learn failed: %s", type(exc).__name__)

        return summary
