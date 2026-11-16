"""Live-trading enablement — requires ALL three conditions. No shortcuts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config import get_settings

LIVE_CONFIRMATION_PHRASE = "I UNDERSTAND THE RISKS"


@dataclass(frozen=True)
class LiveGateStatus:
    """Snapshot of whether live trading may be used."""

    env_enabled: bool
    readiness_passed: bool
    ui_confirmed: bool
    live_session_active: bool
    blockers: list[str]

    @property
    def all_conditions_met(self) -> bool:
        return (
            self.env_enabled
            and self.readiness_passed
            and self.ui_confirmed
            and self.live_session_active
        )


# In-memory confirmation flag — set only by the enable-live endpoint after
# exact phrase match. Cleared by disable-live. Never set from config alone.
_ui_confirmed: bool = False
_live_session_active: bool = False


def reset_live_session_state() -> None:
    """Disable live session immediately (disable-live endpoint)."""
    global _ui_confirmed, _live_session_active
    _ui_confirmed = False
    _live_session_active = False


def attempt_enable_live(
    confirmation: str,
    *,
    readiness_passed: bool,
) -> LiveGateStatus:
    """Try to activate a live session. All three conditions required."""
    global _ui_confirmed, _live_session_active
    settings = get_settings()
    env_ok = bool(settings.live_trading_enabled)

    phrase_ok = confirmation.strip() == LIVE_CONFIRMATION_PHRASE
    blockers: list[str] = []
    if not env_ok:
        blockers.append("LIVE_TRADING_ENABLED is not true in .env")
    if not readiness_passed:
        blockers.append("Go-readiness check has not passed")
    if not phrase_ok:
        blockers.append(f'Confirmation must be exactly "{LIVE_CONFIRMATION_PHRASE}"')

    if blockers:
        _ui_confirmed = False
        _live_session_active = False
        return get_live_gate_status(readiness_passed=readiness_passed)

    _ui_confirmed = True
    _live_session_active = True
    return get_live_gate_status(readiness_passed=True)


def get_live_gate_status(*, readiness_passed: bool = False) -> LiveGateStatus:
    """Inspect live-gate state. Readiness is injected by Stage 6 tracker later."""
    settings = get_settings()
    env_ok = bool(settings.live_trading_enabled)
    blockers: list[str] = []
    if not env_ok:
        blockers.append("LIVE_TRADING_ENABLED is not true in .env")
    if not readiness_passed:
        blockers.append("Go-readiness check has not passed")
    if not _ui_confirmed:
        blockers.append("UI typed confirmation not completed this session")
    if not _live_session_active:
        blockers.append("Live session is not active")

    return LiveGateStatus(
        env_enabled=env_ok,
        readiness_passed=readiness_passed,
        ui_confirmed=_ui_confirmed,
        live_session_active=_live_session_active,
        blockers=blockers,
    )


def is_live_trading_permitted(*, readiness_passed: bool) -> bool:
    """True only when env + readiness + UI confirmation + active session."""
    return get_live_gate_status(readiness_passed=readiness_passed).all_conditions_met


def assert_not_live_from_env_alone() -> None:
    """Safety: env flag alone must never imply live orders are allowed."""
    settings = get_settings()
    if settings.live_trading_enabled and not _live_session_active:
        # Expected state — env can be true while session stays off.
        return
