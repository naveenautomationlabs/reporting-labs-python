"""What one attempt of a test collects while it runs: steps, logs, data blocks, API calls, attachments, errors."""
from __future__ import annotations

import json
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def now_ms() -> float:
    return time.time() * 1000


@dataclass
class Step:
    title: str
    category: str = "test.step"
    start: float = field(default_factory=now_ms)
    duration: float = 0.0
    error: Optional[str] = None
    status: Optional[str] = None       # 'skipped' when the runner never executed it
    steps: List["Step"] = field(default_factory=list)
    _done: bool = False

    def finish(self, error: Optional[str] = None) -> None:
        if not self._done:
            self.duration = max(0.0, now_ms() - self.start)
            self._done = True
        if error:
            self.error = error


@dataclass
class Attachment:
    name: str
    content_type: str
    body: Optional[bytes] = None
    path: Optional[str] = None


@dataclass
class ErrorInfo:
    message: str
    stack: Optional[str] = None
    exc_type: Optional[str] = None
    location: Optional[Dict[str, Any]] = None   # {file, line, column}
    snippet: Optional[str] = None

    @staticmethod
    def from_exception(exc: BaseException, root: Optional[str] = None) -> "ErrorInfo":
        msg = str(exc) or type(exc).__name__
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        loc = None
        if exc.__traceback__ is not None:
            frames = traceback.extract_tb(exc.__traceback__)
            # the deepest frame inside the project, else the deepest frame at all
            chosen = None
            for f in reversed(frames):
                if root and f.filename.startswith(root) and "site-packages" not in f.filename:
                    chosen = f
                    break
            chosen = chosen or (frames[-1] if frames else None)
            if chosen is not None:
                loc = {"file": chosen.filename, "line": chosen.lineno or 0, "column": 0}
        return ErrorInfo(message=f"{type(exc).__name__}: {msg}" if not msg.startswith(type(exc).__name__) else msg, stack=tb, exc_type=type(exc).__name__, location=loc)


class Attempt:
    """One try of a test. Integrations and helpers write here through the current attempt (see context.py)."""

    def __init__(self, test_id: str, retry: int = 0, worker: int = 0) -> None:
        self.test_id = test_id
        self.retry = retry
        self.worker = worker
        self.start = now_ms()
        self.end: Optional[float] = None
        self.status = "passed"
        self.steps: List[Step] = []
        self._stack: List[Step] = []
        self.logs: List[Dict[str, Any]] = []
        self.data: List[Dict[str, Any]] = []        # raw data blocks: {name, data}
        self.api: List[Dict[str, Any]] = []
        self.attachments: List[Attachment] = []
        self.errors: List[ErrorInfo] = []
        self.meta: Dict[str, Any] = {}
        self.stdout: List[str] = []
        self.stderr: List[str] = []
        self.lock = threading.RLock()

    # -- steps -------------------------------------------------------------------------------------
    def begin_step(self, title: str, category: str = "test.step") -> Step:
        with self.lock:
            st = Step(title=title, category=category)
            (self._stack[-1].steps if self._stack else self.steps).append(st)
            self._stack.append(st)
            return st

    def end_step(self, step: Step, error: Optional[str] = None) -> None:
        with self.lock:
            step.finish(error)
            # pop this step and anything left open beneath it
            while self._stack and self._stack[-1] is not step:
                self._stack.pop().finish()
            if self._stack:
                self._stack.pop()

    def record_step(self, title: str, category: str, start: float, duration: float, error: Optional[str] = None) -> Step:
        """A step that already happened (tool integrations report actions after the fact)."""
        with self.lock:
            st = Step(title=title, category=category, start=start, duration=duration, error=error, _done=True)
            (self._stack[-1].steps if self._stack else self.steps).append(st)
            return st

    def current_step(self) -> Optional[Step]:
        return self._stack[-1] if self._stack else None

    def close_open_steps(self) -> None:
        with self.lock:
            while self._stack:
                self._stack.pop().finish()

    # -- content -----------------------------------------------------------------------------------
    def log(self, message: str) -> None:
        with self.lock:
            self.logs.append({"t": now_ms(), "msg": str(message)})

    def test_data(self, data: Any, name: str = "Test data") -> None:
        with self.lock:
            self.data.append({"name": str(name), "data": data})

    def api_call(self, call: Dict[str, Any]) -> None:
        with self.lock:
            self.api.append(call)

    def attach(self, name: str, body: Optional[bytes] = None, content_type: str = "application/octet-stream", path: Optional[str] = None) -> None:
        with self.lock:
            self.attachments.append(Attachment(name=str(name), content_type=content_type, body=body, path=path))

    def add_error(self, err: ErrorInfo) -> None:
        with self.lock:
            self.errors.append(err)

    def finish(self, status: str) -> None:
        self.close_open_steps()
        self.status = status
        self.end = now_ms()

    @property
    def duration(self) -> float:
        return max(0.0, (self.end or now_ms()) - self.start)


def json_safe(value: Any) -> Any:
    """Make a value JSON-serialisable for data blocks and API bodies."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        pass
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return f"<{len(value)} bytes>"
    if hasattr(value, "_asdict"):
        return json_safe(value._asdict())
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return json_safe({k: v for k, v in vars(value).items() if not k.startswith("_")})
    return str(value)
