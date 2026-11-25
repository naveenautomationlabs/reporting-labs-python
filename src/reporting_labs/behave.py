"""reportingLabs for Behave: the report from Behave's own hooks, no pytest needed.

In features/environment.py::

    from reporting_labs.behave import ReportingLabs

    def before_all(context):
        context.rl = ReportingLabs()                      # options as in reporting-labs.config.json

    def before_scenario(context, scenario):
        context.rl.before_scenario(scenario)

    def before_step(context, step):
        context.rl.before_step(step)

    def after_step(context, step):
        context.rl.after_step(step)

    def after_scenario(context, scenario):
        context.rl.after_scenario(scenario)              # before you close the browser: the failure screenshot

    def after_all(context):
        context.rl.after_all()                            # writes reporting-labs/index.html

What lands in the report, the same as with pytest-bdd:

- one row per scenario, at its .feature file and line, under its Feature (and Rule); a Scenario Outline row shows
  its Examples values as a data block
- every Gherkin step, Background included, with its time; the Playwright, Selenium and requests/httpx calls made in
  a step nest under it; data tables and doc strings become data blocks
- the failing step carries the error, the steps after it show as not run; an undefined step fails the scenario at its
  .feature line, with the step definition to write
- tags: @P1 and @critical set priority and severity, @owner:asha sets the owner (any key the report knows),
  anything else is a tag
- on failure, a screenshot of every open Playwright page and Selenium browser; pass the scenario's Playwright
  BrowserContext to after_scenario for its trace (when the steps started one) and its videos, in step with the steps
- "What the browser saw" for Playwright pages: JavaScript errors, console.error, failed and 4xx/5xx requests
- the command that runs a scenario again: behave features/cart.feature:12

Every hook is guarded: a problem in the report never fails a scenario.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .core import collector, context as rl_context, doc_meta, options as options_mod, writer
from .core.model import Attempt, ErrorInfo, now_ms

__all__ = ["ReportingLabs"]

# Behave's status names -> the report's
_STATUS = {"passed": "passed", "failed": "failed", "error": "failed", "hook_error": "failed", "cleanup_error": "failed",
           "undefined": "failed", "skipped": "skipped", "untested": "skipped", "untested_pending": "skipped",
           "untested_undefined": "failed", "pending": "skipped", "pending_warn": "skipped"}
_FAILED = {"failed", "error", "hook_error", "cleanup_error", "undefined", "untested_undefined"}


def _status(thing: Any) -> str:
    """Behave's status as a plain name: 'passed', 'failed', 'undefined' ... (an enum in Behave 1.2.6+)."""
    s = getattr(thing, "status", None)
    return str(getattr(s, "name", s) or "untested").lower()


class ReportingLabs:
    """Collects a Behave run and writes the HTML report in after_all. Keyword arguments are options, as in
    reporting-labs.config.json (title, outputFolder, metadata, embedVideos, ...); they win over the config file.
    `config` points at a config file elsewhere; `project` names the run's project (default "behave")."""

    def __init__(self, config: Optional[str] = None, project: str = "behave", **options: Any) -> None:
        self.opts = options_mod.load(Path.cwd(), options, config)
        if self.opts.values.get("bdd") is None:
            self.opts.values["bdd"] = True             # Given / When / Then styled steps, "Scenario steps"
        self.project = project
        self.run = collector.Run(self.opts, "behave")
        self.run.rerun = {"pre": "behave ", "sep": " "}  # behave features/cart.feature:12 features/login.feature:8
        self.attempt: Optional[Attempt] = None
        self._step: Any = None
        self._install_capture()

    def _install_capture(self) -> None:
        if self.opts.get("captureApi") is not False:
            try:
                from .capture import http
                http.install(int(self.opts.get("apiMaxBody") or 64 * 1024))
            except Exception:
                pass
        if self.opts.get("stepsFromTools") is not False:
            for mod in ("playwright_support", "selenium_support"):
                try:
                    __import__(f"reporting_labs.{mod}", fromlist=["install"]).install(self.opts)
                except Exception:
                    pass

    # ── scenarios ──────────────────────────────────────────────────────────────────────────────────
    def before_scenario(self, scenario: Any) -> None:
        try:
            self._begin(scenario)
        except Exception as e:
            _warn("before_scenario", e)

    def _begin(self, scenario: Any) -> None:
        if self.attempt is not None:                   # after_scenario never came for the last one
            self._close(self.attempt, "failed")
        feature = scenario.feature
        file = _rel(str(getattr(feature, "filename", "") or getattr(scenario, "filename", "") or ""))
        line = int(getattr(scenario, "line", 0) or 0)
        test_id = f"{file}:{line}"
        path = [str(feature.name)]
        rule = getattr(scenario, "parent", None)      # Behave 1.2.7+: a scenario inside "Rule:" has the Rule as parent
        if rule is not None and type(rule).__name__ == "Rule" and getattr(rule, "name", None):
            path.append(str(rule.name))
        tags = [str(t) for t in (getattr(scenario, "effective_tags", None) or getattr(scenario, "tags", []) or [])]
        meta, tags = doc_meta.tag_meta(tags, self.opts.meta_keys())   # like the Cucumber JVM plugin and pytest-bdd
        row = getattr(scenario, "_row", None)          # a Scenario Outline row
        t = self.run.test(test_id, _title(scenario, row), path, file, line, self.project, tags=tags)
        t.rerun = [collector.shell_arg(test_id)]
        a = Attempt(test_id)
        for k, v in meta.items():
            a.meta.setdefault(k, v)
        if row is not None:
            try:
                a.test_data([dict(zip([str(h) for h in row.headings], [str(c) for c in row.cells]))], "Examples")
            except Exception:
                pass
        description = getattr(scenario, "description", None)
        if description:
            a.log("\n".join(str(x) for x in description))
        self.attempt = a
        rl_context.activate(a)

    def before_step(self, step: Any) -> None:
        a = self.attempt
        if a is None:
            return
        try:
            self._step = a.begin_step(_step_title(step), "test.step")
            table = getattr(step, "table", None)
            if table:
                heads = [str(h) for h in table.headings]
                a.test_data([dict(zip(heads, [str(c) for c in r.cells])) for r in table.rows], str(step.name))
            text = getattr(step, "text", None)
            if text:
                a.test_data(str(text), str(step.name))
        except Exception as e:
            _warn("before_step", e)

    def after_step(self, step: Any) -> None:
        a, st = self.attempt, self._step
        if a is None or st is None:
            return
        try:
            error = None
            if _status(step) in _FAILED:
                exc = getattr(step, "exception", None)
                if exc is not None:                    # the same in every Behave version: "ValueError: ..."
                    text = str(exc).strip()
                    error = type(exc).__name__ + (": " + text.splitlines()[0] if text else "")
                else:                                  # Behave's own text, without its prefix
                    lines = [x for x in _clean(getattr(step, "error_message", None) or "").splitlines() if x.strip()]
                    error = lines[0] if lines else f"Step {_status(step)}"
            a.end_step(st, error)
        except Exception as e:
            _warn("after_step", e)
        self._step = None

    def after_scenario(self, scenario: Any, browser_context: Any = None, trace: str = "retain-on-failure") -> None:
        """Call it before closing the browser, so a failure gets a screenshot. Pass the scenario's Playwright
        BrowserContext to get its trace (when the steps started tracing; `trace` is "retain-on-failure", "on" or
        "off") and its videos: this closes the context, since a video is complete only then."""
        a = self.attempt
        if a is None:
            return
        try:
            status = _STATUS.get(_status(scenario), "failed")
            if self._step is not None:                 # a hook failed mid-step
                a.end_step(self._step, "The step did not finish")
                self._step = None
            if status == "failed":
                self._failure(scenario, a)
            elif status == "skipped":
                reason = getattr(scenario, "skip_reason", None) or getattr(scenario, "_skip_reason", None)
                t = self.run.tests.get(a.test_id)
                if t is not None and reason:
                    t.skip_reason = str(reason)
                    t.annotations.append({"type": "skip", "description": str(reason)})
            self._not_run(scenario, a)
            if browser_context is not None:
                self._finish_browser(browser_context, a, failed=status == "failed", trace=trace)
        except Exception as e:
            _warn("after_scenario", e)
            status = "failed" if _status(scenario) in _FAILED else "passed"
        self._close(a, status)

    def _failure(self, scenario: Any, a: Attempt) -> None:
        feature_file = str(getattr(scenario.feature, "filename", "") or "")
        for step in _all_steps(scenario):
            st = _status(step)
            if st not in _FAILED:
                continue
            path = str(getattr(step, "filename", "") or feature_file)
            line = int(getattr(step, "line", 0) or 0)
            if st in ("undefined", "untested_undefined"):
                msg = (f"The step '{_step_title(step)}' is undefined. Write a step definition for it, "
                       f"e.g. @{str(getattr(step, 'step_type', 'given') or 'given').lower()}(\"{step.name}\")")
                err = ErrorInfo(message=msg, exc_type="StepNotDefined")
            elif getattr(step, "exception", None) is not None:
                err = ErrorInfo.from_exception(step.exception, str(Path.cwd()))
                err.message = _clean(err.message)
            else:
                err = ErrorInfo(message=_clean(getattr(step, "error_message", None) or "") or f"Step {st}: {_step_title(step)}")
            if path and line:
                err.location = {"file": str(Path(path).resolve()), "line": line, "column": 0}
                err.snippet = _snippet(path, line)
            a.add_error(err)
            break
        else:
            # a hook failed (before_scenario, before_feature ...): no step carries the error
            msg = _clean(getattr(scenario, "error_message", None) or "") or "The scenario failed in a hook"
            a.add_error(ErrorInfo(message=msg))
        for mod in ("playwright_support", "selenium_support"):   # a screenshot of every open page and browser
            try:
                sys.modules[f"reporting_labs.{mod}"].on_failure(None, a)
            except Exception:
                pass

    def _not_run(self, scenario: Any, a: Attempt) -> None:
        """Steps Behave never ran: an undefined one (failed), and the ones after a failure (greyed out)."""
        for step in _all_steps(scenario):
            st = _status(step)
            if st in ("undefined", "untested_undefined"):
                a.record_step(_step_title(step), "test.step", now_ms(), 0, "Step not defined: no step definition matches it")
            elif st in ("skipped", "untested", "untested_pending"):
                a.record_step(_step_title(step), "test.step", now_ms(), 0).status = "skipped"

    def _finish_browser(self, bctx: Any, a: Attempt, failed: bool, trace: str) -> None:
        try:
            from . import playwright_support
        except Exception:
            return
        folder = self.opts.out_dir / ".behave"
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", a.test_id).strip("-")
        keep = trace == "on" or (trace == "retain-on-failure" and failed)
        try:                                           # the trace, when the steps started one
            if keep:
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{stem}-trace.zip"
                bctx.tracing.stop(path=str(path))
                if path.is_file():
                    a.attach("trace", path=str(path), content_type="application/zip")
            else:
                bctx.tracing.stop()
        except Exception:
            pass                                       # tracing was not started
        # every page of the scenario, in the order they opened: the ones still open, and popups or tabs closed
        # earlier (Playwright keeps their video until the context closes), each with the time it closed
        seq = a.__dict__.get("_rl_seq", [])
        pages: List[Any] = [p for p in (e["ref"]() for e in seq) if p is not None]
        for p in list(getattr(bctx, "pages", []) or []):
            if not any(p is q for q in pages):
                pages.append(p)
        videos = []
        for p in pages:
            try:
                if p.context is bctx and p.video:
                    videos.append((p, p.video))
            except Exception:
                pass
        try:
            bctx.close()
        except Exception:
            pass
        now = now_ms()
        for p, v in videos:
            try:
                path = Path(v.path())
                if not path.is_file():
                    continue
                closed = next((e["closed"] for e in seq if e["ref"]() is p and e.get("closed")), None) or now
                length = playwright_support.webm_duration_ms(str(path))
                # its first frame (the page closed minus the video's length), so the video plays in step with the steps
                a.attach("video", path=str(path), content_type="video/webm", video_start=closed - length if length > 0 else None)
            except Exception:
                pass

    def _close(self, a: Attempt, status: str) -> None:
        try:
            a.finish(status)
            rl_context.deactivate(a)
            self.run.add_attempt(a.test_id, a)
        except Exception as e:
            _warn("after_scenario", e)
        self.attempt = None
        self._step = None

    # ── end of the run ─────────────────────────────────────────────────────────────────────────────
    def after_all(self) -> Optional[Path]:
        """Writes the report. Returns the path of index.html, or None when it could not be written."""
        if self.attempt is not None:
            self._close(self.attempt, "failed")
        try:
            self.run.framework_rows = self._framework_rows()
            data = self.run.build()
            html = writer.write(data, self.opts)
        except Exception as e:
            print(f"reporting-labs: could not write the report: {type(e).__name__}: {e}", file=sys.__stderr__ or sys.stderr)
            return None
        # Behave captures what hooks print unless run with --no-capture: write to the terminal itself
        out = sys.__stdout__ or sys.stdout
        for line in writer.announce_lines(html, data, self.opts):
            print(line, file=out)
        try:
            out.flush()
        except Exception:
            pass
        writer.maybe_open(html, data["runStatus"], self.opts)
        return html

    def _framework_rows(self) -> List[Dict[str, str]]:
        from .core.envdetect import package_version
        rows = [{"k": "Behave", "v": package_version("behave") or "?"}]
        for mod in ("playwright_support", "selenium_support"):
            m = sys.modules.get(f"reporting_labs.{mod}")
            if m is not None:
                try:
                    rows.extend(m.env_rows())
                except Exception:
                    pass
        return rows


# ── helpers ────────────────────────────────────────────────────────────────────────────────────────
def _all_steps(scenario: Any) -> List[Any]:
    """Background steps, then the scenario's own."""
    steps = getattr(scenario, "all_steps", None)
    if steps is None:
        return list(getattr(scenario, "steps", []) or [])
    return list(steps() if callable(steps) else steps)


def _title(scenario: Any, row: Any) -> str:
    # Behave names an Outline row "Coupon HALF lowers the total -- @1.2 Coupons"
    name = re.sub(r"\s+--\s+@\d+(\.\d+)*\b.*$", "", str(scenario.name)).strip() or str(scenario.name)
    if row is not None:
        values = [str(c) for c in getattr(row, "cells", [])]
        if values and not any(v and v in name for v in values):
            name += " (" + ", ".join(values) + ")"     # an Outline whose name has no <placeholder>: as in pytest-bdd
    return name


def _step_title(step: Any) -> str:
    kw = str(getattr(step, "keyword", "") or getattr(step, "step_type", "") or "").strip()
    return (kw[:1].upper() + kw[1:] + " " if kw else "") + str(getattr(step, "name", "") or "")


def _clean(message: str) -> str:
    """Behave's 'ASSERT FAILED: ' and 'ERROR: ' prefixes off a step's error (a hook's 'HOOK-ERROR in ...' stays)."""
    return re.sub(r"^\s*(ASSERT FAILED|ERROR):\s*", "", str(message or "").strip())


def _rel(path: str) -> str:
    if not path:
        return ""
    try:
        return os.path.relpath(path).replace(os.sep, "/")
    except ValueError:                                 # another drive on Windows
        return path.replace(os.sep, "/")


def _snippet(path: str, line: int) -> Optional[str]:
    """The lines around a .feature line, the failing one marked."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return None
    if line <= 0 or line > len(lines):
        return None
    lo, hi = max(1, line - 3), min(len(lines), line + 3)
    w = len(str(hi))
    return "\n".join(("> " if n == line else "  ") + str(n).rjust(w) + " | " + lines[n - 1] for n in range(lo, hi + 1)) + "\n"


def _warn(where: str, e: BaseException) -> None:
    print(f"reporting-labs: {where}: {type(e).__name__}: {e}", file=sys.__stderr__ or sys.stderr)
