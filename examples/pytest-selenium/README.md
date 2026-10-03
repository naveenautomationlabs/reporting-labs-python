# Selenium + pytest example

```bash
pip install -r requirements.txt
pytest
open reporting-labs/index.html
```

`reporting-labs` is on as soon as it is installed. Every Selenium command (open, find, click, type, run
script…) is a step, with the element named by the locator that found it, and a screenshot of the browser
is attached when a test fails. Selenium 4's Selenium Manager downloads the matching driver automatically.
