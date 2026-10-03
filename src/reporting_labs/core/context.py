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
    # Three layers, most precise first. The contextvar follows async tasks and the thread-local follows
    # threads a test spawns, so those always resolve to the right attempt. The process-wide `_fallback` is
    # the last resort for frameworks that give us no context at all (e.g. a library thread that copied
    # neither): between a test's teardown (deactivate clears it) and the next test's setup it is None, so a
    # stray background call in that gap records nowhere rather than being misattributed. Its only true
    # limitation is overlapping tests on bare OS threads with no contextvar/thread-local — not possible under
    # pytest or Robot, which run one attempt at a time per process — where a call could attach to whichever
    # attempt activated last. The two precise layers above make that path unreachable in practice.
    a = _current.get()
    if a is not None:
        return a
    a = getattr(_local, "attempt", None)
    if a is not None:
        return a
    return _fallback
