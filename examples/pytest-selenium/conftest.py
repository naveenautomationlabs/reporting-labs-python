"""A local site plus a headless Chrome driver, so the example runs offline."""
import functools
import http.server
import threading
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

SITE = Path(__file__).parent / "site"
BASE = "http://127.0.0.1:8798"


@pytest.fixture(scope="session", autouse=True)
def _site():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 8798), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield
    httpd.shutdown()


@pytest.fixture
def driver():
    opts = Options()
    for a in ("--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"):
        opts.add_argument(a)
    d = webdriver.Chrome(options=opts)   # Selenium Manager fetches the right driver
    d.implicitly_wait(2)
    yield d
    d.quit()


@pytest.fixture(scope="session")
def base_url():
    return BASE
