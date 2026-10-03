# Playwright + pytest example

```bash
pip install -r requirements.txt
playwright install chromium
pytest --tracing retain-on-failure --video retain-on-failure
open reporting-labs/index.html        # run again to see the trend
```

`reporting-labs` is on as soon as it is installed. Nothing to register. Every Playwright action is a
step, every `expect()` is a step, a screenshot of the failing page is attached, and pytest-playwright's
trace and video are attached too. `reporting-labs.config.json` sets the title, project and an env chip.
