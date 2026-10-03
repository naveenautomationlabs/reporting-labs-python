"""reportingLabs for Python: one HTML report for pytest, Playwright, Selenium and Robot Framework.

Helpers to call from a test:

    from reporting_labs import meta, log, test_data, step, api, attach

    meta(priority="P1", owner="asha", feature="checkout")
    log("cart total before coupons: 99.00")
    test_data({"username": "demo", "password": "x"}, "Login")
    with step("Apply coupon"):
        ...
    api(method="GET", url="/v1/orders", status=200, duration=120, response_body=body)
    attach("screenshot", png_bytes, "image/png")

Secrets (password=..., Bearer ..., tokens) are masked in the report.
"""
from __future__ import annotations

import functools
import inspect
import json
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional, Union

from ._version import __version__
from .core import context
from .core.model import ErrorInfo, now_ms

__all__ = ["meta", "log", "test_data", "step", "api", "attach", "__version__"]


def meta(**values: Any) -> None:
    """Attach report metadata to the current test: priority, severity, owner, feature, epic, story, issue... or any key.
    A value can be a list (one chip per value) or a dict (the fields of a multi-parameter link, see `links`)."""
    a = context.current()
    if a is None:
        return
    for k, v in values.items():
        if v is not None:
            a.meta[str(k).lower()] = v


def log(message: Any, *rest: Any) -> None:
    """Add a timestamped log line to the current test. Lines containing "error"/"fail" show red, "warn" amber."""
    a = context.current()
    if a is None:
        return
    parts = [str(message)] + [r if isinstance(r, str) else json.dumps(r, default=str) for r in rest]
    a.log(" ".join(parts))


def test_data(data: Any, name: str = "Test data") -> None:
    """Attach the data this test uses: a dict (key/value block), a list of dicts (table) or a CSV string (table).
    Sensitive keys are masked."""
    a = context.current()
    if a is not None:
        a.test_data(data, name)


def api(method: str, url: str, status: Optional[int] = None, duration: Optional[float] = None, name: Optional[str] = None,
        request_headers: Optional[Dict[str, str]] = None, request_body: Any = None,
        response_headers: Optional[Dict[str, str]] = None, response_body: Any = None) -> None:
    """Record an API call by hand. requests and httpx calls are recorded automatically."""
    a = context.current()
    if a is None:
        return
    call: Dict[str, Any] = {"method": str(method).upper(), "url": str(url)}
    if status is not None:
        call["status"] = int(status)
    if duration is not None:
        call["duration"] = float(duration)
    if name:
        call["name"] = name
    if request_headers:
        call["requestHeaders"] = dict(request_headers)
    if request_body is not None:
        call["requestBody"] = request_body
    if response_headers:
        call["responseHeaders"] = dict(response_headers)
    if response_body is not None:
        call["responseBody"] = response_body
    a.api_call(call)


def attach(name: str, body: Union[bytes, str, None] = None, content_type: Optional[str] = None, path: Optional[str] = None) -> None:
    """Attach a file or bytes to the current test: a screenshot, a downloaded PDF, a log. Images are shown inline."""
    a = context.current()
    if a is None:
        return
    if isinstance(body, str):
        body = body.encode("utf-8")
        content_type = content_type or "text/plain"
    if content_type is None:
        ext = (path or name).lower().rsplit(".", 1)[-1] if "." in (path or name) else ""
        content_type = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "webm": "video/webm",
                        "mp4": "video/mp4", "txt": "text/plain", "log": "text/plain", "json": "application/json", "html": "text/html", "csv": "text/csv",
                        "zip": "application/zip", "pdf": "application/pdf"}.get(ext, "application/octet-stream")
    a.attach(name, body, content_type, path)


test_data.__test__ = False   # pytest must not collect the helper when a test module imports it


class _StepContext:
    """`with step("title"):` and `@step("title")` on a function (sync or async)."""

    def __init__(self, title: str, category: str = "test.step") -> None:
        self.title, self.category = title, category
        self._st = None
        self._attempt = None

    def __enter__(self) -> "_StepContext":
        self._attempt = context.current()
        if self._attempt is not None:
            self._st = self._attempt.begin_step(self.title, self.category)
        return self

    def __exit__(self, et, ev, tb) -> bool:
        if self._attempt is not None and self._st is not None:
            self._attempt.end_step(self._st, f"{et.__name__}: {ev}" if et else None)
        return False

    async def __aenter__(self) -> "_StepContext":
        return self.__enter__()

    async def __aexit__(self, et, ev, tb) -> bool:
        return self.__exit__(et, ev, tb)

    def __call__(self, fn: Callable) -> Callable:
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def aw(*args: Any, **kw: Any) -> Any:
                async with _StepContext(self.title or fn.__name__, self.category):
                    return await fn(*args, **kw)
            return aw

        @functools.wraps(fn)
        def w(*args: Any, **kw: Any) -> Any:
            with _StepContext(self.title or fn.__name__, self.category):
                return fn(*args, **kw)
        return w


def step(title: Union[str, Callable, None] = None, category: str = "test.step") -> Any:
    """A named step in the report. Use as a context manager or a decorator; steps nest.

        with step("Log in as admin"):
            page.fill("#user", "admin")

        @step("Open the cart")
        def open_cart(page): ...
    """
    if callable(title):
        return _StepContext(title.__name__, category)(title)
    return _StepContext(str(title or "step"), category)
