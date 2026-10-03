"""The pytest plugin. Loaded through the `pytest11` entry point; on by default once the package is installed.

Turn it off with `-p no:reporting_labs`, `--no-rl`, or `reporting_labs = false` in the ini file.
"""
from __future__ import annotations

import base64
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from . import transport
from .core import collector, context, options as options_mod, writer
from .core.model import Attempt, ErrorInfo, now_ms

BROWSER_PARAMS = {"chromium", "firefox", "webkit", "chrome", "msedge", "chrome-beta", "msedge-beta", "msedge-dev"}


def pytest_addoption(parser: pytest.Parser) -> None:
    g = parser.getgroup("reporting-labs", "reportingLabs HTML report")
    g.addoption("--rl", action="store_true", default=None, help="write the reportingLabs report (default: on)")
    g.addoption("--no-rl", action="store_true", default=False, help="do not write the reportingLabs report")
    g.addoption("--rl-config", default=None, help="path to reporting-labs.config.json")
    g.addoption("--rl-output", default=None, help="output folder (default: reporting-labs)")
    g.addoption("--rl-title", default=None, help="report title")
    g.addoption("--rl-project", default=None, help="project name shown in the header and the heatmap")
    parser.addini("reporting_labs", "write the reportingLabs report", type="bool", default=True)
    parser.addini("reporting_labs_config", "path to reporting-labs.config.json", default=None)
    parser.addini("reporting_labs_project", "project name", default=None)
    parser.addini("reporting_labs_title", "report title", default=None)
    parser.addini("reporting_labs_output", "output folder", default=None)


def _is_worker(config: pytest.Config) -> bool:
    return hasattr(config, "workerinput")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "meta(**values): report metadata, e.g. meta(priority='P1', severity='critical', owner='asha', feature='checkout', story='SHOP-12'). Any key is allowed.")
    config.addinivalue_line("markers", "rl_project(name): the project this test belongs to in the report")
    enabled = config.getini("reporting_labs") and not config.getoption("--no-rl")
    if config.getoption("--rl"):
        enabled = True
    if not enabled or getattr(config.option, "collectonly", False) or getattr(config.option, "help", False):
        return
    root = Path(str(config.rootpath))
    overrides: Dict[str, Any] = {}
    for opt, key in (("--rl-title", "title"), ("--rl-output", "outputFolder")):
        v = config.getoption(opt)
        if v:
            overrides[key] = v
    for ini, key in (("reporting_labs_title", "title"), ("reporting_labs_output", "outputFolder")):
        v = config.getini(ini)
        if v and key not in overrides:
            overrides[key] = v
    opts = options_mod.load(root, overrides, config.getoption("--rl-config") or config.getini("reporting_labs_config") or None)
    project = config.getoption("--rl-project") or config.getini("reporting_labs_project") or ""
    config.pluginmanager.register(Runtime(opts), "reporting_labs_runtime")
    if opts.get("captureApi") is not False:
        from .capture import http
        http.install(int(opts.get("apiMaxBody") or 64 * 1024))
    _install_tools(opts)
    if not _is_worker(config):
        config.pluginmanager.register(Controller(config, opts, project), "reporting_labs_controller")


def _install_tools(opts: options_mod.Options) -> None:
    if opts.get("stepsFromTools") is False:
        return
    try:
        from . import playwright_support
        playwright_support.install(opts)
    except Exception:
        pass
    try:
        from . import selenium_support
        selenium_support.install(opts)
    except Exception:
        pass


def pytest_unconfigure(config: pytest.Config) -> None:
    try:
        from .capture import http
        http.uninstall()
    except Exception:
        pass


# ── runs where the tests run (every process) ──────────────────────────────────────────────────────
class Runtime:
    def __init__(self, opts: options_mod.Options) -> None:
        self.opts = opts

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_setup(self, item: pytest.Item):
        attempt = Attempt(item.nodeid, worker=_worker_index())
        item._rl_attempt = attempt  # type: ignore[attr-defined]
        context.activate(attempt)
        _apply_markers(item, attempt)
        yield

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item: pytest.Item):
        attempt: Optional[Attempt] = getattr(item, "_rl_attempt", None)
        if attempt is not None:
            context.activate(attempt)
        yield

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo):
        outcome = yield
        attempt: Optional[Attempt] = getattr(item, "_rl_attempt", None)
        if attempt is None:
            return
        report: pytest.TestReport = outcome.get_result()
        if call.excinfo is not None and report.outcome != "passed" and not report.skipped:
            exc = call.excinfo.value
            err = ErrorInfo.from_exception(exc, str(item.config.rootpath))
            if err.location is None or "site-packages" in str(err.location.get("file", "")) or "_pytest" in str(err.location.get("file", "")):
                loc = getattr(item, "location", None)
                if loc and loc[1] is not None:
                    err.location = {"file": str(Path(str(item.config.rootpath)) / str(loc[0])), "line": int(loc[1]) + 1, "column": 0}
            if report.longreprtext:
                err.message = _first_block(report.longreprtext, err.message)
            attempt.add_error(err)
            _on_failure(item, attempt, exc)
        if call.when == "teardown":
            for name, text in report.sections:
                if "stdout" in name and text:
                    attempt.stdout.append(text)
                elif "stderr" in name and text:
                    attempt.stderr.append(text)
            attempt.finish("passed")
            context.deactivate(attempt)
            item._rl_attempt = None  # type: ignore[attr-defined]
            report.rl_payload = transport.dump(attempt)  # type: ignore[attr-defined]
            report.rl_info = _item_info(item)  # type: ignore[attr-defined]
        else:
            # setup and call payloads let the controller build the attempt even if teardown never reports (crash, interrupt)
            report.rl_payload = transport.dump(attempt)  # type: ignore[attr-defined]
            report.rl_info = _item_info(item)  # type: ignore[attr-defined]


def _first_block(longrepr: str, fallback: str) -> str:
    """pytest's own failure text, trimmed to the error block (the 'E   ' lines) when there is one."""
    lines = [l[4:] if l.startswith("E   ") else l[1:] if l.startswith("E ") else None for l in longrepr.splitlines()]
    err = [l for l in lines if l is not None]
    if err:
        return "\n".join(err).strip()
    return fallback


def _on_failure(item: pytest.Item, attempt: Attempt, exc: BaseException) -> None:
    """Ask the tool integrations for a screenshot of every live page."""
    for mod in ("playwright_support", "selenium_support"):
        try:
            m = __import__(f"reporting_labs.{mod}", fromlist=["on_failure"])
            m.on_failure(item, attempt)
        except Exception:
            pass


def _apply_markers(item: pytest.Item, attempt: Attempt) -> None:
    for mark in item.iter_markers("meta"):
        for k, v in mark.kwargs.items():
            attempt.meta.setdefault(str(k).lower(), v)
        for arg in mark.args:
            if isinstance(arg, dict):
                for k, v in arg.items():
                    attempt.meta.setdefault(str(k).lower(), v)


def _worker_index() -> int:
    w = os.environ.get("PYTEST_XDIST_WORKER", "")
    m = re.match(r"gw(\d+)$", w)
    return int(m.group(1)) if m else 0


def _item_info(item: pytest.Item) -> Dict[str, Any]:
    tags: List[str] = []
    project = ""
    for mark in item.iter_markers():
        if mark.name in ("meta", "parametrize", "usefixtures", "filterwarnings", "skip", "skipif", "xfail", "timeout", "flaky", "asyncio", "anyio"):
            if mark.name == "rl_project" and mark.args:
                project = str(mark.args[0])
            continue
        if mark.name == "rl_project":
            if mark.args:
                project = str(mark.args[0])
            continue
        tag = mark.name
        if mark.args and all(isinstance(a, (str, int)) for a in mark.args):
            tag = f"{mark.name}:{','.join(str(a) for a in mark.args)}" if mark.args else mark.name
        if tag not in tags:
            tags.append(tag)
    timeout = None
    for mark in item.iter_markers("timeout"):
        if mark.args:
            try:
                timeout = float(mark.args[0]) * 1000
            except (TypeError, ValueError):
                pass
    return {"tags": tags, "project": project, "timeout": timeout, "file": str(getattr(item, "fspath", "") or getattr(item, "path", ""))}


# ── runs in the main process only ──────────────────────────────────────────────────────────────────
class Controller:
    def __init__(self, config: pytest.Config, opts: options_mod.Options, project: str) -> None:
        self.config = config
        self.opts = opts
        self.project = project
        self.run = collector.Run(opts, "pytest")
        self.attempts: Dict[str, Attempt] = {}        # nodeid -> the attempt being assembled from phase reports
        self._after_rerun: set = set()
        self.collected: List[Dict[str, Any]] = []
        self.lines: List[str] = []
        self.interrupted = False
        self.run.framework_rows = self._framework_rows()

    def _framework_rows(self) -> List[Dict[str, str]]:
        from .core.envdetect import package_version
        rows = [{"k": "pytest", "v": pytest.__version__}]
        plugins = [f"{n} {v}" for n, v in ((n, package_version(n)) for n in ("pytest-playwright", "playwright", "selenium", "pytest-xdist", "pytest-rerunfailures", "pytest-timeout", "requests", "httpx")) if v]
        if plugins:
            rows.append({"k": "Packages", "v": ", ".join(plugins)})
        return rows

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        self.run.start = now_ms()

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        for item in session.items:
            self._register(item.nodeid, _item_info(item), item.location if hasattr(item, "location") else None)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            text = report.longreprtext or str(report.longrepr)
            lines = [l for l in text.splitlines() if l.strip()]
            self.run.global_error(ErrorInfo(message=f"{report.nodeid or 'collection'}: {lines[-1] if lines else 'collection failed'}", stack=text, exc_type="CollectError"))

    def pytest_internalerror(self, excrepr: Any) -> None:
        text = str(excrepr)
        lines = [l for l in text.splitlines() if l.strip()]
        self.run.global_error(ErrorInfo(message=lines[-1] if lines else "pytest internal error", stack=text, exc_type="InternalError"))

    def pytest_keyboard_interrupt(self, excinfo: pytest.ExceptionInfo) -> None:
        if type(excinfo.value).__name__ in ("Interrupted", "Exit"):
            return
        self.interrupted = True
        self.run.run_status = "interrupted"

    # -- one test, one or more attempts, three phase reports each ---------------------------------
    def _register(self, nodeid: str, info: Dict[str, Any], location: Any = None) -> collector.TestRecord:
        file, line, path, title = self._split(nodeid, location)
        project = info.get("project") or self.project or self._browser_from_title(title) or "pytest"
        if project in BROWSER_PARAMS:
            title = re.sub(r"\[" + re.escape(project) + r"\]$", "", title) or title
            title = re.sub(r"\[" + re.escape(project) + r"-", "[", title)
        return self.run.test(nodeid, title, path, file, line, project, tags=info.get("tags"), timeout=info.get("timeout"))

    def _browser_from_title(self, title: str) -> str:
        m = re.search(r"\[([^\]]+)\]$", title)
        if not m:
            return ""
        for part in m.group(1).split("-"):
            if part in BROWSER_PARAMS:
                return part
        return ""

    def _split(self, nodeid: str, location: Any):
        parts = nodeid.split("::")
        file = parts[0]
        line = 0
        if location and len(location) >= 2 and location[1] is not None:
            file = str(location[0]).replace(os.sep, "/")
            line = int(location[1]) + 1
        path = [p for p in parts[1:-1] if p != "()"]
        return file, line, path, parts[-1]

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        payload = getattr(report, "rl_payload", None)
        info = getattr(report, "rl_info", None) or {}
        t = self._register(report.nodeid, info, report.location)
        if payload is None:
            # a plugin cut the protocol short, or the runtime is not installed on this worker: keep an attempt anyway
            payload = transport.dump(Attempt(report.nodeid))
        if report.when == "teardown" and report.nodeid in self._after_rerun:
            # the teardown of a rerun attempt; that attempt was closed when the rerun was reported
            self._after_rerun.discard(report.nodeid)
            return
        previous = self.attempts.get(report.nodeid)
        # every phase payload carries the whole attempt so far, so the latest one replaces the previous
        attempt = transport.load(payload)
        self.attempts[report.nodeid] = attempt
        if previous is None or report.when == "setup":
            attempt._rl_status = "passed"  # type: ignore[attr-defined]
            attempt._rl_skipped = None  # type: ignore[attr-defined]
        else:
            attempt._rl_status = previous._rl_status  # type: ignore[attr-defined]
            attempt._rl_skipped = previous._rl_skipped  # type: ignore[attr-defined]
        status: str = attempt._rl_status  # type: ignore[attr-defined]
        if report.when == "setup":
            if report.failed:
                status = "failed"
            elif report.skipped:
                attempt._rl_skipped = _skip_reason(report)  # type: ignore[attr-defined]
                status = "skipped"
        elif report.when == "call":
            if report.outcome == "rerun":
                status = "failed"
                attempt._rl_rerun = True  # type: ignore[attr-defined]
            elif report.failed:
                status = "timedOut" if _is_timeout(report) else "failed"
            elif report.skipped:
                if hasattr(report, "wasxfail"):
                    t.expected_status = "failed"
                    t.expected_failure = True
                    t.note = ("Failed as expected (xfail: " + str(report.wasxfail) + ").") if report.wasxfail else None
                    status = "failed"
                else:
                    attempt._rl_skipped = _skip_reason(report)  # type: ignore[attr-defined]
                    status = "skipped"
            elif hasattr(report, "wasxfail"):
                # xpass: passed although marked xfail (non-strict). Strict xpass arrives as failed above.
                t.expected_status = "failed"
                t.note = "Passed, but the test is marked xfail. If the bug is fixed, remove the marker."
                status = "failed"
        elif report.when == "teardown":
            if report.failed and status in ("passed", "skipped"):
                status = "failed"
        attempt._rl_status = status  # type: ignore[attr-defined]
        if report.outcome == "rerun":
            self._after_rerun.add(report.nodeid)
            self._close(t, attempt)
        elif report.when == "teardown":
            self._close(t, attempt)

    def _close(self, t: collector.TestRecord, attempt: Attempt) -> None:
        self.attempts.pop(t.id, None)
        status = attempt._rl_status  # type: ignore[attr-defined]
        if status == "skipped":
            t.skip_reason = attempt._rl_skipped  # type: ignore[attr-defined]
            if t.skip_reason:
                t.annotations = [a for a in t.annotations if a.get("type") != "skip"] + [{"type": "skip", "description": t.skip_reason}]
        attempt.finish(status)
        self.run.add_attempt(t.id, attempt)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        # attempts whose teardown never reported (crash, Ctrl+C mid-test)
        for nodeid, attempt in list(self.attempts.items()):
            t = self.run.tests.get(nodeid)
            if t is not None:
                attempt._rl_status = "interrupted" if self.interrupted else attempt._rl_status  # type: ignore[attr-defined]
                self._close(t, attempt)
        if self.interrupted:
            for t in self.run.tests.values():
                if not t.attempts:
                    t.forced_outcome = "interrupted"
        try:
            data = self.run.build()
            html = writer.write(data, self.opts)
        except Exception as e:  # never fail the test session because of the report
            self.lines.append(f"reporting-labs: could not write the report: {type(e).__name__}: {e}")
            return
        self.lines.extend(writer.announce_lines(html, data, self.opts))
        writer.maybe_open(html, data["runStatus"], self.opts)

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        if not self.lines:
            return
        terminalreporter.write_line("")
        for line in self.lines:
            terminalreporter.write_line(line)


def _skip_reason(report: pytest.TestReport) -> Optional[str]:
    lr = report.longrepr
    if isinstance(lr, tuple) and len(lr) >= 3:
        return re.sub(r"^Skipped:\s*", "", str(lr[2])).strip() or None
    text = report.longreprtext
    return re.sub(r"^Skipped:\s*", "", text.strip()) or None if text else None


def _is_timeout(report: pytest.TestReport) -> bool:
    text = report.longreprtext or ""
    return bool(re.search(r"Failed: Timeout >\s*[\d.]+s|\bTimeout >\s*[\d.]+s\b", text))
