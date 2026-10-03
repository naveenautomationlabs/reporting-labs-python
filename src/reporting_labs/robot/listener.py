"""Robot Framework listener (API v3): one row per test, every keyword a step, tags as filters and meta.

    robot --listener reporting_labs.RobotListener tests/
    robot --listener reporting_labs.RobotListener:title=Checkout:output=reports/rl tests/

Suites become the test's path, setup and teardown keywords show as hooks, log messages become log lines,
screenshots SeleniumLibrary or the Browser library embed in the log are attached, SeleniumLibrary commands
and RequestsLibrary calls are recorded through the same Selenium and HTTP capture the pytest plugin uses.
"""
from __future__ import annotations

import html as html_mod
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core import collector, context, options as options_mod, writer
from ..core.model import Attempt, ErrorInfo, Step, now_ms

_IMG = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
_HREF = re.compile(r"<a[^>]+href=[\"']([^\"']+)[\"']", re.I)
_TAG = re.compile(r"<[^>]+>")
_SECRET_KW = re.compile(r"password|passwd|secret|token|credential|otp|pin\b", re.I)
_SECRET_ARG = re.compile(r"password|passwd|pwd|secret|token|otp|\bpin\b|\bpw\b", re.I)


class ReportingLabsListener:
    ROBOT_LISTENER_API_VERSION = 3

    def __init__(self, **kwargs: str) -> None:
        self.overrides: Dict[str, Any] = {}
        self.project = kwargs.pop("project", "") or ""
        self.config_file = kwargs.pop("config", None)
        for k, v in kwargs.items():
            key = {"output": "outputFolder", "out": "outputFolder"}.get(k, k)
            self.overrides[key] = v
        self.root = Path.cwd()
        self.opts = options_mod.load(self.root, self.overrides, self.config_file)
        self.run = collector.Run(self.opts, "robot")
        self.output_dir: Optional[Path] = None
        self.attempt: Optional[Attempt] = None
        self.test_id: Optional[str] = None
        self.suite_stack: List[str] = []
        self._steps: List[Step] = []
        self._install_capture()

    def _install_capture(self) -> None:
        if self.opts.get("captureApi") is not False:
            try:
                from ..capture import http
                http.install(int(self.opts.get("apiMaxBody") or 64 * 1024))
            except Exception:
                pass
        if self.opts.get("stepsFromTools") is not False:
            for mod in ("selenium_support", "playwright_support"):
                try:
                    __import__(f"reporting_labs.{mod}", fromlist=["install"]).install(self.opts)
                except Exception:
                    pass

    # ── suites ────────────────────────────────────────────────────────────────────────────────────
    def start_suite(self, data: Any, result: Any) -> None:
        if not self.suite_stack:
            self.run.start = now_ms()
            try:
                from robot.libraries.BuiltIn import BuiltIn
                self.output_dir = Path(str(BuiltIn().get_variable_value("${OUTPUT DIR}")))
            except Exception:
                self.output_dir = None
        self.suite_stack.append(data.name)

    def end_suite(self, data: Any, result: Any) -> None:
        if self.suite_stack:
            self.suite_stack.pop()
        if result.failed and not result.passed and result.message and not self.suite_stack:
            pass  # suite-level message is already on the tests it failed

    # ── tests ─────────────────────────────────────────────────────────────────────────────────────
    def start_test(self, data: Any, result: Any) -> None:
        self.test_id = data.longname
        source = str(data.source) if data.source else ""
        file = os.path.relpath(source, str(self.opts.base)).replace(os.sep, "/") if source else ""
        self.run.test(self.test_id, data.name, list(self.suite_stack[1:]) if len(self.suite_stack) > 1 else [], file, int(data.lineno or 0),
                      self.project or "robot", tags=[str(t) for t in data.tags], timeout=_timeout_ms(data))
        self.attempt = Attempt(self.test_id)
        if data.doc:
            self.attempt.log(str(data.doc))
        context.activate(self.attempt)

    def end_test(self, data: Any, result: Any) -> None:
        a = self.attempt
        if a is None:
            return
        t = self.run.tests[self.test_id or data.longname]
        status = "passed"
        if result.status == "FAIL":
            status = "timedOut" if re.search(r"timeout .* exceeded", result.message or "", re.I) else "failed"
            if result.message:
                a.add_error(ErrorInfo(message=str(result.message), exc_type=_exc_type(result.message), location={"file": str(data.source or ""), "line": int(data.lineno or 0), "column": 0}))
            if status == "timedOut":
                t.note = str(result.message)
        elif result.status == "SKIP":
            status = "skipped"
            t.skip_reason = str(result.message or "") or None
            if t.skip_reason:
                t.annotations.append({"type": "skip", "description": t.skip_reason})
        elif result.status == "NOT RUN":
            status = "skipped"
        a.finish(status)
        context.deactivate(a)
        self.run.add_attempt(t.id, a)
        self.attempt = None
        self.test_id = None

    # ── keywords and control structures as steps ─────────────────────────────────────────────────
    def start_keyword(self, data: Any, result: Any) -> None:
        self._begin(_kw_title(data, result), "hook" if result.type in ("SETUP", "TEARDOWN") else ("test.step" if _is_user_keyword(result) else "keyword"))

    def end_keyword(self, data: Any, result: Any) -> None:
        self._end(result)

    def start_body_item(self, data: Any, result: Any) -> None:
        if result.type in ("KEYWORD", "SETUP", "TEARDOWN"):
            return self.start_keyword(data, result)
        self._begin(_control_title(result), "control")

    def end_body_item(self, data: Any, result: Any) -> None:
        if result.type in ("KEYWORD", "SETUP", "TEARDOWN"):
            return self.end_keyword(data, result)
        self._end(result)

    def _begin(self, title: str, category: str) -> None:
        if self.attempt is None:
            return
        self._steps.append(self.attempt.begin_step(title, category))

    def _end(self, result: Any) -> None:
        if self.attempt is None or not self._steps:
            return
        st = self._steps.pop()
        error = None
        if result.status == "FAIL":
            error = str(result.message or "FAIL")
        elif result.status == "NOT RUN":
            st.status = "skipped"
        self.attempt.end_step(st, error)

    # ── messages ──────────────────────────────────────────────────────────────────────────────────
    def log_message(self, message: Any) -> None:
        a = self.attempt
        if a is None:
            return
        level = str(message.level)
        text = str(message.message or "")
        if message.html or re.search(r"<img\b|<a\b", text, re.I):
            for src in _IMG.findall(text):
                self._attach_file(a, src, "image")
            for href in _HREF.findall(text):
                if not _IMG.search(text) and re.search(r"\.(png|jpe?g|webp|gif|webm|mp4|zip|pdf|txt|log|json)$", href, re.I):
                    self._attach_file(a, href, "file")
            plain = html_mod.unescape(_TAG.sub(" ", text)).strip()
            if plain and not _IMG.search(text):
                a.log(plain)
            return
        if level in ("INFO", "WARN", "ERROR", "FAIL", "SKIP"):
            a.log((level + ": " + text) if level in ("WARN", "ERROR") else text)

    def _attach_file(self, a: Attempt, src: str, kind: str) -> None:
        if src.startswith("data:"):
            m = re.match(r"data:([^;]+);base64,(.+)", src, re.S)
            if m:
                import base64
                a.attach("screenshot", base64.b64decode(m.group(2)), m.group(1))
            return
        p = Path(src)
        if not p.is_absolute():
            for base in (self.output_dir, self.root):
                if base and (base / src).is_file():
                    p = base / src
                    break
        if p.is_file():
            name = p.name
            ext = p.suffix.lower().lstrip(".")
            ct = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "webm": "video/webm", "mp4": "video/mp4",
                  "zip": "application/zip", "pdf": "application/pdf", "txt": "text/plain", "log": "text/plain", "json": "application/json"}.get(ext, "application/octet-stream")
            a.attach(name if kind == "file" else ("screenshot" if "screenshot" in name.lower() else name), path=str(p), content_type=ct)

    def message(self, message: Any) -> None:
        if str(message.level) in ("ERROR",) and self.attempt is None:
            self.run.global_error(ErrorInfo(message=str(message.message), exc_type="RobotError"))

    # ── end of run ────────────────────────────────────────────────────────────────────────────────
    def output_file(self, path: Any) -> None:
        if path:
            self.output_dir = Path(str(path)).parent

    def close(self) -> None:
        try:
            self.run.framework_rows = self._framework_rows()
            data = self.run.build()
            html = writer.write(data, self.opts)
        except Exception as e:
            print(f"reporting-labs: could not write the report: {type(e).__name__}: {e}", file=sys.stderr)
            return
        for line in writer.announce_lines(html, data, self.opts):
            print(line)
        writer.maybe_open(html, data["runStatus"], self.opts)

    def _framework_rows(self) -> List[Dict[str, str]]:
        from ..core.envdetect import package_version
        rows = [{"k": "Robot Framework", "v": package_version("robotframework") or "?"}]
        libs = [f"{n} {v}" for n, v in ((n, package_version(n)) for n in ("robotframework-seleniumlibrary", "robotframework-browser", "robotframework-requests", "robotframework-appiumlibrary")) if v]
        if libs:
            rows.append({"k": "Libraries", "v": ", ".join(libs)})
        for mod in ("selenium_support", "playwright_support"):
            try:
                rows.extend(__import__(f"reporting_labs.{mod}", fromlist=["env_rows"]).env_rows())
            except Exception:
                pass
        return rows


def _is_user_keyword(result: Any) -> bool:
    lib = getattr(result, "owner", None) or getattr(result, "libname", None) or ""
    return not lib or str(lib).endswith(".robot") or str(lib).endswith(".resource")


def _kw_title(data: Any, result: Any) -> str:
    name = str(getattr(result, "full_name", None) or getattr(result, "name", None) or getattr(data, "name", "") or "keyword")
    short = name.split(".")[-1] if "." in name and not name.startswith(".") else name
    args = [str(a) for a in (getattr(result, "args", None) or getattr(data, "args", None) or [])]
    if _SECRET_KW.search(short):
        args = [args[0], "****"] + ["****"] * (len(args) - 2) if len(args) > 1 else args
    else:
        out = []
        hide = False
        for a in args:
            out.append("****" if hide else a)
            if _SECRET_ARG.search(a):
                hide = True
        args = out
    assign = [str(x) for x in (getattr(result, "assign", None) or getattr(data, "assign", None) or [])]
    title = short
    if args:
        title += "  " + "  ".join(a if len(a) <= 80 else a[:79] + "…" for a in args[:6]) + ("  …" if len(args) > 6 else "")
    if assign:
        title = ", ".join(assign) + " = " + title
    return title


def _control_title(result: Any) -> str:
    t = str(result.type)
    try:
        if t == "FOR":
            return f"FOR {', '.join(result.assign)} {result.flavor} {' '.join(result.values)}"
        if t == "WHILE":
            return f"WHILE {result.condition or ''}".strip()
        if t in ("IF", "ELSE IF"):
            return f"{t} {result.condition}"
        if t == "ITERATION":
            v = getattr(result, "assign", None)
            return "iteration" + (" " + ", ".join(f"{k} = {x}" for k, x in dict(v).items()) if isinstance(v, dict) and v else "")
        if t == "VAR":
            return f"VAR {result.name} = {' '.join(result.value) if isinstance(result.value, (list, tuple)) else result.value}"
        if t == "RETURN":
            return "RETURN " + " ".join(result.values)
        if t == "EXCEPT":
            return "EXCEPT " + " ".join(result.patterns)
    except Exception:
        pass
    return t


def _timeout_ms(data: Any) -> Optional[float]:
    try:
        t = data.timeout
        if not t:
            return None
        from robot.utils import timestr_to_secs
        return float(timestr_to_secs(t)) * 1000
    except Exception:
        return None


def _exc_type(message: str) -> Optional[str]:
    m = re.match(r"^(\w+(?:Error|Exception)):", message or "")
    if m:
        return m.group(1)
    if re.search(r"^Element .* not found|did not appear|Page should have contained|should have been|not found", message or "", re.I):
        return "AssertionError"
    return None
