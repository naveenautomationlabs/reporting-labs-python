"""Collects the tests of a run and builds the report data, the shape src/types.ts describes (0.6.9)."""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import envdetect, explain as explain_mod, history as history_mod, logo as logo_mod
from .mask import Masker, parse_csv
from .model import Attachment, Attempt, ErrorInfo, Step, json_safe, now_ms
from .options import Options

EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif", "video/webm": ".webm", "video/mp4": ".mp4",
       "application/zip": ".zip", "text/plain": ".txt", "application/json": ".json", "text/html": ".html", "text/csv": ".csv", "application/pdf": ".pdf"}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class TestRecord:
    id: str
    title: str
    path: List[str]
    file: str
    line: int
    project: str = ""
    tags: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    annotations: List[Dict[str, str]] = field(default_factory=list)
    attempts: List[Attempt] = field(default_factory=list)
    expected_status: Optional[str] = None     # 'failed' for xfail, 'skipped' for skip
    note: Optional[str] = None
    timeout: Optional[float] = None
    retries: Optional[int] = None
    skip_reason: Optional[str] = None
    forced_outcome: Optional[str] = None      # set by the framework: 'skipped', 'interrupted', 'timedOut'
    expected_failure: bool = False
    column: Optional[int] = None

    @property
    def key(self) -> str:
        return f"{self.project}::{self.file}::{' › '.join([*self.path, self.title])}"


class Run:
    """One test session. Add tests and attempts while it runs; `build()` makes the report data."""

    def __init__(self, options: Options, framework: str, environ: Optional[Mapping[str, str]] = None) -> None:
        self.options = options
        self.framework = framework
        self.env = dict(os.environ if environ is None else environ)
        self.masker = Masker(options.get("maskKeys") or [], options.get("maskValues") or [], options.get("maskFromEnv") is not False, environ=self.env)
        self.start = now_ms()
        self.tests: Dict[str, TestRecord] = {}
        self.order: List[str] = []
        self.global_errors: List[ErrorInfo] = []
        self.global_output: List[Dict[str, str]] = []
        self.run_status = "passed"
        self.framework_rows: List[Dict[str, str]] = []
        self.workers = 1
        self._asset_counter = 0
        self.projects_seen: List[str] = []

    # -- registering -------------------------------------------------------------------------------
    def test(self, id: str, title: str, path: Sequence[str], file: str, line: int, project: str = "", **kw: Any) -> TestRecord:
        t = self.tests.get(id)
        if t is None:
            t = TestRecord(id=id, title=title, path=list(path), file=file, line=line, project=project)
            self.tests[id] = t
            self.order.append(id)
        for k, v in kw.items():
            if v is not None:
                setattr(t, k, v)
        return t

    def add_attempt(self, test_id: str, attempt: Attempt) -> None:
        t = self.tests[test_id]
        attempt.retry = len(t.attempts)
        t.attempts.append(attempt)
        self.workers = max(self.workers, attempt.worker + 1)

    def global_error(self, err: ErrorInfo) -> None:
        self.global_errors.append(err)

    def output(self, stream: str, text: str) -> None:
        if len(self.global_output) >= 200:
            return
        text = ANSI.sub("", text)[:2000]
        if text.strip():
            self.global_output.append({"stream": stream, "text": text})

    # -- building ----------------------------------------------------------------------------------
    def build(self, end_time: Optional[float] = None) -> Dict[str, Any]:
        opts = self.options
        out_dir = opts.out_dir
        assets = out_dir / "assets"
        shutil.rmtree(assets, ignore_errors=True)
        assets.mkdir(parents=True, exist_ok=True)
        self._asset_counter = 0

        tests: List[Dict[str, Any]] = []
        projects: List[str] = []
        for tid in self.order:
            t = self.tests[tid]
            if t.project and t.project not in projects:
                projects.append(t.project)
            tests.append(self._test(t, assets))
        if not projects:
            projects = [p for p in self.projects_seen] or []
        stats = {"passed": 0, "failed": 0, "skipped": 0, "flaky": 0, "timedOut": 0, "interrupted": 0, "total": len(tests)}
        for t in tests:
            stats[t["outcome"]] += 1

        end = end_time or now_ms()
        hist_entries: List[Dict[str, Any]] = []
        if opts.history_enabled():
            prev = history_mod.load(opts.history_file)
            md = opts["metadata"]
            label = md.get("build") or envdetect.ci_run_label(self.env) or md.get("branch")
            cur = history_mod.entry(self.start, end - self.start, stats, tests, label)
            hist_entries = history_mod.roll(prev, cur, opts.history_keep())
            history_mod.save(opts.history_file, hist_entries)

        bdd = opts.get("bdd")
        if bdd is None:
            bdd = any(re.match(r"^(Given|When|Then|And|But)\b", s["title"]) for t in tests for r in t["results"] for s in r["steps"])

        failed = stats["failed"] + stats["timedOut"] + stats["interrupted"]
        run_status = self.run_status if self.run_status in ("interrupted", "timedout") else ("failed" if failed or self.global_errors else "passed")
        metadata = {str(k): self.masker.mask_str(str(v)) for k, v in opts["metadata"].items()}
        editor_default = not self.env.get("CI")
        data: Dict[str, Any] = {
            "title": self.masker.mask_str(str(opts["title"])),
            "generatedAt": now_ms(),
            "startTime": self.start,
            "duration": max(0.0, end - self.start),
            "metadata": metadata,
            "projects": projects,
            "workers": self.workers,
            "stats": stats,
            "tests": tests,
            "history": hist_entries,
            "bdd": bool(bdd),
            "rootDir": str(opts.base),
            "env": envdetect.collect_env(opts.base, self.framework_rows, {str(k): self.masker.mask_str(str(v)) for k, v in (opts.get("env") or {}).items()}, metadata, self.workers, self.env),
            "runStatus": run_status,
            "globalErrors": [self._error(e) for e in self.global_errors],
            "globalOutput": [{"stream": o["stream"], "text": self.masker.mask_str(o["text"])} for o in self.global_output],
            "options": opts.report_options(logo_mod.resolve(opts.get("logo"), opts.base), editor_default),
        }
        return data

    # -- per test ----------------------------------------------------------------------------------
    def _test(self, t: TestRecord, assets: Path) -> Dict[str, Any]:
        results = [self._result(a, t, assets) for a in t.attempts]
        outcome, note, expected_failure = self._outcome(t)
        meta, links = self._meta(t)
        d: Dict[str, Any] = {
            "id": t.id, "key": t.key, "title": self.masker.mask_str(t.title), "path": [self.masker.mask_str(p) for p in t.path],
            "file": t.file, "line": t.line, "project": t.project, "tags": list(t.tags), "annotations": list(t.annotations),
            "meta": meta, "outcome": outcome, "duration": sum(r["duration"] for r in results), "results": results,
        }
        if links:
            d["links"] = links
        if t.column is not None:
            d["column"] = t.column
        if t.expected_status:
            d["expectedStatus"] = t.expected_status
        if expected_failure:
            d["expectedFailure"] = True
        if note or t.note:
            d["note"] = note or t.note
        if t.timeout:
            d["timeout"] = t.timeout
        if t.retries is not None:
            d["retries"] = t.retries
        return d

    def _outcome(self, t: TestRecord):
        last = t.attempts[-1] if t.attempts else None
        if t.forced_outcome == "skipped" or (last and last.status == "skipped" and len(t.attempts) == 1):
            return "skipped", None, False
        if not last:
            return "interrupted", "This test never ran: the run was interrupted before it started.", False
        if t.forced_outcome in ("interrupted", "timedOut"):
            return t.forced_outcome, t.note, False
        xfail = t.expected_status == "failed"
        if last.status == "passed":
            if xfail:
                return "failed", "Passed, but the test is marked as an expected failure. If the bug is fixed, remove the marker.", False
            if any(a.status in ("failed", "timedOut") for a in t.attempts[:-1]):
                return "flaky", None, False
            return "passed", None, False
        if last.status == "timedOut":
            return "timedOut", t.note or "The test exceeded its timeout.", False
        if last.status == "interrupted":
            return "interrupted", "The run was interrupted while this test was executing.", False
        if last.status == "skipped":
            return "skipped", None, False
        if xfail or t.expected_failure:
            return "passed", "Failed as expected: this test is marked as an expected failure. The failure below is the known one.", True
        return "failed", None, False

    def _meta(self, t: TestRecord):
        dims = self.options.meta_keys()
        meta: Dict[str, str] = {}
        links: Dict[str, str] = {}
        for raw in t.tags:
            tag = raw.lstrip("@")
            m = re.match(r"^([a-z_-]+)[:=](.+)$", tag, re.I)
            if m and m.group(1).lower() in dims:
                meta[m.group(1).lower()] = m.group(2)
                continue
            if re.match(r"^P[0-4]$", tag, re.I) and "priority" in dims and "priority" not in meta:
                meta["priority"] = tag.upper()
            if re.match(r"^(blocker|critical|major|minor|trivial)$", tag, re.I) and "severity" in dims and "severity" not in meta:
                meta["severity"] = tag.lower()
        merged: Dict[str, Any] = dict(t.meta)
        for a in t.attempts:
            merged.update(a.meta)
        for k, v in merged.items():
            if v is None:
                continue
            key = str(k).lower()
            if isinstance(v, (list, tuple)):
                meta[key] = ", ".join(str(x) for x in v)
            elif isinstance(v, Mapping):
                tpl = self.options.link_template(key)
                display = tpl.get("display") if isinstance(tpl, Mapping) and tpl.get("display") else "{id}"
                shown = _fill(display, v, False)
                meta[key] = shown or str(v.get("id", next(iter(v.values()), "")))
                url = tpl if isinstance(tpl, str) else (tpl.get("url") if isinstance(tpl, Mapping) else None)
                if url:
                    links[key] = _fill(url, v, True)
            else:
                meta[key] = str(v)
        return {k: self.masker.mask_str(v) for k, v in meta.items()}, links

    def _result(self, a: Attempt, t: TestRecord, assets: Path) -> Dict[str, Any]:
        m = self.masker
        return {
            "retry": a.retry, "status": a.status, "duration": a.duration, "startTime": a.start, "workerIndex": a.worker,
            "errors": [self._error(e) for e in a.errors],
            "steps": [self._step(s) for s in a.steps],
            "attachments": [x for x in (self._attachment(att, t, assets) for att in a.attachments) if x],
            "stdout": [m.mask_str(ANSI.sub("", s)) for s in a.stdout],
            "stderr": [m.mask_str(ANSI.sub("", s)) for s in a.stderr],
            "logs": [{"t": l["t"], "msg": m.mask_str(str(l["msg"]))} for l in sorted(a.logs, key=lambda x: x["t"])],
            "data": [self._data_block(d["name"], d["data"]) for d in a.data],
            "api": [self._api(c) for c in a.api],
        }

    def _step(self, s: Step) -> Dict[str, Any]:
        d: Dict[str, Any] = {"title": self.masker.mask_str(s.title), "category": s.category, "duration": s.duration, "steps": [self._step(c) for c in s.steps]}
        if s.error:
            d["error"] = self.masker.mask_str(ANSI.sub("", s.error))
        if s.status:
            d["status"] = s.status
        return d

    def _error(self, e: ErrorInfo) -> Dict[str, Any]:
        m = self.masker
        d: Dict[str, Any] = {"message": m.mask_str(ANSI.sub("", e.message or ""))}
        why = explain_mod.explain(d["message"], e.exc_type)
        if why:
            d["explain"] = why
        if e.stack:
            d["stack"] = m.mask_str(ANSI.sub("", e.stack))
        if e.snippet:
            d["snippet"] = m.mask_str(e.snippet)
        if e.location:
            loc = dict(e.location)
            loc["file"] = self.rel(str(loc.get("file", "")))
            d["location"] = loc
        return d

    def _api(self, c: Dict[str, Any]) -> Dict[str, Any]:
        call = dict(c)
        for k in ("requestBody", "responseBody"):
            if k in call:
                call[k] = json_safe(call[k])
        return self.masker.mask(call)

    def _data_block(self, name: str, raw: Any) -> Dict[str, Any]:
        m = self.masker
        name = m.mask_str(str(name))
        v = raw
        if isinstance(v, str):
            s = v.strip()
            if s[:1] in "{[":
                try:
                    v = json.loads(s)
                except ValueError:
                    pass
            if isinstance(v, str):
                if "\n" in v and "," in v:
                    columns, rows = parse_csv(v)
                    masked = [[("****" if m.is_sensitive(columns[i] if i < len(columns) else "") else m.mask_str(c)) for i, c in enumerate(r)] for r in rows]
                    for r in rows:
                        for i, c in enumerate(r):
                            if i < len(columns) and m.is_sensitive(columns[i]):
                                m.learn(c)
                    return {"name": name, "kind": "table", "columns": columns, "rows": masked}
                return {"name": name, "kind": "text", "text": m.mask_str(v)}
        v = m.mask(json_safe(v))
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            columns: List[str] = []
            for x in v:
                for k in x:
                    if k not in columns:
                        columns.append(k)
            return {"name": name, "kind": "table", "columns": columns, "rows": [[_fmt(x.get(c)) for c in columns] for x in v]}
        if isinstance(v, dict):
            return {"name": name, "kind": "kv", "kv": [[str(k), _fmt(x)] for k, x in v.items()]}
        return {"name": name, "kind": "text", "text": json.dumps(v, indent=2, ensure_ascii=False, default=str)}

    def _attachment(self, a: Attachment, t: TestRecord, assets: Path) -> Optional[Dict[str, Any]]:
        opts = self.options
        out: Dict[str, Any] = {"name": a.name, "contentType": a.content_type}
        embed = opts.get("embedAttachments") is not False
        limit = int(opts.get("embedLimit") or 2 * 1024 * 1024)
        ct = a.content_type or ""
        is_image, is_video = ct.startswith("image/"), ct.startswith("video/")
        is_text = ct.startswith("text/") or "json" in ct
        can_embed = embed and (is_image or (is_video and opts.get("embedVideos")))
        body = a.body
        path = Path(a.path) if a.path else None
        if body is None and path and path.is_file():
            size = path.stat().st_size
            out["size"] = size
            if size <= limit and (can_embed or is_text):
                body = path.read_bytes()
        if body is not None:
            out.setdefault("size", len(body))
            if is_text:
                out["text"] = self.masker.mask_str(body.decode("utf-8", "replace")[:20000])
                return out
            if can_embed and len(body) <= limit:
                out["src"] = f"data:{ct};base64," + base64.b64encode(body).decode("ascii")
                return out
            if not path:
                name = self._asset_name(t, a.name, EXT.get(ct, ""))
                (assets / name).write_bytes(body)
                out["src"] = "assets/" + name
                return out
        if path and path.is_file():
            name = self._asset_name(t, a.name, path.suffix or EXT.get(ct, ""))
            shutil.copyfile(path, assets / name)
            out["src"] = "assets/" + name
            return out
        return None

    def _asset_name(self, t: TestRecord, name: str, ext: str) -> str:
        self._asset_counter += 1
        safe = re.sub(r"[^a-z0-9.-]", "_", name, flags=re.I)[:60]
        return f"{_sanitize(t.title)}-{safe}-{self._asset_counter}{ext}"

    def rel(self, file: str) -> str:
        if not file:
            return file
        try:
            return os.path.relpath(file, str(self.options.base)).replace(os.sep, "/")
        except ValueError:
            return file.replace(os.sep, "/")


def _sanitize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "test"


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


def _fill(template: str, fields: Mapping[str, Any], encode: bool) -> str:
    from urllib.parse import quote

    def sub(m: "re.Match[str]") -> str:
        v = fields.get(m.group(1))
        if v is None:
            return ""
        return quote(str(v), safe="") if encode else str(v)
    return re.sub(r"\{(\w+)\}", sub, template)
