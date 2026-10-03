"""The pytest plugin, exercised with pytest's own `pytester` fixture. Offline, no browser."""
import json
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


def _report(pytester) -> dict:
    out = pytester.path / "reporting-labs" / "report.json"
    assert out.is_file(), "report.json was not written"
    return json.loads(out.read_text())


def _run(pytester, *args):
    return pytester.runpytest_subprocess("-p", "reporting_labs", *args)


def test_outcomes(pytester: pytest.Pytester):
    pytester.makepyfile(
        test_x="""
        import pytest
        from reporting_labs import meta, log

        @pytest.mark.meta(priority="P1", owner="asha")
        def test_pass():
            log("hi")

        def test_fail():
            assert 1 == 2

        def test_skip():
            pytest.skip("later")

        @pytest.mark.xfail(reason="bug")
        def test_xfail():
            assert False
        """
    )
    _run(pytester, "-p", "no:cacheprovider")
    data = _report(pytester)
    by = {t["title"]: t["outcome"] for t in data["tests"]}
    assert by["test_pass"] == "passed"
    assert by["test_fail"] == "failed"
    assert by["test_skip"] == "skipped"
    assert by["test_xfail"] == "passed"
    p = next(t for t in data["tests"] if t["title"] == "test_pass")
    assert p["meta"] == {"priority": "P1", "owner": "asha"}
    assert p["results"][0]["logs"][0]["msg"] == "hi"


def test_failure_has_explanation_and_location(pytester: pytest.Pytester):
    pytester.makepyfile(
        test_y="""
        def test_fail():
            got = 404
            assert got == 200
        """
    )
    _run(pytester, "-p", "no:cacheprovider")
    data = _report(pytester)
    t = data["tests"][0]
    err = t["results"][-1]["errors"][0]
    assert err["explain"]["summary"]
    assert err["location"]["file"].endswith("test_y.py")
    assert err["location"]["line"] == 3


def test_steps_and_test_data(pytester: pytest.Pytester):
    pytester.makepyfile(
        test_s="""
        from reporting_labs import step, test_data
        def test_it():
            with step("Outer"):
                with step("Inner"):
                    pass
            test_data({"user": "demo", "password": "secret"}, "Login")
        """
    )
    _run(pytester, "-p", "no:cacheprovider")
    r = _report(pytester)["tests"][0]["results"][0]
    assert r["steps"][0]["title"] == "Outer"
    assert r["steps"][0]["steps"][0]["title"] == "Inner"
    assert r["data"][0]["kv"] == [["user", "demo"], ["password", "****"]]


def test_stdout_captured_and_masked(pytester: pytest.Pytester):
    pytester.makepyfile(
        test_o="""
        def test_it():
            print("token=abc12345")
            assert False
        """
    )
    _run(pytester, "-p", "no:cacheprovider")
    r = _report(pytester)["tests"][0]["results"][-1]
    assert any("token=****" in s for s in r["stdout"])


def test_html_is_written(pytester: pytest.Pytester):
    pytester.makepyfile(test_h="def test_it(): pass")
    _run(pytester, "-p", "no:cacheprovider")
    html = pytester.path / "reporting-labs" / "index.html"
    assert html.is_file() and b"rl-data" in html.read_bytes()


def test_disabled_writes_nothing(pytester: pytest.Pytester):
    pytester.makepyfile(test_d="def test_it(): pass")
    pytester.runpytest_subprocess("-p", "no:cacheprovider", "--no-rl")
    assert not (pytester.path / "reporting-labs").exists()
