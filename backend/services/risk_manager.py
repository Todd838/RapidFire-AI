"""Risk management — every order must pass check_trade_allowed(). No bypass flags."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

AssetType = Literal["equity", "crypto"]

# ---------------------------------------------------------------------------
# Phase-1 LIVE limits (Stage 7). Kept here so live checks cannot be skipped
# by callers that forget a separate module. Comment block required by spec:
#   - $500 max per position
#   - 3 open positions
#   - $150 daily loss hard stop (enforced when is_live=True)
#   - whitelist only
#   - no options / no micro-caps
#   - 60-minute cooldown after a loss (tracked by AutoTrader, not sizing)
# ---------------------------------------------------------------------------
LIVE_MAX_POSITION_USD = 500.0
LIVE_MAX_OPEN_POSITIONS = 3
LIVE_DAILY_LOSS_HARD_STOP_USD = 150.0
LIVE_WHITELIST = frozenset({"SPY", "QQQ", "NVDA", "AAPL", "BTC-USD", "ETH-USD"})


@dataclass(frozen=True)
class RiskCheckResult:
    """Result of a pre-trade risk check."""

    allowed: bool
    reason: str
    suggested_size: float


def size_position(
    account_value: float,
    entry: float,
    stop: float,
    risk_pct: float = 0.02,
    asset_type: AssetType | str = "equity",
) -> float:
    """Position size = (account * risk_pct) / (entry - stop).

    Equities are floored to whole shares. Crypto may be fractional.
    Returns 0.0 when inputs are invalid or size rounds to zero.
    """
    if account_value <= 0 or entry <= 0 or risk_pct <= 0:
        return 0.0
    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return 0.0

    raw = (account_value * risk_pct) / risk_per_share
    if asset_type == "crypto":
        # Keep a sensible precision for crypto fractions.
        return math.floor(raw * 1_000_000) / 1_000_000

    whole = float(math.floor(raw))
    return whole if whole > 0 else 0.0


class RiskManager:
    """Hard risk gates for paper and live trading.

    There is intentionally no bypass / skip_risk / force parameter.
    """

    def __init__(
        self,
        max_risk_pct: float = 0.02,
        max_open_positions: int = 10,
        daily_loss_limit_pct: float = 0.05,
    ) -> None:
        self.max_risk_pct = max_risk_pct
        self.max_open_positions = max_open_positions
        self.daily_loss_limit_pct = daily_loss_limit_pct

    def check_trade_allowed(
        self,
        *,
        account_value: float,
        open_positions: int,
        daily_pnl: float,
        entry: float,
        stop: float,
        asset_type: AssetType | str = "equity",
        ticker: str = "",
        is_live: bool = False,
    ) -> RiskCheckResult:
        """Return whether a trade may be sent, with suggested size and reason."""
        if account_value <= 0:
            return RiskCheckResult(False, "Account value must be positive", 0.0)
        if entry <= 0:
            return RiskCheckResult(False, "Entry price must be positive", 0.0)
        if stop >= entry:
            return RiskCheckResult(False, "Stop must be below entry for long trades", 0.0)

        # Daily-loss kill switch (paper/default: % of account; live also uses $ hard stop).
        loss_limit = -(account_value * self.daily_loss_limit_pct)
        if daily_pnl <= loss_limit:
            return RiskCheckResult(
                False,
                f"Daily-loss kill switch: PnL {daily_pnl:.2f} hit {self.daily_loss_limit_pct:.0%} limit",
                0.0,
            )

        max_positions = self.max_open_positions
        if is_live:
            max_positions = min(max_positions, LIVE_MAX_OPEN_POSITIONS)
            if daily_pnl <= -LIVE_DAILY_LOSS_HARD_STOP_USD:
                return RiskCheckResult(
                    False,
                    f"Live daily-loss hard stop: PnL {daily_pnl:.2f} <= -${LIVE_DAILY_LOSS_HARD_STOP_USD:.0f}",
                    0.0,
                )
            sym = ticker.upper().strip()
            if sym not in LIVE_WHITELIST:
                return RiskCheckResult(
                    False,
                    f"Live whitelist rejection: {sym or '(empty)'} not in {sorted(LIVE_WHITELIST)}",
                    0.0,
                )

        if open_positions >= max_positions:
            return RiskCheckResult(
                False,
                f"Max open positions reached ({open_positions}/{max_positions})",
                0.0,
            )

        size = size_position(
            account_value=account_value,
            entry=entry,
            stop=stop,
            risk_pct=self.max_risk_pct,
            asset_type=asset_type,
        )

        if is_live and size > 0:
            notional = size * entry
            if notional > LIVE_MAX_POSITION_USD:
                # Cap size to max notional rather than silently oversized.
                capped = math.floor(LIVE_MAX_POSITION_USD / entry) if asset_type != "crypto" else (
                    math.floor((LIVE_MAX_POSITION_USD / entry) * 1_000_000) / 1_000_000
                )
                if capped <= 0:
                    return RiskCheckResult(
                        False,
                        f"Live max position ${LIVE_MAX_POSITION_USD:.0f}: size rounds to zero at entry {entry}",
                        0.0,
                    )
                size = float(capped)

        if size <= 0:
            return RiskCheckResult(
                False,
                "Suggested size is zero after risk sizing (stop too wide or account too small)",
                0.0,
            )

        return RiskCheckResult(True, "Allowed: risk checks passed", size)
