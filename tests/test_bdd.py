"""pytest-bdd scenarios read like a Cucumber JVM run. Offline, no browser. Skipped when pytest-bdd is not installed."""
import json

import pytest

pytest.importorskip("pytest_bdd")
pytest_plugins = ["pytester"]

FEATURE = """\
@smoke @owner:asha
Feature: Login

  Background:
    Given the app is open

  @P1 @critical
  Scenario: Successful login
    When I log in as "admin"
    Then I see the dashboard

  Scenario: Wrong password
    When I log in as "nobody"
    Then I see the dashboard
    And I see my name

  Scenario: Remember me
    When I tick remember me
    Then I see the dashboard

  Scenario: Not built yet
    When the feature is not ready
    Then I see the dashboard

  Scenario Outline: Many users
    When I log in as "<user>"
    Then I see the dashboard

    Examples:
      | user  |
      | admin |
      | eve   |

  @owner:asha
  Scenario: Owner set in code
    When the owner is set in code
    Then I see the dashboard

  Scenario: Table and text
    When I add these items:
      | item  | qty |
      | apple | 2   |
    And I write the note:
      \"\"\"
      Ring twice.
      \"\"\"
    Then I see the dashboard
"""

STEPS = """
import pytest
from pytest_bdd import scenarios, given, when, then, parsers

scenarios("login.feature")

@pytest.fixture
def state():
    return {}

@given("the app is open")
def app_open(state):
    state["open"] = True

@when(parsers.parse('I log in as "{user}"'))
def log_in(state, user):
    state["user"] = user

@when("I add these items:")
def add(state, datatable):
    state["user"] = "admin"

@when("I write the note:")
def note(state, docstring):
    state["note"] = docstring

@when("the feature is not ready")
def not_ready():
    pytest.skip("ships next sprint")

@then("I see the dashboard")
def dashboard(state):
    assert state.get("user") == "admin", "not logged in"

@when("the owner is set in code")
def owner_in_code(state):
    from reporting_labs import meta
    meta(owner="ravi")
    state["user"] = "admin"

@then("I see my name")
def my_name(state):
    pass
"""


def _run(pytester: pytest.Pytester) -> dict:
    pytester.makefile(".feature", login=FEATURE)
    pytester.makepyfile(test_login=STEPS)
    pytester.makeini("[pytest]\nmarkers =\n    smoke\n    critical\n    P1\n    owner:asha\n")
    pytester.runpytest_subprocess("-p", "reporting_labs", "-p", "no:cacheprovider")
    return json.loads((pytester.path / "reporting-labs" / "report.json").read_text())


def _steps(t):
    return [(s["title"], s.get("status") or ("failed" if s.get("error") else "passed")) for s in t["results"][-1]["steps"]]


def test_scenarios_read_like_cucumber(pytester: pytest.Pytester):
    data = _run(pytester)
    by = {t["title"]: t for t in data["tests"]}
    assert set(by) == {"Successful login", "Wrong password", "Remember me", "Not built yet",
                       "Many users (admin)", "Many users (eve)", "Table and text", "Owner set in code"}
    assert data["bdd"] is True

    ok = by["Successful login"]
    assert ok["outcome"] == "passed"
    assert ok["file"].endswith("login.feature") and ok["line"] == 8
    assert ok["path"] == ["login"]
    assert ok["meta"] == {"priority": "P1", "severity": "critical", "owner": "asha"}
    assert "smoke" in ok["tags"]
    assert _steps(ok) == [("Given the app is open", "passed"), ('When I log in as "admin"', "passed"),
                          ("Then I see the dashboard", "passed")]


def test_failure_skips_the_rest(pytester: pytest.Pytester):
    by = {t["title"]: t for t in _run(pytester)["tests"]}
    t = by["Wrong password"]
    assert t["outcome"] == "failed"
    assert _steps(t) == [("Given the app is open", "passed"), ('When I log in as "nobody"', "passed"),
                         ("Then I see the dashboard", "failed"), ("And I see my name", "skipped")]
    assert "not logged in" in t["results"][-1]["errors"][0]["message"]


def test_undefined_step_points_at_the_feature(pytester: pytest.Pytester):
    by = {t["title"]: t for t in _run(pytester)["tests"]}
    t = by["Remember me"]
    assert t["outcome"] == "failed"
    assert _steps(t) == [("Given the app is open", "passed"), ("When I tick remember me", "failed"),
                         ("Then I see the dashboard", "skipped")]
    err = t["results"][-1]["errors"][0]
    assert "is undefined" in err["message"]
    assert err["location"]["file"].endswith("login.feature") and err["location"]["line"] == 18
    assert "> 18 |" in err["snippet"]


def test_skip_inside_a_step(pytester: pytest.Pytester):
    by = {t["title"]: t for t in _run(pytester)["tests"]}
    t = by["Not built yet"]
    assert t["outcome"] == "skipped"
    assert _steps(t) == [("Given the app is open", "passed"), ("When the feature is not ready", "skipped"),
                         ("Then I see the dashboard", "skipped")]


def test_outline_examples_and_step_arguments(pytester: pytest.Pytester):
    by = {t["title"]: t for t in _run(pytester)["tests"]}
    assert by["Many users (admin)"]["outcome"] == "passed"
    assert by["Many users (eve)"]["outcome"] == "failed"
    ex = by["Many users (eve)"]["results"][-1]["data"]
    assert ex[0]["name"] == "Examples" and ex[0]["rows"] == [["eve"]]
    import importlib.metadata as md
    if int(md.version("pytest-bdd").split(".")[0]) < 8:
        return  # data tables and doc strings arrived in pytest-bdd 8
    data = {d["name"]: d for d in by["Table and text"]["results"][-1]["data"]}
    assert data["I add these items:"]["columns"] == ["item", "qty"]
    assert data["I add these items:"]["rows"] == [["apple", "2"]]
    assert data["I write the note:"]["text"] == "Ring twice."


def test_tags_become_meta_and_code_wins(pytester: pytest.Pytester):
    by = {t["title"]: t for t in _run(pytester)["tests"]}
    ok = by["Successful login"]
    assert ok["tags"] == ["smoke"]                       # @P1, @critical, @owner:asha are meta, not tag chips
    assert by["Owner set in code"]["meta"]["owner"] == "ravi"   # meta() in a step wins over @owner:asha
