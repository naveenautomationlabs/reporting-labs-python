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

### Meta: two ways, your choice

Meta (priority, owner, feature, story) can be added in **two ways**. Both give **exactly the same report**, so use
whichever you like:

```python
# Way 1: the marker (or meta() inside the test)
@pytest.mark.meta(priority="P0", owner="asha", feature="checkout", story="SHOP-12")
def test_checkout(page):
    ...

# Way 2: the test's docstring, no marker, no import
def test_checkout(page):
    """Places an order with a saved card.

    @priority P0  @owner asha  @feature checkout  @story SHOP-12
    @smoke
    """
    ...
```

- **Already using the marker or `meta()`?** Nothing changes. Docstrings are only an extra option.
- **Mix them freely.** If one test has both, the marker / `meta()` wins.
- `#` comments right above the `def` work too. A **class** docstring applies to every test in the class, the
  **module** docstring at the top of the file to every test in the file.
- A line with only `@words` (`@smoke @regression`) becomes tags; `@P0` sets the priority.
- **Your old docstrings are safe:** a name in a sentence ("reported by @asha") and unknown keys are ignored.
- **Robot Framework:** write it in `[Documentation]`: `@owner naveen    @priority P0`.
- Turn it off with `"commentMeta": false`.

**Don't type it by hand: install the snippets.** In VS Code:

1. In the project folder (virtualenv active), run `python -m reporting_labs snippets`. It creates
   `.vscode/reporting-labs.code-snippets`.
2. Inside a test, type `rlmeta` and press **Tab** for the docstring (or `rltest` for a whole test). Pick the priority
   from the list, then **Tab** to the next field.
3. Commit the `.vscode` file so the whole team gets the snippets.

For PyCharm, see [Install the editor snippets](https://reportinglabs.dev/features/meta-comments#install-the-editor-snippets).

## pytest-bdd

Using pytest-bdd (Gherkin `.feature` files)? Nothing to set up (reporting-labs 0.1.7+): when pytest-bdd is installed,
every scenario reads like a Cucumber report.

- **One row per scenario**, named after it, at its `.feature` file and line, grouped under the feature file.
  A Scenario Outline example is named `Scenario (value1, value2)` and shows its Examples row as a data block.
- **Every Gherkin step** (Background included) as a step: `Given …`, `When …`, `Then …`, with its time. Playwright and
  Selenium actions of a step nest under it.
- **The failing step** carries the error; the steps after it show as *not run*. A step that calls `pytest.skip()`
  skips the scenario, and its remaining steps show as *not run* too.
- **An undefined step** fails the scenario at its `.feature` line, with the lines around it and the step definition
  to write.
- **Data tables and doc strings** of a step become data blocks.
- **Tags:** `@P1` and `@critical` set priority and severity, `@owner:asha` sets the owner, anything else is a tag.
  `meta()` inside a step wins over a tag.
- **The browser** the steps used (pytest-playwright) is the project.

Works with pytest-bdd 6 to 9 (data tables and doc strings need pytest-bdd 8+).

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

All options:

| Option | Default | What it does |
|---|---|---|
| `title` | `"Test report"` | Title in the header |
| `logo` | – | Your logo next to the title: a file next to the config (embedded in the report) or an https URL |
| `project` | – | `{ "name", "version", "team", "url" }` shown under the title |
| `metadata` | `{}` | Chips in the header, e.g. `{ "env": "staging", "build": "#1842" }`. `build` labels the run in the trend |
| `envVar` | – | Name of the variable that holds the environment name, when the detection cannot guess it |
| `env` | `{}` | Extra rows on the Environment card |
| `links` | `{}` | Turn meta values into links: `{ "story": "https://acme.atlassian.net/browse/{id}" }` |
| `maskKeys` | `[]` | Extra keys to mask as `****` |
| `maskValues` | `[]` | Literal values to blank wherever they appear, keyed or not |
| `maskFromEnv` | `true` | Learn the values of sensitive-looking environment variables (`PASSWORD`, `API_TOKEN`) and blank them everywhere |
| `dimensions` | `["priority", "severity", "feature", "owner"]` | Meta keys that get a tab in the Breakdown chart and a filter on the Tests page. Add your own, e.g. `"team"` |
| `dimensionOrder` | P0…P4, blocker…trivial | The order values appear in those charts and filters, e.g. `{ "severity": ["high", "medium", "low"] }` |
| `commentMeta` | `true` | Also read meta from docstrings and `#` comments (`@priority P0 @owner asha`). The marker and `meta()` win when both are there. `false` reads no comments |
| `warnMissingMeta` | `true` | After the run, list the tests that have no meta in the console |
| `widgets` | all on | Hide cards: `{ "tags": false, "timeline": false }` |
| `sections` | `[]` | Extra HTML below the summary, e.g. release notes: `[{ "title": "...", "html": "..." }]` |
| `history` | `{ "enabled": true, "keep": 30 }` | Run history for the trend; `file` sets a custom path |
| `palette` | `"lab"` | `"lab"` (blue), `"ocean"`, `"ember"`, `"mono"` |
| `accent` | palette accent | Your brand color |
| `theme` | `"auto"` | `"light"`, `"dark"` or follow the OS |
| `customCss` | `""` | CSS appended to the report |
| `editorLinks` | on locally, off in CI | "Open in VS Code" links |
| `bdd` | auto | Style Given / When / Then steps as Gherkin |
| `outputFolder` | `"reporting-labs"` | Where the report goes |
| `outputFile` | `"index.html"` | Report file name |
| `embedAttachments` | `true` | Screenshots inside the HTML (one file) |
| `embedLimit` | 2 MB | Bigger attachments are copied to `./assets` |
| `embedVideos` | `false` | Videos inside the HTML too |
| `emitJson` | `true` | Also write `report.json` next to `index.html` |
| `jsonFile` | `"report.json"` | File name of the JSON |
| `pdf` | `true` | Also write a print-ready `report.pdf`. `false` turns it off |
| `pdfFile` | `"report.pdf"` | File name of the PDF |
| `chromePath` | – | The Chrome / Edge / Chromium that prints the PDF, when it is not found on its own (or set `CHROME_PATH`) |
| `embedFonts` | `true` | Bundle the fonts (~140 KB) so the report looks the same offline |
| `announce` | `true` | Print the report path after the run |
| `open` | `"on-failure"` | Open the report in the browser after the run: `"on-failure"`, `"always"` or `"never"`. Never opens in CI |
| `captureApi` | `true` | Record every `requests` / `httpx` call in the API tab |
| `apiMaxBody` | 64 KB | Bytes of a request or response body kept |
| `stepsFromTools` | `true` | Playwright and Selenium actions as steps |

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

Passwords, tokens and card numbers never reach the report. They are replaced with `****` **before** anything is
written, with no setup.

**Where:** logs, request and response bodies, error messages, test data and step titles. Values typed into password
fields with Playwright or Selenium are masked too.

**What it catches:**

| Kind | Examples |
|---|---|
| Passwords and keys | `password=...`, `token`, `api_key`, cookies |
| Auth headers | `Authorization: Bearer …`, `Basic …` |
| Tokens | JWTs, and Stripe, GitHub, AWS, Google, GitLab, npm and SendGrid keys |
| Card numbers | any valid card number (Luhn check) |

**It remembers.** Once a value has been masked (or comes from a `PASSWORD`, `*_TOKEN` or `*_SECRET` environment
variable), it is masked everywhere it shows up later, even with no key around it.

**Add your own:**

```json
{
  "maskKeys": ["otp", "pan"],
  "maskValues": ["a-value-it-cannot-know"],
  "maskFromEnv": true
}
```

`maskKeys` adds key names, `maskValues` exact values; `"maskFromEnv": false` stops learning values from environment
variables.

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
