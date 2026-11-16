"""LIVE mode cannot turn on without all three conditions."""

from __future__ import annotations

import pytest

from services import live_gate


@pytest.fixture(autouse=True)
def _reset_session():
    live_gate.reset_live_session_state()
    yield
    live_gate.reset_live_session_state()


def test_env_alone_does_not_permit_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()
    assert live_gate.is_live_trading_permitted(readiness_passed=False) is False
    get_settings.cache_clear()


def test_wrong_phrase_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()
    status = live_gate.attempt_enable_live("yes", readiness_passed=True)
    assert status.all_conditions_met is False
    assert status.live_session_active is False
    get_settings.cache_clear()


def test_readiness_required_even_with_phrase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()
    status = live_gate.attempt_enable_live(
        live_gate.LIVE_CONFIRMATION_PHRASE,
        readiness_passed=False,
    )
    assert status.all_conditions_met is False
    get_settings.cache_clear()


def test_all_three_conditions_activate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()
    status = live_gate.attempt_enable_live(
        live_gate.LIVE_CONFIRMATION_PHRASE,
        readiness_passed=True,
    )
    assert status.env_enabled is True
    assert status.readiness_passed is True
    assert status.ui_confirmed is True
    assert status.live_session_active is True
    assert status.all_conditions_met is True
    assert live_gate.is_live_trading_permitted(readiness_passed=True) is True
    get_settings.cache_clear()


def test_disable_live_is_instant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()
    live_gate.attempt_enable_live(
        live_gate.LIVE_CONFIRMATION_PHRASE,
        readiness_passed=True,
    )
    live_gate.reset_live_session_state()
    assert live_gate.is_live_trading_permitted(readiness_passed=True) is False
    get_settings.cache_clear()
