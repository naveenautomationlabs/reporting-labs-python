"""Turns an Attempt into a JSON-safe payload and back, so pytest-xdist workers can hand attempts to the main process."""
from __future__ import annotations

import base64
from typing import Any, Dict, List

from .core.model import Attachment, Attempt, ErrorInfo, Step, json_safe


def _step_out(s: Step) -> Dict[str, Any]:
    return {"title": s.title, "category": s.category, "start": s.start, "duration": s.duration, "error": s.error, "status": s.status, "steps": [_step_out(c) for c in s.steps]}


def _step_in(d: Dict[str, Any]) -> Step:
    st = Step(title=d["title"], category=d.get("category", "test.step"), start=d.get("start", 0), duration=d.get("duration", 0), error=d.get("error"), status=d.get("status"))
    st._done = True
    st.steps = [_step_in(c) for c in d.get("steps", [])]
    return st


def dump(a: Attempt) -> Dict[str, Any]:
    a.close_open_steps()
    return {
        "test_id": a.test_id, "retry": a.retry, "worker": a.worker, "start": a.start, "end": a.end, "status": a.status,
        "steps": [_step_out(s) for s in a.steps],
        "logs": list(a.logs),
        "data": [{"name": d["name"], "data": json_safe(d["data"])} for d in a.data],
        "api": [json_safe(c) for c in a.api],
        "attachments": [{"name": x.name, "content_type": x.content_type, "path": x.path,
                         "body": base64.b64encode(x.body).decode("ascii") if x.body is not None else None} for x in a.attachments],
        "errors": [{"message": e.message, "stack": e.stack, "exc_type": e.exc_type, "location": e.location, "snippet": e.snippet} for e in a.errors],
        "meta": json_safe(a.meta),
        "stdout": list(a.stdout), "stderr": list(a.stderr),
    }


def load(d: Dict[str, Any]) -> Attempt:
    a = Attempt(d["test_id"], d.get("retry", 0), d.get("worker", 0))
    a.start, a.end, a.status = d.get("start", a.start), d.get("end"), d.get("status", "passed")
    a.steps = [_step_in(s) for s in d.get("steps", [])]
    a.logs = list(d.get("logs", []))
    a.data = list(d.get("data", []))
    a.api = list(d.get("api", []))
    a.attachments = [Attachment(x["name"], x["content_type"], base64.b64decode(x["body"]) if x.get("body") else None, x.get("path")) for x in d.get("attachments", [])]
    a.errors = [ErrorInfo(e["message"], e.get("stack"), e.get("exc_type"), e.get("location"), e.get("snippet")) for e in d.get("errors", [])]
    a.meta = dict(d.get("meta", {}))
    a.stdout, a.stderr = list(d.get("stdout", [])), list(d.get("stderr", []))
    return a


def merge(into: Attempt, more: Dict[str, Any]) -> None:
    """Add a later phase's payload (call, teardown) to the attempt made from the setup phase."""
    other = load(more)
    into.steps.extend(other.steps)
    into.logs.extend(other.logs)
    into.data.extend(other.data)
    into.api.extend(other.api)
    into.attachments.extend(other.attachments)
    into.errors.extend(other.errors)
    into.meta.update(other.meta)
    into.stdout.extend(other.stdout)
    into.stderr.extend(other.stderr)
    if other.end:
        into.end = other.end
