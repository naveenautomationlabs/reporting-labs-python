"""Zero-code Playwright support: every action on a Page, Frame, Locator or ElementHandle is a step, every
expect() a step, every APIRequestContext call lands in the API tab, a screenshot of each open page is attached
when a test fails, and pytest-playwright's trace, video and screenshot files are attached after the test.

Works with the sync and the async API. Installed by the pytest plugin when `playwright` is importable; the Robot
listener does the same for the Browser library's pages where it can.
"""
from __future__ import annotations

import contextvars
import functools
import inspect
import os
import re
import time
import weakref
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .core import context
from .core.model import Attempt, now_ms

ACTIONS = {
    "click", "dblclick", "fill", "type", "press", "press_sequentially", "check", "uncheck", "set_checked", "select_option", "set_input_files",
    "hover", "focus", "blur", "clear", "tap", "drag_to", "drag_and_drop", "dispatch_event", "scroll_into_view_if_needed", "select_text",
    "goto", "go_back", "go_forward", "reload", "set_content", "wait_for_selector", "wait_for_load_state", "wait_for_url", "wait_for_timeout",
    "wait_for_function", "wait_for", "wait_for_element_state", "screenshot", "pdf", "evaluate", "evaluate_handle", "evaluate_all",
    "eval_on_selector", "eval_on_selector_all", "set_viewport_size", "emulate_media", "bring_to_front", "close", "set_extra_http_headers",
    "add_init_script", "route", "unroute", "highlight",
}
READS = {"inner_text", "text_content", "inner_html", "input_value", "get_attribute", "is_visible", "is_hidden", "is_enabled", "is_disabled",
         "is_checked", "is_editable", "count", "all_inner_texts", "all_text_contents", "bounding_box", "title", "content", "aria_snapshot",
         "query_selector", "query_selector_all", "element_handle", "element_handles", "all"}
INPUT_ACTIONS = {"press", "type", "down", "up", "insert_text", "click", "dblclick", "move", "wheel"}
API_METHODS = {"get", "post", "put", "patch", "delete", "head", "fetch"}
MAX_ARG = 80
_SECRET_FIELD = ("password", "passwd", "pwd", "pass", "pw", "secret", "token", "pin", "otp", "cvv")

_installed = False
_depth: contextvars.ContextVar[int] = contextvars.ContextVar("rl_pw_depth", default=0)
_browsers_seen: List[str] = []
_patched: List[tuple] = []  # (cls, method_name, original) so install() can be undone


def _short(v: Any) -> str:
    if isinstance(v, str):
        s = v
    elif isinstance(v, (int, float, bool)) or v is None:
        s = str(v)
    elif isinstance(v, (list, tuple)):
        s = "[" + ", ".join(_short(x) for x in v[:5]) + ("…" if len(v) > 5 else "") + "]"
    elif isinstance(v, dict):
        s = "{" + ", ".join(f"{k}: {_short(x)}" for k, x in list(v.items())[:5]) + "}"
    elif callable(v):
        s = getattr(v, "__name__", "function")
    else:
        s = _target(v) or type(v).__name__
    return s if len(s) <= MAX_ARG else s[: MAX_ARG - 1] + "…"


def _selector(obj: Any) -> Optional[str]:
    impl = getattr(obj, "_impl_obj", obj)
    sel = getattr(impl, "_selector", None)
    return str(sel) if sel else None


def _target(obj: Any) -> str:
    name = type(obj).__name__
    if name == "Locator":
        sel = _selector(obj)
        return f'locator("{sel}")' if sel else "locator"
    if name == "FrameLocator":
        sel = _selector(obj) or getattr(getattr(obj, "_impl_obj", obj), "_frame_selector", None)
        return f'frame_locator("{sel}")' if sel else "frame_locator"
    if name == "Page":
        return "page"
    if name == "Frame":
        try:
            return "frame" + (f'("{obj.name}")' if obj.name else "")
        except Exception:
            return "frame"
    if name == "ElementHandle":
        try:
            return f"<{obj.evaluate('e => e.tagName.toLowerCase()')}>"
        except Exception:
            return "element"
    if name in ("Mouse", "Keyboard", "Touchscreen"):
        return name.lower()
    return name.lower()


def _title(target: Any, method: str, args: tuple, kwargs: dict) -> str:
    tname = _target(target)
    kind = type(target).__name__
    shown = [a for a in args if a is not None]
    extra = {k: v for k, v in kwargs.items() if k in ("url", "value", "key", "text", "state", "files", "timeout", "options", "label", "index") and v is not None}
    parts = [f"{tname}.{method}"] if kind not in ("Page",) or method in READS else [f"page.{method}"]
    if kind == "Page" and method not in ("goto", "go_back", "go_forward", "reload", "set_content", "screenshot", "pdf", "close", "bring_to_front", "wait_for_timeout", "wait_for_load_state", "wait_for_url", "set_viewport_size", "emulate_media", "title", "content", "wait_for_function", "evaluate", "evaluate_handle", "add_init_script", "route", "unroute", "set_extra_http_headers"):
        # page.click("#x", ...): the selector is the first argument
        parts = [f"page.{method}"]
    shown_s = [_short(a) for a in shown[:3]]
    # a value typed into a password-like field never shows in a step title
    if method in ("fill", "type", "press_sequentially", "insert_text"):
        where = (tname + " " + (str(shown[0]) if kind == "Page" and shown else "")).lower()
        if any(w in where for w in _SECRET_FIELD):
            shown_s = [shown_s[0], '"****"'] if kind == "Page" and len(shown_s) > 1 else ['"****"']
    text = " ".join(parts + shown_s + [f"{k}={_short(v)}" for k, v in extra.items() if k not in ("timeout",)])
    return text


def _page_of(target: Any) -> Any:
    try:
        name = type(target).__name__
        if name == "Page":
            return target
        if name in ("Locator", "Frame"):
            return target.page
        if name in ("Mouse", "Keyboard", "Touchscreen"):
            return getattr(target, "_rl_page", None)
    except Exception:
        return None
    return None


_ABORTED = re.compile(r"ERR_ABORTED|NS_BINDING_ABORTED|cancelled", re.I)
_FAVICON = re.compile(r"/favicon\.ico(\?.*)?$")
# when each test's last page closed (ms since epoch): a video ends then, so its first frame is that minus its length
_closed_at: Dict[str, float] = {}


def _watch(attempt: Attempt, page: Any) -> None:
    """What the browser reports while the test runs, for the report's "What the browser saw": uncaught JavaScript
    errors, console.error messages, and requests that got no response or a 4xx/5xx."""
    if getattr(page, "_rl_watched", False):
        return
    try:
        page._rl_watched = True
    except Exception:
        return
    first = weakref.ref(attempt)

    def target() -> Optional[Attempt]:
        # the test running now (a page shared by several tests), else the one that first used the page
        return context.current() or first()

    def safe(fn: Callable) -> Callable:
        def run(*a: Any) -> None:
            try:
                fn(*a)
            except Exception:
                pass  # a listener must never break the test
        return run

    def page_url() -> Optional[str]:
        try:
            return page.url
        except Exception:
            return None

    def on_error(err: Any) -> None:
        a = target()
        if a is None:
            return
        msg = getattr(err, "message", None) or str(err)
        name = getattr(err, "name", None)
        stack = getattr(err, "stack", None)
        text = f"{name}: {msg}" if name and not str(msg).startswith(str(name)) else str(msg)
        a.browser_event("error", text.splitlines()[0] if text else "", page_url(), stack=stack if stack and stack != text else None)

    def on_console(m: Any) -> None:
        if m.type != "error":
            return
        text = m.text
        # the browser's own note for a request that got 4xx/5xx: the request is already listed
        if text.startswith("Failed to load resource"):
            return
        a = target()
        if a is None:
            return
        loc = None
        try:
            l = m.location
            if l and l.get("url"):
                loc = f"{l['url']}:{l.get('lineNumber', 0)}"
        except Exception:
            pass
        a.browser_event("console", text, loc)

    def on_response(r: Any) -> None:
        if r.status < 400 or _FAVICON.search(r.url):
            return
        a = target()
        if a is not None:
            a.browser_event("request", r.status_text, r.url, r.request.method, r.status)

    def on_failed(r: Any) -> None:
        why = r.failure or ""
        if _ABORTED.search(why):
            return  # navigating away
        a = target()
        if a is not None:
            a.browser_event("request", why or "Request failed", r.url, r.method)

    def on_close(*_: Any) -> None:
        a = target()
        if a is not None:
            _closed_at[a.test_id] = now_ms()

    for event, fn in (("pageerror", on_error), ("console", on_console), ("response", on_response), ("requestfailed", on_failed), ("close", on_close)):
        try:
            page.on(event, safe(fn))
        except Exception:
            pass


def webm_duration_ms(path: str) -> float:
    """The length of a .webm recording in ms, from its header (Segment Info: TimecodeScale and Duration). 0 when unknown."""
    import struct
    try:
        with open(path, "rb") as f:
            b = f.read(4096)
    except OSError:
        return 0.0
    scale_ns = 1_000_000.0  # TimecodeScale, default 1 ms
    i = b.find(b"\x2a\xd7\xb1")
    if i >= 0 and i + 4 <= len(b):
        n = b[i + 3] & 0x7F
        if 0 < n <= 8 and i + 4 + n <= len(b):
            scale_ns = float(int.from_bytes(b[i + 4:i + 4 + n], "big"))
    i = b.find(b"\x44\x89")
    while i >= 0:
        n = b[i + 2] & 0x7F if i + 2 < len(b) else 0
        if n in (4, 8) and i + 3 + n <= len(b):
            ticks = struct.unpack(">f" if n == 4 else ">d", b[i + 3:i + 3 + n])[0]
            return max(0.0, ticks * scale_ns / 1_000_000)
        i = b.find(b"\x44\x89", i + 1)
    return 0.0


def _remember_page(attempt: Attempt, page: Any) -> None:
    if page is None:
        return
    if not hasattr(page, "_impl_obj"):
        # expect() holds Playwright's internal objects: use the page the test sees, so it is remembered (and watched) once
        page = getattr(page, "_pw_api_instance_", None) or page
    pages: List[Any] = attempt.__dict__.setdefault("_rl_pages", [])
    if not any(p() is page for p in pages):
        pages.append(weakref.ref(page))
        _watch(attempt, page)
    try:
        b = page.context.browser
        name = f"{b.browser_type.name} {b.version}" if b else "browser"
        if name not in _browsers_seen:
            _browsers_seen.append(name)
    except Exception:
        pass


def _wrap(cls: type, method: str, category: str) -> None:
    original = getattr(cls, method, None)
    if original is None or getattr(original, "_rl_wrapped", False):
        return
    is_async = inspect.iscoroutinefunction(original)

    def begin(self: Any, args: tuple, kwargs: dict):
        attempt = context.current()
        if attempt is None or _depth.get() > 0:
            return None, None
        _remember_page(attempt, _page_of(self))
        token = _depth.set(_depth.get() + 1)
        return attempt, (token, now_ms(), _title(self, method, args, kwargs))

    def end(attempt: Any, state: Any, error: Optional[BaseException]) -> None:
        token, start, title = state
        _depth.reset(token)
        attempt.record_step(title, category, start, now_ms() - start, f"{type(error).__name__}: {error}" if error else None)

    if is_async:
        @functools.wraps(original)
        async def aw(self: Any, *args: Any, **kwargs: Any) -> Any:
            attempt, state = begin(self, args, kwargs)
            if attempt is None:
                return await original(self, *args, **kwargs)
            try:
                result = await original(self, *args, **kwargs)
            except BaseException as e:
                end(attempt, state, e)
                raise
            end(attempt, state, None)
            return result
        aw._rl_wrapped = True  # type: ignore[attr-defined]
        setattr(cls, method, aw)
        _patched.append((cls, method, original))
    else:
        @functools.wraps(original)
        def w(self: Any, *args: Any, **kwargs: Any) -> Any:
            attempt, state = begin(self, args, kwargs)
            if attempt is None:
                return original(self, *args, **kwargs)
            try:
                result = original(self, *args, **kwargs)
            except BaseException as e:
                end(attempt, state, e)
                raise
            end(attempt, state, None)
            return result
        w._rl_wrapped = True  # type: ignore[attr-defined]
        setattr(cls, method, w)
        _patched.append((cls, method, original))


def _wrap_assertions(cls: type) -> None:
    for name in dir(cls):
        if not (name.startswith("to_") or name.startswith("not_to_")):
            continue
        original = getattr(cls, name)
        if not callable(original) or getattr(original, "_rl_wrapped", False):
            continue
        is_async = inspect.iscoroutinefunction(original)

        def make(name: str, original: Callable):
            def actual(self: Any) -> Any:
                for obj in (self, getattr(self, "_impl_obj", None)):
                    for attr in ("_actual_page", "_actual_locator", "_actual"):
                        v = getattr(obj, attr, None)
                        if v is not None:
                            return v
                return None

            def title(self: Any, args: tuple, kwargs: dict) -> str:
                target = actual(self)
                shown = [_short(a) for a in args[:2] if a is not None]
                return f"expect({_target(target) if target is not None else '…'}).{name}(" + ", ".join(shown) + ")"

            def begin(self: Any, args: tuple, kwargs: dict):
                attempt = context.current()
                if attempt is None:
                    return None, None
                _remember_page(attempt, _page_of(actual(self)))
                return attempt, (now_ms(), title(self, args, kwargs))

            def end(attempt: Any, state: Any, error: Optional[BaseException]) -> None:
                start, t = state
                attempt.record_step(t, "expect", start, now_ms() - start, f"{type(error).__name__}: {error}" if error else None)

            if is_async:
                @functools.wraps(original)
                async def aw(self: Any, *args: Any, **kwargs: Any) -> Any:
                    attempt, state = begin(self, args, kwargs)
                    if attempt is None:
                        return await original(self, *args, **kwargs)
                    try:
                        r = await original(self, *args, **kwargs)
                    except BaseException as e:
                        end(attempt, state, e)
                        raise
                    end(attempt, state, None)
                    return r
                aw._rl_wrapped = True  # type: ignore[attr-defined]
                return aw

            @functools.wraps(original)
            def w(self: Any, *args: Any, **kwargs: Any) -> Any:
                attempt, state = begin(self, args, kwargs)
                if attempt is None:
                    return original(self, *args, **kwargs)
                try:
                    r = original(self, *args, **kwargs)
                except BaseException as e:
                    end(attempt, state, e)
                    raise
                end(attempt, state, None)
                return r
            w._rl_wrapped = True  # type: ignore[attr-defined]
            return w

        setattr(cls, name, make(name, original))
        _patched.append((cls, name, original))


def _wrap_api(cls: type) -> None:
    from .capture.http import record

    for method in API_METHODS:
        original = getattr(cls, method, None)
        if original is None or getattr(original, "_rl_wrapped", False):
            continue
        is_async = inspect.iscoroutinefunction(original)

        def make(method: str, original: Callable):
            def http_method(args: tuple, kwargs: dict) -> str:
                return str(kwargs.get("method") or "GET").upper() if method == "fetch" else method.upper()

            def req_body(kwargs: dict) -> Any:
                for k in ("data", "form", "multipart"):
                    if kwargs.get(k) is not None:
                        return kwargs[k]
                return None

            def url_of(args: tuple, resp: Any) -> str:
                try:
                    return resp.url
                except Exception:
                    return str(args[0]) if args else "?"

            if is_async:
                @functools.wraps(original)
                async def aw(self: Any, *args: Any, **kwargs: Any) -> Any:
                    if context.current() is None:
                        return await original(self, *args, **kwargs)
                    start = time.time()
                    try:
                        resp = await original(self, *args, **kwargs)
                    except BaseException as e:
                        record(http_method(args, kwargs), str(args[0]) if args else "?", None, start, kwargs.get("headers"), req_body(kwargs), error=f"{type(e).__name__}: {e}")
                        raise
                    body = None
                    try:
                        body = await resp.text()
                    except Exception:
                        pass
                    record(http_method(args, kwargs), url_of(args, resp), resp.status, start, kwargs.get("headers"), req_body(kwargs), resp.headers, body)
                    return resp
                aw._rl_wrapped = True  # type: ignore[attr-defined]
                return aw

            @functools.wraps(original)
            def w(self: Any, *args: Any, **kwargs: Any) -> Any:
                if context.current() is None:
                    return original(self, *args, **kwargs)
                start = time.time()
                try:
                    resp = original(self, *args, **kwargs)
                except BaseException as e:
                    record(http_method(args, kwargs), str(args[0]) if args else "?", None, start, kwargs.get("headers"), req_body(kwargs), error=f"{type(e).__name__}: {e}")
                    raise
                body = None
                try:
                    body = resp.text()
                except Exception:
                    pass
                record(http_method(args, kwargs), url_of(args, resp), resp.status, start, kwargs.get("headers"), req_body(kwargs), resp.headers, body)
                return resp
            w._rl_wrapped = True  # type: ignore[attr-defined]
            return w

        setattr(cls, method, make(method, original))
        _patched.append((cls, method, original))


def _install_module(mod: Any) -> None:
    for cls_name in ("Page", "Frame", "Locator", "ElementHandle"):
        cls = getattr(mod, cls_name, None)
        if cls is None:
            continue
        for method in ACTIONS | READS:
            if hasattr(cls, method):
                _wrap(cls, method, "pw:api")
    for cls_name in ("Mouse", "Keyboard", "Touchscreen"):
        cls = getattr(mod, cls_name, None)
        if cls is None:
            continue
        for method in INPUT_ACTIONS | {"tap"}:
            if hasattr(cls, method):
                _wrap(cls, method, "pw:api")
    for cls_name in ("LocatorAssertions", "PageAssertions", "APIResponseAssertions"):
        cls = getattr(mod, cls_name, None)
        if cls is not None:
            _wrap_assertions(cls)
    cls = getattr(mod, "APIRequestContext", None)
    if cls is not None:
        _wrap_api(cls)


def install(opts: Any = None) -> bool:
    """Patch the Playwright classes. Returns False when playwright is not installed."""
    global _installed
    if _installed:
        return True
    try:
        import playwright.sync_api as sync_mod
        import playwright.async_api as async_mod
    except ImportError:
        return False
    _install_module(sync_mod)
    _install_module(async_mod)
    _installed = True
    return True


def uninstall() -> None:
    """Restore the original Playwright methods. Used at the end of a run so an in-process import of the
    library (e.g. a test runner that keeps the interpreter alive) is left unpatched."""
    global _installed
    for cls, method, original in reversed(_patched):
        try:
            setattr(cls, method, original)
        except Exception:
            pass
    _patched.clear()
    _browsers_seen.clear()
    _installed = False


def live_pages(attempt: Attempt) -> List[Any]:
    out = []
    for ref in attempt.__dict__.get("_rl_pages", []):
        p = ref()
        try:
            if p is not None and not p.is_closed():
                out.append(p)
        except Exception:
            pass
    return out


def on_failure(item: Any, attempt: Attempt) -> None:
    """A screenshot of every open page (sync API; async pages need a running loop, so they are skipped)."""
    for i, page in enumerate(live_pages(attempt)):
        try:
            shot = page.screenshot
            if inspect.iscoroutinefunction(shot):
                continue
            token = _depth.set(_depth.get() + 1)
            try:
                png = shot(type="png")
            finally:
                _depth.reset(token)
            name = "screenshot" if i == 0 else f"screenshot {i + 1}"
            attempt.attach(name, png, "image/png")
            try:
                attempt.log(f"{name}: {page.url}")
            except Exception:
                pass
        except Exception:
            pass


def after_teardown(item: Any, attempt: Attempt) -> None:
    """pytest-playwright writes trace.zip, video.webm and test-failed-N.png under test-results/<test>/ in its
    fixture teardown; attach whatever it left for this test."""
    try:
        from slugify import slugify  # pytest-playwright's dependency
    except ImportError:
        return
    try:
        out = item.config.getoption("--output")
    except Exception:
        return
    if not out:
        return
    base = Path(out) if Path(out).is_absolute() else Path(str(item.config.rootpath)) / out
    name = slugify(item.nodeid)
    if len(name) > 256:
        name = name[:100] + "-" + str(abs(hash(name)) % 10**8)
    folder = base / name
    if not folder.is_dir():
        # pytest-playwright's own truncation: keep the prefix and a hash of the full name
        for cand in base.glob(name[:60] + "*"):
            if cand.is_dir():
                folder = cand
                break
        else:
            return
    have = {a.name for a in attempt.attachments}
    closed = _closed_at.pop(attempt.test_id, None)
    for f in sorted(folder.iterdir()):
        if not f.is_file():
            continue
        if f.suffix == ".zip" and "trace" in f.name:
            attempt.attach("trace", path=str(f), content_type="application/zip")
        elif f.suffix == ".webm":
            length = webm_duration_ms(str(f))
            # the first frame, so the report can play the video in step with the steps
            first = closed - length if closed and length > 0 else None
            attempt.attach("video", path=str(f), content_type="video/webm", video_start=first)
        elif f.suffix == ".png" and "screenshot" not in have:
            attempt.attach(f.stem, path=str(f), content_type="image/png")


def env_rows() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    try:
        from importlib.metadata import version
        rows.append({"k": "Playwright", "v": version("playwright")})
    except Exception:
        pass
    if _browsers_seen:
        rows.append({"k": "Browsers", "v": ", ".join(_browsers_seen)})
    return rows
