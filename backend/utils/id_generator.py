"""Application-side BIGINT ID generator.

The migrated ``cynexus_appl_market`` PostgreSQL tables intentionally have
``BIGINT`` primary keys without database defaults, so insert paths must assign
IDs before flushing.  This module provides a compact Snowflake-style generator
that fits signed PostgreSQL BIGINT values.
"""
from __future__ import annotations

import os
import threading
import time

# 2024-01-01T00:00:00.000Z in milliseconds.
_EPOCH_MS = 1704067200000
_WORKER_ID_BITS = 10
_SEQUENCE_BITS = 12
_MAX_WORKER_ID = (1 << _WORKER_ID_BITS) - 1
_MAX_SEQUENCE = (1 << _SEQUENCE_BITS) - 1

_LOCK = threading.Lock()
_LAST_MS = -1
_SEQUENCE = 0


def _worker_id() -> int:
    raw = os.getenv("APP_ID_WORKER_ID", "1").strip() or "1"
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"APP_ID_WORKER_ID must be an integer, got {raw!r}") from exc
    if value < 0 or value > _MAX_WORKER_ID:
        raise RuntimeError(f"APP_ID_WORKER_ID must be between 0 and {_MAX_WORKER_ID}, got {value}")
    return value


def _now_ms() -> int:
    return int(time.time() * 1000)


def next_id() -> int:
    """Return a positive signed-BIGINT-compatible unique ID."""
    global _LAST_MS, _SEQUENCE
    worker = _worker_id()
    with _LOCK:
        now_ms = _now_ms()
        if now_ms < _LAST_MS:
            # Clock moved backwards.  Keep monotonicity inside this process.
            now_ms = _LAST_MS
        if now_ms == _LAST_MS:
            _SEQUENCE = (_SEQUENCE + 1) & _MAX_SEQUENCE
            if _SEQUENCE == 0:
                while now_ms <= _LAST_MS:
                    now_ms = _now_ms()
        else:
            _SEQUENCE = 0
        _LAST_MS = now_ms
        elapsed = now_ms - _EPOCH_MS
        return (elapsed << (_WORKER_ID_BITS + _SEQUENCE_BITS)) | (worker << _SEQUENCE_BITS) | _SEQUENCE


__all__ = ["next_id"]
