"""Behave scenarios through reporting_labs.behave read like a Cucumber run, without pytest in the picture.
Offline, no browser: Behave runs in a subprocess on generated files. Skipped when Behave is not installed."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

behave = pytest.importorskip("behave")

FEATURE = """\
@owner:asha
Feature: Login
  Signing in to the shop.

  Background:
    Given the app is open

  @P1 @critical @smoke
  Scenario: Successful login
    When I log in as "admin"
    Then I see the dashboard

  Scenario: Wrong password
    When I log in as "nobody"
    Then I see the dashboard
    And I see my name

  Scenario: Server error
    When the server breaks
    Then I see the dashboard

  Scenario: Not built yet
    When the feature is not ready
    Then I see the dashboard

  @wip
  Scenario: Skipped in a hook
    When I log in as "admin"

  Scenario: Data from the step
    Given these users
      | name  | role  |
      | asha  | admin |
      | priya | qa    |
    And this note
      \"\"\"
      Remember the coupon.
      \"\"\"
    When I log in as "asha"

  Scenario Outline: Log in as <user>
    When I log in as "<user>"
    Then I see the dashboard

    Examples:
      | user  |
      | admin |

  Scenario Outline: Many users
    When I log in as "<user>"

    Examples:
      | user  |
      | priya |
"""

STEPS = """\
import reporting_labs as rl
from behave import given, when, then


@given("the app is open")
def app_open(context):
    context.user = None


@given("these users")
def users(context):
    context.users = [r["name"] for r in context.table]


@given("this note")
def note(context):
    with rl.step("Read the note"):
        context.note = context.text
    rl.attach("note.txt", context.text, "text/plain")


@when('I log in as "{user}"')
def log_in(context, user):
    rl.log("logging in as " + user)
    context.user = user


@when("the server breaks")
def server_breaks(context):
    raise ValueError("connection reset by the server")


@then("I see the dashboard")
def dashboard(context):
    assert context.user in ("admin", "asha", "priya"), "expected the dashboard, got the login page"


@then("I see my name")
def my_name(context):
    pass
"""

ENVIRONMENT = """\
from reporting_labs.behave import ReportingLabs


def before_all(context):
    context.rl = ReportingLabs(title="Behave suite", open="never", pdf=False)


def before_scenario(context, scenario):
    context.rl.before_scenario(scenario)
    if "wip" in scenario.effective_tags:
        scenario.skip("not ready yet")


def before_step(context, step):
    context.rl.before_step(step)


def after_step(context, step):
    context.rl.after_step(step)


def after_scenario(context, scenario):
    context.rl.after_scenario(scenario)


def after_all(context):
    context.rl.after_all()
"""


# Rule: blocks came in Behave 1.2.7
HAS_RULE = tuple(int(x) for x in behave.__version__.split(".")[:3] if x.isdigit()) >= (1, 2, 7)

RULE_FEATURE = """\
Feature: Checkout

  Rule: Guests can pay

    Scenario: Guest pays by card
      When I log in as "admin"
"""


@pytest.fixture(scope="module")
def report(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("behave")
    (root / "features" / "steps").mkdir(parents=True)
    (root / "features" / "login.feature").write_text(FEATURE)
    (root / "features" / "steps" / "login_steps.py").write_text(STEPS)
    (root / "features" / "environment.py").write_text(ENVIRONMENT)
    if HAS_RULE:
        (root / "features" / "rules.feature").write_text(RULE_FEATURE)
    # no --no-capture: as most people run it, so the "report written" line must get past Behave's capture
    run = subprocess.run([sys.executable, "-m", "behave", "-f", "plain"], cwd=root, capture_output=True, text=True, timeout=120)
    out = root / "reporting-labs" / "report.json"
    assert out.is_file(), run.stdout + run.stderr
    data = json.loads(out.read_text())
    data["_stdout"] = run.stdout
    return data


def by_title(report: dict) -> dict:
    return {t["title"]: t for t in report["tests"]}


def steps(t: dict) -> list:
    return t["results"][-1]["steps"]


def test_scenarios_at_their_feature_line(report):
    t = by_title(report)["Successful login"]
    assert report["bdd"] is True
    assert t["outcome"] == "passed"
    assert t["file"] == "features/login.feature" and t["line"] == 9
    assert t["path"] == ["Login"]
    assert t["rerun"] == ["features/login.feature:9"]
    assert report["rerun"]["pre"] == "behave "
    assert [s["title"] for s in steps(t)] == ["Given the app is open", 'When I log in as "admin"', "Then I see the dashboard"]
    assert any(r["k"] == "Behave" for r in report["env"])
    assert "report written to" in report["_stdout"]


def test_tags_become_meta(report):
    t = by_title(report)["Successful login"]
    assert t["meta"].get("priority") == "P1" and t["meta"].get("severity") == "critical" and t["meta"].get("owner") == "asha"
    assert "smoke" in t["tags"] and not any(x.lower() in ("p1", "critical") for x in t["tags"])


def test_failed_assertion_and_the_steps_after_it(report):
    t = by_title(report)["Wrong password"]
    assert t["outcome"] == "failed"
    err = t["results"][-1]["errors"][0]
    assert "expected the dashboard, got the login page" in err["message"] and not err["message"].startswith("ASSERT FAILED")
    assert err["location"]["file"].endswith("login.feature") and err["location"]["line"] == 15
    assert "> 15 |" in (err.get("snippet") or "")
    st = steps(t)
    assert st[2]["title"] == "Then I see the dashboard" and st[2].get("error")
    assert st[3]["title"] == "And I see my name" and st[3].get("status") == "skipped"


def test_exception_in_a_step(report):
    err = by_title(report)["Server error"]["results"][-1]["errors"][0]
    assert err["message"].startswith("ValueError: connection reset by the server")
    step = next(s for s in steps(by_title(report)["Server error"]) if s["title"] == "When the server breaks")
    assert step["error"].startswith("ValueError: connection reset")      # without Behave's "ERROR: " prefix


def test_undefined_step(report):
    t = by_title(report)["Not built yet"]
    assert t["outcome"] == "failed"
    err = t["results"][-1]["errors"][0]
    assert "is undefined" in err["message"] and '@when("the feature is not ready")' in err["message"]
    assert err["location"]["line"] == 23
    st = steps(t)
    assert st[1]["title"] == "When the feature is not ready" and st[1].get("error")
    assert st[2].get("status") == "skipped"


def test_skipped_in_a_hook(report):
    t = by_title(report)["Skipped in a hook"]
    assert t["outcome"] == "skipped"
    assert {"type": "skip", "description": "not ready yet"} in t.get("annotations", [])


@pytest.mark.skipif(not HAS_RULE, reason="Rule: needs Behave 1.2.7+")
def test_rule_is_in_the_path(report):
    t = by_title(report)["Guest pays by card"]
    assert t["path"] == ["Checkout", "Guests can pay"] and t["outcome"] == "passed"


def test_steps_and_attachments_from_step_code(report):
    t = by_title(report)["Data from the step"]
    note = next(s for s in steps(t) if s["title"] == "And this note")
    assert [s["title"] for s in note["steps"]] == ["Read the note"]
    assert any(a["name"] == "note.txt" for a in t["results"][-1]["attachments"])


def test_data_tables_doc_strings_and_logs(report):
    t = by_title(report)["Data from the step"]
    names = [b["name"] for b in t["results"][-1]["data"]]
    assert "these users" in names and "this note" in names
    table = next(b for b in t["results"][-1]["data"] if b["name"] == "these users")
    assert "asha" in json.dumps(table)
    assert any("logging in as asha" in l["msg"] for l in t["results"][-1]["logs"])


def test_outline_rows(report):
    tests = by_title(report)
    assert "Log in as admin" in tests                       # the name had a <placeholder>
    assert "Many users (priya)" in tests                    # no placeholder: the values are added, as in pytest-bdd
    data = tests["Many users (priya)"]["results"][-1]["data"]
    assert data and data[0]["name"] == "Examples"


def test_stats(report):
    s = report["stats"]
    assert (s["passed"], s["failed"], s["skipped"]) == (4 + (1 if HAS_RULE else 0), 3, 1)


def test_no_pytest_needed():
    out = subprocess.run([sys.executable, "-c", "import sys, reporting_labs.behave; print('pytest' in sys.modules)"],
                         capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "False", out.stderr


PW_FEATURE = """\
Feature: Cart

  Scenario: Total after a coupon
    Given the cart page
    When I apply the coupon "SAVE10"
    Then the total is "$89.91"

  Scenario: Pays in a popup
    Given the cart page
    When I pay in a popup
    Then the total is "$99.90"
"""

PW_STEPS = """\
from behave import given, when, then
from playwright.sync_api import expect


@given("the cart page")
def cart(context):
    context.page.set_content('<input placeholder="Coupon code"> <button>Apply</button> <b id=total>$99.90</b>')


@when('I apply the coupon "{code}"')
def apply(context, code):
    context.page.get_by_placeholder("Coupon code").fill(code)
    context.page.get_by_role("button", name="Apply").click()


@then('the total is "{total}"')
def total(context, total):
    expect(context.page.locator("#total")).to_have_text(total, timeout=1000)


@when("I pay in a popup")
def pay_in_popup(context):
    context.page.wait_for_timeout(600)
    with context.page.expect_popup() as info:
        context.page.evaluate("() => { window.open('about:blank'); }")
    popup = info.value
    popup.set_content("<button>Pay</button>")
    popup.get_by_role("button", name="Pay").click()
    popup.wait_for_timeout(600)
    popup.close()
"""

PW_ENVIRONMENT = """\
from playwright.sync_api import sync_playwright
from reporting_labs.behave import ReportingLabs


def before_all(context):
    context.rl = ReportingLabs(open="never", pdf=False)
    context.pw = sync_playwright().start()
    context.browser = context.pw.chromium.launch()


def before_scenario(context, scenario):
    context.rl.before_scenario(scenario)
    context.bctx = context.browser.new_context(record_video_dir="videos")
    context.bctx.tracing.start(screenshots=True, snapshots=True)
    context.page = context.bctx.new_page()


def before_step(context, step):
    context.rl.before_step(step)


def after_step(context, step):
    context.rl.after_step(step)


def after_scenario(context, scenario):
    context.rl.after_scenario(scenario, browser_context=context.bctx)


def after_all(context):
    context.browser.close()
    context.pw.stop()
    context.rl.after_all()
"""


def _chromium_runs() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


def test_playwright_steps_screenshot_trace_and_video(tmp_path):
    if not _chromium_runs():
        pytest.skip("Playwright with Chromium is not available")
    (tmp_path / "features" / "steps").mkdir(parents=True)
    (tmp_path / "features" / "cart.feature").write_text(PW_FEATURE)
    (tmp_path / "features" / "steps" / "cart_steps.py").write_text(PW_STEPS)
    (tmp_path / "features" / "environment.py").write_text(PW_ENVIRONMENT)
    run = subprocess.run([sys.executable, "-m", "behave", "--no-capture", "-f", "plain"], cwd=tmp_path, capture_output=True, text=True, timeout=180)
    out = tmp_path / "reporting-labs" / "report.json"
    assert out.is_file(), run.stdout + run.stderr
    tests = {x["title"]: x for x in json.loads(out.read_text())["tests"]}
    t = tests["Total after a coupon"]
    r = t["results"][-1]
    assert t["outcome"] == "failed"
    when = next(s for s in r["steps"] if s["title"].startswith("When I apply"))
    assert [s["category"] for s in when["steps"]] == ["pw:api", "pw:api"]    # fill and click, inside the Gherkin step
    then = next(s for s in r["steps"] if s["title"].startswith("Then the total"))
    assert then.get("error") and then["steps"] and then["steps"][0]["category"] == "expect"
    names = [a["name"] for a in r["attachments"]]
    assert "screenshot" in names and "trace" in names and "video" in names
    video = next(a for a in r["attachments"] if a["name"] == "video")
    assert video.get("videoStart")                          # plays in step with the steps
    # a popup closed mid-scenario keeps its own video, starting when it opened
    popup = tests["Pays in a popup"]
    assert popup["outcome"] == "passed"
    vids = [a for a in popup["results"][-1]["attachments"] if a["name"] == "video"]
    assert len(vids) == 2 and all(v.get("videoStart") for v in vids)
    assert vids[1]["videoStart"] - vids[0]["videoStart"] > 300
