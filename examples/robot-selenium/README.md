# Robot Framework + SeleniumLibrary example

```bash
pip install -r requirements.txt
robot --listener reporting_labs.RobotListener tests/
open reporting-labs/index.html
```

Add `--listener reporting_labs.RobotListener` and your suite is in the report: one row per test case,
suites as the path, every keyword a step, setup and teardown as hooks, tags as filters, and the
screenshots SeleniumLibrary embeds in the log attached to the test. Options go after a colon, e.g.
`--listener reporting_labs.RobotListener:title=Checkout:output=reports/rl`.
