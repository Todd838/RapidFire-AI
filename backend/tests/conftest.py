"""Pytest fixtures shared across Stage 2+ tests."""

from __future__ import annotations

import pytest

from config import get_settings
from services import live_gate


@pytest.fixture(autouse=True)
def _reset_settings_and_live_gate():
    """Avoid cross-test pollution from cached settings / live session."""
    get_settings.cache_clear()
    live_gate.reset_live_session_state()
    yield
    live_gate.reset_live_session_state()
    get_settings.cache_clear()
