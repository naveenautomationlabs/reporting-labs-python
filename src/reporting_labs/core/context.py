"""The attempt that is running right now, for helpers and tool integrations.

A contextvar carries it across async code; a thread-local and a process-wide fallback cover threads a test starts
and frameworks that run everything on one thread (Robot Framework).
"""
from __future__ import annotations

import contextvars
import threading
from typing import Optional

from .model import Attempt

_current: contextvars.ContextVar[Optional[Attempt]] = contextvars.ContextVar("reporting_labs_attempt", default=None)
_local = threading.local()
_fallback: Optional[Attempt] = None
_lock = threading.Lock()


def activate(attempt: Attempt) -> None:
    global _fallback
    _current.set(attempt)
    _local.attempt = attempt
    with _lock:
        _fallback = attempt


def deactivate(attempt: Optional[Attempt] = None) -> None:
    global _fallback
    _current.set(None)
    _local.attempt = None
    with _lock:
        if attempt is None or _fallback is attempt:
            _fallback = None


def current() -> Optional[Attempt]:
    a = _current.get()
    if a is not None:
        return a
    a = getattr(_local, "attempt", None)
    if a is not None:
        return a
    return _fallback
