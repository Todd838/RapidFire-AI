"""Logging filters that redact secrets from log records."""

from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key\s*[:=]\s*)\S+", re.I),
    re.compile(r"(secret[_-]?key\s*[:=]\s*)\S+", re.I),
    re.compile(r"(authorization\s*[:=]\s*)\S+", re.I),
    re.compile(r"(APCA-API-(?:KEY-ID|SECRET-KEY)\s*[:=]\s*)\S+", re.I),
    re.compile(r"(sk-ant-[A-Za-z0-9_\-]+)"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.I),
]


class SecretRedactionFilter(logging.Filter):
    """Replace likely secrets in log messages with [REDACTED]."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        redacted = msg
        for pattern in _SECRET_PATTERNS:
            if pattern.groups:
                redacted = pattern.sub(lambda m: f"{m.group(1)}[REDACTED]", redacted)
            else:
                redacted = pattern.sub("[REDACTED]", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def install_secret_redaction() -> None:
    """Attach redaction filter to the root logger and common app loggers."""
    filt = SecretRedactionFilter()
    root = logging.getLogger()
    root.addFilter(filt)
    for name in ("rapidfire", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addFilter(filt)
