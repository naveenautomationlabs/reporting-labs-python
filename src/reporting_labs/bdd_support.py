"""pytest-bdd: a scenario reads in the report like a Cucumber JVM run.

    Feature: Login
      @smoke @P1
      Scenario: Successful login            <- the test's title, listed under login.feature:<line>
        Given the login page is open        <- a step, with its time and status
        When I log in as "admin"            <-   Playwright actions of the step nest under it
        Then I see the dashboard            <- the failing step carries the error
        And I see my name                   <- not run after a failure: grey, skipped

Same rules as the Cucumber JVM plugin of the Java reporter:
- one row per scenario, named after it, at the .feature file and line, grouped under the feature file's name;
  a Scenario Outline example is named "Scenario (value1, value2)" and gets its row as an "Examples" data block
- Background and scenario steps as "Keyword text" steps; a data table or a doc string of a step becomes a data block
- steps after a failure, or after a step that skips the scenario, are shown as skipped
- a step with no step definition fails the scenario at its .feature line, with the lines around it
- tags: @P1 / @critical set priority and severity, @owner:asha sets the owner, anything else is a tag
  (pytest-bdd turns tags into pytest markers, which the plugin already reads)

Works with pytest-bdd 6 to 9. Installed by the pytest plugin only when pytest-bdd is importable. Every hook is guarded:
a problem in the report must never fail a test.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import pytest

from .core import context
from .core.model import Step, now_ms


def installed() -> bool:
    try:
        import pytest_bdd  # noqa: F401
        return True
    except Exception:
        return False


def template_of(fn: Any) -> Any:
    """The ScenarioTemplate behind a pytest-bdd test function, or None for any other test."""
    if fn is None:
        return None
    t = getattr(fn, "__scenario__", None)                   # pytest-bdd up to 7
    if t is not None:
        return t
    try:
        # pytest-bdd 8+: a registry keyed by the test function. Import the module by name: `from pytest_bdd import
        # scenario` would give the scenario() decorator, not the module.
        import importlib
        reg = getattr(importlib.import_module("pytest_bdd.scenario"), "scenario_wrapper_template_registry", None)
        if reg is not None:
            return reg.get(fn)
    except Exception:
        pass
    return None


def _example(item: Any) -> Dict[str, str]:
    """The Examples row of a Scenario Outline test, else {}."""
    try:
        ex = item.callspec.params.get("_pytest_bdd_example")
        return {str(k): str(v) for k, v in ex.items()} if isinstance(ex, dict) else {}
    except Exception:
        return {}


def _feature_file(feature: Any) -> str:
    return str(getattr(feature, "rel_filename", None) or getattr(feature, "filename", None) or "").replace("\\", "/")


def item_info(item: Any) -> Optional[Dict[str, Any]]:
    """Title, .feature file, line and group for a pytest-bdd test; None for an ordinary test."""
    tpl = template_of(getattr(item, "obj", None))
    if tpl is None:
        return None
    ran = getattr(item, "_rl_bdd", None) or {}
    ex = _example(item)
    name = str(getattr(tpl, "name", "") or "").strip()
    try:
        if ex and hasattr(tpl, "render"):
            name = str(tpl.render(ex).name or name).strip()     # <placeholders> in the outline's name filled in
    except Exception:
        pass
    if not name:
        return None
    if ex:
        vals = ", ".join(ex.values())
        name += " (" + (vals[:60] + "…" if len(vals) > 60 else vals) + ")"
    feature = getattr(tpl, "feature", None)
    file = _feature_file(feature)
    out: Dict[str, Any] = {"title": name, "line": int(getattr(tpl, "line_number", 0) or 0)}
    if file:
        out["file"] = file
        base = file.rsplit("/", 1)[-1]
        out["path"] = [base[:-8] if base.endswith(".feature") else base]
    if ran.get("project"):
        out["project"] = ran["project"]
    return out


def _attempt(request: Any) -> Any:
    node = getattr(request, "node", None)
    return getattr(node, "_rl_attempt", None) or context.current()


def _title(step: Any) -> str:
    kw = str(getattr(step, "keyword", "") or getattr(step, "type", "") or "").strip()
    return (kw[:1].upper() + kw[1:] + " " if kw else "") + str(getattr(step, "name", "") or "")


def _table(datatable: Any) -> Optional[List[List[str]]]:
    try:
        rows = datatable.raw() if hasattr(datatable, "raw") else datatable
        return [[str(c) for c in r] for r in rows] if rows else None
    except Exception:
        return None


def _snippet(path: str, line: int) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as f:
            ls = f.read().splitlines()
    except Exception:
        return None
    if line <= 0 or line > len(ls):
        return None
    lo, hi = max(1, line - 3), min(len(ls), line + 3)
    w = len(str(hi))
    return "\n".join(("> " if n == line else "  ") + str(n).rjust(w) + " | " + ls[n - 1] for n in range(lo, hi + 1)) + "\n"


class BddHooks:
    """Registered next to the pytest plugin's runtime, in every process that runs tests."""

    @pytest.hookimpl(optionalhook=True)
    def pytest_bdd_before_scenario(self, request: Any, feature: Any, scenario: Any) -> None:
        try:
            node = request.node
            node._rl_bdd = {"scenario": scenario, "feature": feature, "started": -1, "open": None}
            attempt = _attempt(request)
            ex = _example(node)
            if attempt is not None and ex:
                attempt.test_data([ex], "Examples")
        except Exception:
            pass

    @pytest.hookimpl(optionalhook=True)
    def pytest_bdd_before_step(self, request: Any, feature: Any, scenario: Any, step: Any, step_func: Any) -> None:
        try:
            attempt = _attempt(request)
            st_ = getattr(request.node, "_rl_bdd", None)
            if attempt is None or st_ is None:
                return
            st_["started"] = _index(scenario, step, st_["started"])
            st_["open"] = attempt.begin_step(_title(step), "test.step")
            rows = _table(getattr(step, "datatable", None))
            if rows and len(rows) > 1:
                attempt.test_data([dict(zip(rows[0], r + [""] * (len(rows[0]) - len(r)))) for r in rows[1:]], str(step.name))
            elif rows:
                attempt.test_data(" | ".join(rows[0]), str(step.name))
            doc = getattr(step, "docstring", None)
            if doc is not None:
                attempt.test_data(str(doc), str(step.name))
        except Exception:
            pass

    def _end(self, request: Any, error: Optional[str] = None) -> None:
        try:
            attempt = _attempt(request)
            st_ = getattr(request.node, "_rl_bdd", None)
            if attempt is None or st_ is None or st_["open"] is None:
                return
            attempt.end_step(st_["open"], error)
            st_["open"] = None
            if error:
                st_["failed"] = True
        except Exception:
            pass

    @pytest.hookimpl(optionalhook=True)
    def pytest_bdd_after_step(self, request: Any, feature: Any, scenario: Any, step: Any, step_func: Any, step_func_args: Any) -> None:
        self._end(request)

    @pytest.hookimpl(optionalhook=True)
    def pytest_bdd_step_error(self, request: Any, feature: Any, scenario: Any, step: Any, step_func: Any, step_func_args: Any, exception: BaseException) -> None:
        lines = str(exception).strip().splitlines()
        msg = lines[0] if lines else ""
        name = type(exception).__name__
        self._end(request, f"{name}: {msg}" if msg and not msg.startswith(name) else (msg or name))

    @pytest.hookimpl(optionalhook=True)
    def pytest_bdd_step_func_lookup_error(self, request: Any, feature: Any, scenario: Any, step: Any, exception: BaseException) -> None:
        try:
            attempt = _attempt(request)
            st_ = getattr(request.node, "_rl_bdd", None)
            if attempt is None or st_ is None:
                return
            st_["started"] = _index(scenario, step, st_["started"])
            msg = (f"The step '{_title(step)}' is undefined. Write a step definition for it, "
                   f"e.g. @{str(getattr(step, 'type', 'given') or 'given').lower()}(\"{getattr(step, 'name', '')}\")")
            attempt.record_step(_title(step), "test.step", now_ms(), 0, msg)
            path = str(getattr(feature, "filename", "") or "")
            line = int(getattr(step, "line_number", 0) or 0)
            st_["undefined"] = {"message": msg, "file": path, "line": line, "snippet": _snippet(path, line)}
            st_["failed"] = True
        except Exception:
            pass

    @pytest.hookimpl(optionalhook=True)
    def pytest_bdd_after_scenario(self, request: Any, feature: Any, scenario: Any) -> None:
        """Runs in pytest-bdd's `finally`: close a step that skipped the scenario, list the steps that never ran."""
        try:
            attempt = _attempt(request)
            st_ = getattr(request.node, "_rl_bdd", None)
            if attempt is None or st_ is None:
                return
            if st_["open"] is not None:
                # left open by pytest.skip() inside the step (not an Exception, so no step_error hook)
                s = st_["open"]
                attempt.end_step(s)
                s.status = "skipped"
                st_["open"] = None
            steps = list(getattr(scenario, "steps", None) or [])
            for step in steps[st_["started"] + 1:]:
                attempt.record_step(_title(step), "test.step", now_ms(), 0).status = "skipped"
        except Exception:
            pass
        try:
            # pytest-playwright cannot parametrize a scenario by browser (its steps ask for `page`, the test function
            # does not), so the test id has no [chromium]. Take the browser the steps really used as the project.
            if "browser_name" in request.fixturenames:
                request.node._rl_bdd["project"] = str(request.getfixturevalue("browser_name"))
        except Exception:
            pass


def _index(scenario: Any, step: Any, last: int) -> int:
    steps = list(getattr(scenario, "steps", None) or [])
    for i in range(max(0, last + 1), len(steps)):
        if steps[i] is step:
            return i
    line = getattr(step, "line_number", None)
    for i in range(max(0, last + 1), len(steps)):
        if getattr(steps[i], "line_number", None) == line and getattr(steps[i], "name", None) == getattr(step, "name", None):
            return i
    return last + 1


def adjust_error(item: Any, err: Any, exc: BaseException) -> None:
    """A step with no step definition: point the error at the .feature line, like Cucumber does."""
    try:
        st_ = getattr(item, "_rl_bdd", None) or {}
        und = st_.get("undefined")
        if und and type(exc).__name__ == "StepDefinitionNotFoundError":
            err.message = und["message"]
            err.exc_type = "UndefinedStep"
            if und.get("file"):
                err.location = {"file": und["file"] if os.path.isabs(und["file"]) else os.path.abspath(und["file"]), "line": und["line"], "column": 0}
            if und.get("snippet"):
                err.snippet = und["snippet"]
    except Exception:
        pass
