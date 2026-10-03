"""A tiny local site so the example runs offline, served for the whole test session."""
import functools
import http.server
import threading
from pathlib import Path

import pytest

SITE = Path(__file__).parent / "site"
BASE = "http://127.0.0.1:8799"


@pytest.fixture(scope="session", autouse=True)
def _site():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 8799), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield
    httpd.shutdown()


@pytest.fixture(scope="session")
def base_url():
    return BASE
