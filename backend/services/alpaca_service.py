"""Alpaca broker adapter.

CRITICAL: place_order / place_bracket_order require a passing RiskCheckResult.
There is no bypass flag. Callers that skip RiskManager will be rejected here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from config import get_settings
from services.live_gate import is_live_trading_permitted
from services.risk_manager import RiskCheckResult

logger = logging.getLogger(__name__)

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


@dataclass
class OrderResult:
    """Normalized order placement result."""

    ok: bool
    dry_run: bool
    order_id: Optional[str]
    status: str
    detail: str
    raw: Optional[dict[str, Any]] = None


class RiskGateError(PermissionError):
    """Raised when an order is attempted without a passing risk check."""


class AlpacaService:
    """Thin Alpaca REST client. Paper by default; live only behind gates."""

    def __init__(self, *, paper: bool = True) -> None:
        self.paper = paper
        settings = get_settings()
        self._api_key = settings.alpaca_api_key
        self._secret_key = settings.alpaca_secret_key
        self._timeout = settings.http_timeout_seconds

    @property
    def base_url(self) -> str:
        if self.paper:
            return PAPER_BASE_URL
        # Live URL only when env allows — still requires readiness + UI confirm at call time.
        settings = get_settings()
        if not settings.live_trading_enabled:
            raise PermissionError(
                "Live Alpaca base URL blocked: LIVE_TRADING_ENABLED is false"
            )
        return LIVE_BASE_URL

    def _headers(self) -> dict[str, str]:
        # Never log these headers.
        return {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._secret_key,
            "Content-Type": "application/json",
        }

    def _require_risk(self, risk: RiskCheckResult) -> None:
        if risk is None or not isinstance(risk, RiskCheckResult):
            raise RiskGateError(
                "Order blocked: RiskManager.check_trade_allowed() result is required"
            )
        if not risk.allowed:
            raise RiskGateError(f"Order blocked by RiskManager: {risk.reason}")
        if risk.suggested_size <= 0:
            raise RiskGateError("Order blocked: suggested_size is zero")

    def _require_live_gates_if_needed(self, *, readiness_passed: bool) -> None:
        if self.paper:
            return
        if not is_live_trading_permitted(readiness_passed=readiness_passed):
            raise PermissionError(
                "Live order blocked: need LIVE_TRADING_ENABLED + readiness + UI confirmation"
            )

    def place_market_order(
        self,
        *,
        ticker: str,
        qty: float,
        side: str = "buy",
        risk: RiskCheckResult,
        dry_run: bool = False,
        readiness_passed: bool = False,
        stop_price: Optional[float] = None,
        take_profit: Optional[float] = None,
        use_bracket: bool = False,
    ) -> OrderResult:
        """Place an order only after RiskManager approval.

        dry_run=True logs intent and returns without calling Alpaca.
        """
        self._require_risk(risk)
        self._require_live_gates_if_needed(readiness_passed=readiness_passed)

        symbol = ticker.upper().strip()
        qty = float(qty)
        if qty <= 0:
            raise ValueError("qty must be positive")
        if abs(qty - risk.suggested_size) > 1e-9 and qty > risk.suggested_size:
            raise RiskGateError(
                f"Order blocked: qty {qty} exceeds risk-suggested size {risk.suggested_size}"
            )

        payload: dict[str, Any] = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "market",
            "time_in_force": "day",
        }
        if use_bracket and stop_price is not None and take_profit is not None:
            payload["order_class"] = "bracket"
            payload["stop_loss"] = {"stop_price": str(stop_price)}
            payload["take_profit"] = {"limit_price": str(take_profit)}

        # Never log API keys — only symbol/side/qty/dry_run.
        logger.info(
            "Order intent symbol=%s side=%s qty=%s dry_run=%s paper=%s",
            symbol,
            side,
            qty,
            dry_run,
            self.paper,
        )

        if dry_run:
            return OrderResult(
                ok=True,
                dry_run=True,
                order_id=None,
                status="dry_run",
                detail=f"Dry-run: would place {side} {qty} {symbol} (risk: {risk.reason})",
                raw={"payload": payload},
            )

        if not self._api_key or not self._secret_key:
            return OrderResult(
                ok=False,
                dry_run=False,
                order_id=None,
                status="error",
                detail="Alpaca API keys not configured",
            )

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{self.base_url}/v2/orders",
                    headers=self._headers(),
                    json=payload,
                )
                if resp.status_code >= 400:
                    # Do not echo response headers (may include auth material in misconfig).
                    logger.warning(
                        "Alpaca order rejected status=%s symbol=%s",
                        resp.status_code,
                        symbol,
                    )
                    return OrderResult(
                        ok=False,
                        dry_run=False,
                        order_id=None,
                        status="rejected",
                        detail=f"Alpaca HTTP {resp.status_code}",
                        raw={"body": resp.text[:500]},
                    )
                data = resp.json()
                return OrderResult(
                    ok=True,
                    dry_run=False,
                    order_id=str(data.get("id") or ""),
                    status=str(data.get("status") or "submitted"),
                    detail="Order submitted",
                    raw=data,
                )
        except Exception as exc:  # noqa: BLE001 — graceful failure
            logger.warning("Alpaca order failed symbol=%s err=%s", symbol, type(exc).__name__)
            return OrderResult(
                ok=False,
                dry_run=False,
                order_id=None,
                status="error",
                detail=f"Order request failed: {type(exc).__name__}",
            )
