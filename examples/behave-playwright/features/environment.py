"""Behave hooks: a local site for the example, a Playwright browser, and reportingLabs.

The reportingLabs part is one line in each hook. Keep the order in after_scenario: the report first (it takes the
screenshot of a failing page while the page is still open), then close the browser context. Passing the context to
after_scenario, as here, closes it for you and adds its trace and video to the report."""
import functools
import http.server
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from reporting_labs.behave import ReportingLabs

SITE = Path(__file__).resolve().parent.parent / "site"


def before_all(context):
    context.rl = ReportingLabs()                       # options come from reporting-labs.config.json
    # a tiny local site, so the example runs offline
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    context.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 8798), handler)
    threading.Thread(target=context.httpd.serve_forever, daemon=True).start()
    context.base_url = "http://127.0.0.1:8798"
    context.playwright = sync_playwright().start()
    context.browser = context.playwright.chromium.launch()


def before_scenario(context, scenario):
    context.rl.before_scenario(scenario)
    context.browser_context = context.browser.new_context(record_video_dir="test-results/videos")
    context.browser_context.tracing.start(screenshots=True, snapshots=True)
    context.page = context.browser_context.new_page()


def before_step(context, step):
    context.rl.before_step(step)


def after_step(context, step):
    context.rl.after_step(step)


def after_scenario(context, scenario):
    # screenshot of a failing page, the trace when it failed, the video; then closes the browser context
    context.rl.after_scenario(scenario, browser_context=context.browser_context)


def after_all(context):
    context.browser.close()
    context.playwright.stop()
    context.httpd.shutdown()
    context.rl.after_all()                             # writes reporting-labs/index.html
