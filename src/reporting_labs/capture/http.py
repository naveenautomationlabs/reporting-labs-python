"""Records every requests / httpx call made while a test runs, into the current attempt's API list.

Installed once per process by the pytest plugin and the Robot listener. Nothing is recorded outside a test.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from ..core import context

_installed: Dict[str, Any] = {}
_max_body = 64 * 1024


def _headers(h: Any) -> Dict[str, str]:
    try:
        return {str(k): str(v) for k, v in dict(h).items()}
    except Exception:
        return {}


def _body(raw: Any, content_type: str = "") -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > _max_body:
            return f"<{len(raw)} bytes, first {_max_body} shown>\n" + bytes(raw[:_max_body]).decode("utf-8", "replace")
        if "json" in content_type or raw[:1] in (b"{", b"["):
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                pass
        if any(t in content_type for t in ("image/", "video/", "audio/", "octet-stream", "pdf", "zip")):
            return f"<{len(raw)} bytes {content_type}>"
        return raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        if len(raw) > _max_body:
            return raw[:_max_body] + f"… ({len(raw)} chars)"
        if raw[:1] in "{[":
            try:
                return json.loads(raw)
            except Exception:
                pass
        return raw
    try:
        return json.loads(json.dumps(raw, default=str))
    except Exception:
        return str(raw)


def record(method: str, url: str, status: Optional[int], start: float, req_headers: Any, req_body: Any,
           res_headers: Any = None, res_body: Any = None, error: Optional[str] = None) -> None:
    a = context.current()
    if a is None:
        return
    rh = _headers(req_headers)
    call: Dict[str, Any] = {"method": str(method).upper(), "url": str(url), "duration": round((time.time() - start) * 1000, 1), "requestHeaders": rh}
    if status is not None:
        call["status"] = int(status)
    if req_body is not None:
        call["requestBody"] = _body(req_body, rh.get("Content-Type") or rh.get("content-type") or "")
    if res_headers is not None:
        sh = _headers(res_headers)
        call["responseHeaders"] = sh
        call["responseBody"] = _body(res_body, sh.get("Content-Type") or sh.get("content-type") or "")
    if error:
        call["responseBody"] = error
    a.api_call(call)


def install(max_body: int = 64 * 1024) -> None:
    global _max_body
    _max_body = max_body
    _install_requests()
    _install_httpx()


def uninstall() -> None:
    for name, (owner, attr, original) in list(_installed.items()):
        setattr(owner, attr, original)
        _installed.pop(name, None)


def _install_requests() -> None:
    if "requests" in _installed:
        return
    try:
        import requests
    except ImportError:
        return
    original = requests.Session.send

    def send(self, request, **kwargs):  # type: ignore[no-untyped-def]
        if context.current() is None:
            return original(self, request, **kwargs)
        start = time.time()
        try:
            resp = original(self, request, **kwargs)
        except Exception as e:
            record(request.method, request.url, None, start, request.headers, request.body, error=f"{type(e).__name__}: {e}")
            raise
        body: Any = None
        try:
            if not kwargs.get("stream"):
                body = resp.content
        except Exception:
            body = None
        record(request.method, request.url, resp.status_code, start, request.headers, request.body, resp.headers, body)
        return resp

    requests.Session.send = send  # type: ignore[assignment]
    _installed["requests"] = (requests.Session, "send", original)


def _install_httpx() -> None:
    if "httpx" in _installed:
        return
    try:
        import httpx
    except ImportError:
        return

    def req_body(request: Any) -> Any:
        try:
            return request.content or None
        except Exception:
            return None

    def res_body(resp: Any) -> Any:
        try:
            return resp.content if not resp.is_stream_consumed and hasattr(resp, "_content") else resp.content
        except Exception:
            return None

    original = httpx.Client.send

    def send(self, request, **kwargs):  # type: ignore[no-untyped-def]
        if context.current() is None:
            return original(self, request, **kwargs)
        start = time.time()
        try:
            resp = original(self, request, **kwargs)
        except Exception as e:
            record(request.method, str(request.url), None, start, request.headers, req_body(request), error=f"{type(e).__name__}: {e}")
            raise
        try:
            if not kwargs.get("stream"):
                resp.read()
        except Exception:
            pass
        record(request.method, str(request.url), resp.status_code, start, request.headers, req_body(request), resp.headers, res_body(resp) if not kwargs.get("stream") else None)
        return resp

    httpx.Client.send = send  # type: ignore[assignment]
    _installed["httpx"] = (httpx.Client, "send", original)

    aoriginal = httpx.AsyncClient.send

    async def asend(self, request, **kwargs):  # type: ignore[no-untyped-def]
        if context.current() is None:
            return await aoriginal(self, request, **kwargs)
        start = time.time()
        try:
            resp = await aoriginal(self, request, **kwargs)
        except Exception as e:
            record(request.method, str(request.url), None, start, request.headers, req_body(request), error=f"{type(e).__name__}: {e}")
            raise
        try:
            if not kwargs.get("stream"):
                await resp.aread()
        except Exception:
            pass
        record(request.method, str(request.url), resp.status_code, start, request.headers, req_body(request), resp.headers, res_body(resp) if not kwargs.get("stream") else None)
        return resp

    httpx.AsyncClient.send = asend  # type: ignore[assignment]
    _installed["httpx_async"] = (httpx.AsyncClient, "send", aoriginal)
