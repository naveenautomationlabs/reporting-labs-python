# Playwright + Behave example

```bash
pip install -r requirements.txt
playwright install chromium
behave
open reporting-labs/index.html        # run again to see the trend
```

reportingLabs is wired into Behave's own hooks in `features/environment.py`, one line per hook. The step
definitions in `features/steps/` are plain Behave and Playwright: every action and every `expect()` of a step shows
inside that step in the report, a screenshot of the failing page is attached, and the scenario's trace and video
are attached too. `reporting-labs.config.json` sets the title, project and an env chip.

"Checkout is enabled" fails on purpose, so the report has a failure to explain.

Run one scenario again with the command the report shows on it, for example `behave features/shop.feature:19`.
