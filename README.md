# reportingLabs for Python

[![PyPI](https://img.shields.io/pypi/v/reporting-labs.svg?label=PyPI)](https://pypi.org/project/reporting-labs/)
[![Docs](https://img.shields.io/badge/docs-reportinglabs.dev-1A56DB.svg)](https://reportinglabs.dev)
[![Support reportingLabs](https://img.shields.io/badge/%E2%99%A5%20Support-reportingLabs-E5405E?style=flat)](https://reportinglabs.dev/support)

**One beautiful HTML report for pytest, Playwright, Selenium and Robot Framework.** It tells you what broke,
who owns it, and whether it is new. The whole report is a single self-contained HTML file: no server, no
upload, no login. Open it in a browser, attach it to a CI job, or drop it in Slack.

> ♥ **Free and open source, no paid tier.** If reportingLabs saves your team time, [support its development](https://reportinglabs.dev/support) (Razorpay for India, Stripe for everywhere else). A ⭐ on GitHub helps too.

The report is byte-for-byte the same layout as the [Node.js](https://github.com/naveenautomationlabs/reporting-labs)
and [Java](https://github.com/naveenautomationlabs/reporting-labs-java) reporters, so one triage habit works
across a whole company. Nothing from Node is needed at run time: the report is built entirely in Python.

## Install

```bash
pip install reporting-labs
```

That is all. The pytest plugin turns on the moment the package is installed. For Robot Framework, add one
listener flag (below).

## pytest

Run your tests as you always do:

```bash
pytest
open reporting-labs/index.html        # run again to see the trend and flaky history
```

Add detail with a few optional helpers:

```python
import pytest
from reporting_labs import meta, log, test_data, step, api, attach

@pytest.mark.meta(priority="P1", owner="asha", feature="checkout", story="SHOP-231")
def test_checkout(page):
    test_data({"username": "demo", "password": "S3cret"}, "Login")   # sensitive keys are masked
    log("cart total before coupons: 99.00")
    with step("Apply coupon"):
        ...
```

| What you get | How |
|---|---|
| A row per test: passed, failed, skipped (with the reason), xfail / xpass | automatic |
| Flaky, with every attempt | `pytest-rerunfailures` |
| Timed out | `pytest-timeout` |
| Parallel runs merged into one report | `pytest-xdist` (`-n auto`) |
| Priority, owner, feature charts and filters | `@pytest.mark.meta(...)` or `meta(...)` |
| Every `requests` / `httpx` call in the API tab | automatic |
| Captured stdout / stderr, with secrets masked | automatic |

Turn it off for a run with `-p no:reporting_labs` or `--no-rl`.

## Playwright

Install `pytest-playwright` and write tests as usual. Every action, every `expect()` and a screenshot of the
failing page land in the report with no extra code. pytest-playwright's trace and video are attached too:

```bash
pytest --tracing retain-on-failure --video retain-on-failure
```

The sync and async APIs both work. See `examples/pytest-playwright`.

## Selenium

Install `selenium` and write tests as usual. Every driver command (open, find, click, type, run script,
perform actions, Appium taps) becomes a step, with the element named by the locator that found it, and a
screenshot of the browser is attached when a test fails. No wrappers. See `examples/pytest-selenium`.

## Robot Framework

Add one listener flag:

```bash
robot --listener reporting_labs.RobotListener tests/
```

One row per test case, suites as the path, every keyword a step, setup and teardown as hooks, tags as
filters, and the screenshots SeleniumLibrary or the Browser library embed in the log attached to the test.
Options go after a colon: `--listener reporting_labs.RobotListener:title=Checkout:output=reports/rl`.
See `examples/robot-selenium`.

## Configuration

Every option is optional. Put them in `reporting-labs.config.json` next to where you run, or under
`[tool.reporting-labs]` in `pyproject.toml`. Keys may be written `camelCase` (as in the Node reporter) or
`snake_case`.

```json
{
  "title": "Checkout regression",
  "project": { "name": "ShopLite", "version": "2.4.0", "team": "QA Platform" },
  "metadata": { "env": "local" },
  "logo": "logo.png",
  "palette": "lab",
  "links": { "story": "https://acme.atlassian.net/browse/{id}" },
  "maskKeys": ["otp", "pan"],
  "history": { "enabled": true, "keep": 30 }
}
```

Common options: `title`, `logo`, `accent`, `theme` (`auto` / `light` / `dark`), `palette`
(`lab` / `ocean` / `ember` / `mono`), `outputFolder`, `metadata`, `project`, `env`, `dimensions`,
`links`, `maskKeys`, `maskValues`, `maskFromEnv`, `history`, `open` (`on-failure` / `always` / `never`),
`pdf` (`true` / `false`), `pdfFile`, `chromePath`.

**report.pdf** is printed by Playwright's Chromium if it is installed, otherwise by an installed Chrome, Edge or
Chromium, whatever browser the tests ran on. Name one with `chromePath` or `CHROME_PATH`.

**The environment chip** is found for you from `ENV`, `TEST_ENV`, `APP_ENV`, `TARGET_ENV`,
`CI_ENVIRONMENT_NAME`, or any variable ending in `_ENV`, so a config that says `local` still labels the
pipeline's reports `dev`, `qa`, `stage`. Point it at your own variable with `"envVar": "TARGET"`.

**Runtime overrides**, read from the environment and winning over the config, so CI can label a run without
touching the file: `REPORTING_LABS_METADATA_<KEY>` sets a header chip
(`REPORTING_LABS_METADATA_ENV=qa`), and `REPORTING_LABS_TITLE`, `_THEME`, `_PALETTE`, `_ACCENT`, `_LOGO`
set the matching option.

## Secrets are masked

Passwords, tokens, cookies, auth headers, API keys (Stripe, GitHub, AWS, Google, GitLab, npm, SendGrid),
JWTs and Luhn-valid card numbers are blanked in logs, request and response bodies, error messages, test
data and step titles. A value seen once as a secret (`password=...`, a `PASSWORD` env var, or `maskValues`)
is blanked everywhere it later appears. `maskKeys` adds your own keys; `maskFromEnv` (on by default) learns
the values of `PASSWORD` / `*_TOKEN` / `*_SECRET` environment variables.

## Security & privacy

reportingLabs is a library that runs inside your own test run. There is no reportingLabs server, account, API key, telemetry or licence check.

- **Nothing is sent anywhere.** The reporter makes no network requests of its own; its only traffic is the traffic your tests already make. An opened report makes no external requests either: fonts, scripts and the logo are embedded, so it works offline and behind a firewall. The only exceptions are opt-in (`embedFonts: false`, a logo given as an `https://` URL) or need a click (CI, commit and issue links).
- **Everything stays on your machine:** the report folder (`reporting-labs/` by default) holds `index.html`, `report.json`, `report.pdf` and `assets/`, plus the run history `reporting-labs.history.json` next to your project. Nothing is written anywhere else. Whoever can read your test artifacts can read the report; deleting them deletes the data.
- **Secrets are masked before anything is written:** passwords, tokens, cookies, auth headers, API keys, JWTs and card numbers in logs, API bodies and headers, test data, errors and step titles. Values typed into password fields with Playwright or Selenium are masked too (see [Secrets are masked](#secrets-are-masked)).
- **Screenshots, videos and traces are not masked.** They are images and recordings of the application, so run tests against test data, or turn them off for suites that show real personal data.
- **No required dependencies;** it uses the pytest, Playwright, Selenium, requests, httpx or Robot Framework your project already installs. No install or post-install scripts. MIT licensed.

Full details for security reviewers and client projects, including what is read, what is written and what to tell a client: [reportinglabs.dev/security-privacy](https://reportinglabs.dev/security-privacy). To report a vulnerability, open an issue saying you have a security report (no details) and a private channel will be arranged.

## License

MIT. The report is a file you own; nothing leaves your machine or your CI.
