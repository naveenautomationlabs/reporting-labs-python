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


def test_shell_arg():
    assert collector.shell_arg("tests/test_x.py::test_a") == "tests/test_x.py::test_a"
    assert collector.shell_arg("tests/test_x.py::test_a[1]") == '"tests/test_x.py::test_a[1]"'
    assert collector.shell_arg('a "b" $c') == '"a \\"b\\" \\$c"'


def test_rerun_only_when_a_test_has_one(tmp_path):
    run, opts = _run(tmp_path)
    run.rerun = {"pre": "pytest ", "sep": " "}
    run.test("a", "a", [], "t.py", 1, "proj")
    a = Attempt("a"); a.finish("passed"); run.add_attempt("a", a)
    assert "rerun" not in run.build()
    run.tests["a"].rerun = ["t.py::a"]
    data = run.build()
    assert data["rerun"] == {"pre": "pytest ", "sep": " "} and data["tests"][0]["rerun"] == ["t.py::a"]


def test_star_line_once_a_week_never_in_ci(tmp_path):
    import os, time
    from reporting_labs.core import writer
    mark = tmp_path / "star"
    assert writer.star_line({}, mark) and not writer.star_line({}, mark)       # once, then quiet for a week
    old = time.time() - 8 * 24 * 3600
    os.utime(mark, (old, old))
    assert writer.star_line({}, mark)
    mark.unlink()
    assert writer.star_line({"CI": "true"}, mark) is None and writer.star_line({"REPORTING_LABS_NO_STAR": "1"}, mark) is None
    assert not mark.exists()


def test_browser_events_and_video_start(tmp_path):
    from reporting_labs import transport
    run, opts = _run(tmp_path, {"API_TOKEN": "s3cretTok3n99"})
    run.test("t", "t", [], "t.py", 1, "proj")
    a = Attempt("t")
    a.browser_event("request", "Internal Server Error", "https://shop.test/api?token=s3cretTok3n99", "POST", 500)
    a.browser_event("error", "TypeError: x is undefined", "https://shop.test/cart", stack="TypeError: x is undefined\n    at app.js:1")
    for i in range(60):
        a.browser_event("console", f"noise {i}")
    video = tmp_path / "video.webm"
    video.write_bytes(b"\x1a\x45\xdf\xa3")
    a.attach("video", path=str(video), content_type="video/webm", video_start=a.start + 250)
    a.finish("failed")
    # pytest-xdist hands the attempt over as JSON
    run.add_attempt("t", transport.load(transport.dump(a)))
    r = run.build()["tests"][0]["results"][0]
    assert len(r["browser"]) == 50
    assert r["browser"][0] == {"t": r["browser"][0]["t"], "kind": "request", "text": "Internal Server Error", "url": "https://shop.test/api?token=****", "method": "POST", "status": 500}
    assert r["browser"][1]["stack"].startswith("TypeError")
    assert r["attachments"][0]["videoStart"] == a.start + 250
    assert all("start" in s for s in r["steps"])


def test_no_browser_key_without_events(tmp_path):
    run, opts = _run(tmp_path)
    run.test("t", "t", [], "t.py", 1, "proj")
    a = Attempt("t"); a.finish("passed"); run.add_attempt("t", a)
    assert "browser" not in run.build()["tests"][0]["results"][0]


def test_webm_duration(tmp_path):
    from reporting_labs.playwright_support import webm_duration_ms
    import struct
    # Segment Info with TimecodeScale 1 000 000 ns and Duration 2500.0 (a 4-byte float)
    f = tmp_path / "v.webm"
    f.write_bytes(b"\x1a\x45\xdf\xa3\x80" + b"\x2a\xd7\xb1\x83\x0f\x42\x40" + b"\x44\x89\x84" + struct.pack(">f", 2500.0))
    assert webm_duration_ms(str(f)) == 2500.0
    (tmp_path / "bad.webm").write_bytes(b"nothing")
    assert webm_duration_ms(str(tmp_path / "bad.webm")) == 0.0
    assert webm_duration_ms(str(tmp_path / "missing.webm")) == 0.0
