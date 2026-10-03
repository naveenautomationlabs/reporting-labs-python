import json
from pathlib import Path

from reporting_labs.core import collector, options as options_mod, render, writer
from reporting_labs.core.model import Attempt, ErrorInfo
from reporting_labs.core import context


def _run(tmp_path, environ=None):
    opts = options_mod.load(tmp_path, environ=environ or {})
    return collector.Run(opts, "pytest", environ=environ or {}), opts


def test_outcomes_and_stats(tmp_path):
    run, opts = _run(tmp_path)
    # passed
    run.test("p", "passes", [], "t.py", 1, "proj")
    a = Attempt("p"); a.finish("passed"); run.add_attempt("p", a)
    # failed
    run.test("f", "fails", [], "t.py", 2, "proj")
    a = Attempt("f"); a.add_error(ErrorInfo("boom", exc_type="RuntimeError")); a.finish("failed"); run.add_attempt("f", a)
    # flaky: fail then pass
    run.test("k", "flaky", [], "t.py", 3, "proj")
    a1 = Attempt("k"); a1.finish("failed"); run.add_attempt("k", a1)
    a2 = Attempt("k"); a2.finish("passed"); run.add_attempt("k", a2)
    # skipped
    run.test("s", "skips", [], "t.py", 4, "proj", forced_outcome="skipped")
    data = run.build()
    by = {t["title"]: t["outcome"] for t in data["tests"]}
    assert by == {"passes": "passed", "fails": "failed", "flaky": "flaky", "skips": "skipped"}
    assert data["stats"] == {"passed": 1, "failed": 1, "flaky": 1, "skipped": 1, "timedOut": 0, "interrupted": 0, "total": 4}
    assert data["runStatus"] == "failed"


def test_steps_logs_data_api_masked(tmp_path):
    run, opts = _run(tmp_path, {"DB_PASSWORD": "Hunter2x9pw"})
    run.test("t", "t", [], "t.py", 1, "proj")
    a = Attempt("t"); context.activate(a)
    st = a.begin_step("Outer")
    a.begin_step("Inner"); a.end_step(a.current_step())
    a.end_step(st)
    a.log("the password is Hunter2x9pw")
    a.test_data({"user": "demo", "password": "x"}, "Login")
    a.api_call({"method": "GET", "url": "/v1", "status": 200, "responseBody": {"token": "abc"}})
    a.finish("passed"); context.deactivate(a); run.add_attempt("t", a)
    r = run.build()["tests"][0]["results"][0]
    assert [s["title"] for s in r["steps"]] == ["Outer"]
    assert r["steps"][0]["steps"][0]["title"] == "Inner"
    assert r["logs"][0]["msg"] == "the password is ****"
    assert r["data"][0] == {"name": "Login", "kind": "kv", "kv": [["user", "demo"], ["password", "****"]]}
    assert r["api"][0]["responseBody"] == {"token": "****"}


def test_history_written_and_rolled(tmp_path):
    for i in range(3):
        run, opts = _run(tmp_path)
        run.test("p", "p", [], "t.py", 1, "proj")
        a = Attempt("p"); a.finish("passed"); run.add_attempt("p", a)
        data = run.build()
    assert len(data["history"]) == 3
    hist = json.loads((tmp_path / "reporting-labs.history.json").read_text())
    assert len(hist) == 3 and hist[-1]["passed"] == 1


def test_render_has_data_and_title(tmp_path):
    run, opts = _run(tmp_path)
    run.test("p", "p", [], "t.py", 1, "proj")
    a = Attempt("p"); a.finish("passed"); run.add_attempt("p", a)
    data = run.build()
    html = render.render(data)
    assert "__RL_DATA__" not in html
    assert '<script id="rl-data"' in html
    assert "<title>" in html


def test_writer_emits_html_and_json(tmp_path):
    run, opts = _run(tmp_path)
    run.test("p", "p", [], "t.py", 1, "proj")
    a = Attempt("p"); a.finish("passed"); run.add_attempt("p", a)
    data = run.build()
    html = writer.write(data, opts)
    assert html.is_file() and html.stat().st_size > 100_000
    assert (opts.out_dir / "report.json").is_file()
