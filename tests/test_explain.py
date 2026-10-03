from reporting_labs.core.explain import explain


def k(msg, t=None):
    e = explain(msg, t)
    return (e["kind"], e["summary"]) if e else (None, None)


def test_pytest_status_assert():
    kind, s = k("assert 404 == 200\n +  where 404 = <Response [404]>.status_code", "AssertionError")
    assert kind == "api" and "404" in s and "200" in s


def test_pytest_value_assert():
    kind, s = k("assert 'Welcome' == 'Hello'", "AssertionError")
    assert kind == "assertion" and "Hello" in s and "Welcome" in s


def test_playwright_not_found():
    kind, s = k('Locator.click: Timeout 800ms exceeded.\nCall log:\n  - waiting for locator("#nope")', "TimeoutError")
    assert kind == "not-found" and 'locator("#nope")' in s


def test_playwright_disabled():
    kind, s = k('Locator.click: Timeout 800ms exceeded.\nCall log:\n  - waiting for locator("#dis")\n    - locator resolved to <button disabled>x</button>\n  - element is not enabled', "TimeoutError")
    assert kind == "disabled"


def test_playwright_to_have_text():
    kind, s = k("Locator expected to have text 'Welcome'\nActual value: Hello\nCall log:\n  - LocatorAssertions.to_have_text with timeout 5000ms\n  - waiting for locator(\"h1\")", "AssertionError")
    assert kind == "assertion" and "Welcome" in s and "Hello" in s


def test_playwright_nav_refused():
    kind, s = k('Page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:1/\nCall log:\n  - navigating to "http://localhost:1/"', "Error")
    assert kind == "network" and "nothing is listening" in s


def test_selenium_not_found():
    kind, s = k('NoSuchElementException: Message: no such element: Unable to locate element: {"method":"css selector","selector":"#login"}', "NoSuchElementException")
    assert kind == "not-found" and "#login" in s


def test_selenium_click_intercepted():
    kind, s = k("ElementClickInterceptedException: Message: element click intercepted: Element is not clickable at point (1,2). Other element would receive the click: <div class='overlay'>", "ElementClickInterceptedException")
    assert kind == "blocked"


def test_selenium_stale():
    kind, s = k("StaleElementReferenceException: Message: stale element reference", "StaleElementReferenceException")
    assert kind == "detached"


def test_requests_connection_refused():
    kind, s = k("requests.exceptions.ConnectionError: HTTPConnectionPool(host='127.0.0.1', port=1): Max retries exceeded with url: /x (Caused by NewConnectionError('...: [Errno 111] Connection refused'))", "ConnectionError")
    assert kind == "api" and "nothing is listening" in s


def test_requests_http_error():
    kind, s = k("requests.exceptions.HTTPError: 404 Client Error: Not Found for url: http://x/missing", "HTTPError")
    assert kind == "api" and "404" in s


def test_requests_read_timeout():
    kind, s = k("requests.exceptions.ReadTimeout: HTTPConnectionPool(host='x', port=80): Read timed out. (read timeout=1)", "ReadTimeout")
    assert kind == "api" and "did not answer" in s


def test_robot_element_not_found():
    kind, s = k("Element with locator 'id:nope' not found.", "AssertionError")
    assert kind == "not-found" and "id:nope" in s


def test_robot_setup_failed_unwraps():
    kind, s = k("Setup failed:\nElement with locator 'id:x' not found.", None)
    assert kind == "not-found"


def test_python_key_error():
    kind, s = k("KeyError: 'phone'", "KeyError")
    assert kind == "script" and "phone" in s


def test_python_attribute_error_none():
    kind, s = k("AttributeError: 'NoneType' object has no attribute 'text'", "AttributeError")
    assert kind == "script" and "None" in s


def test_plain_raise():
    kind, s = k("RuntimeError: payment service did not start", "RuntimeError")
    assert kind == "thrown" and "payment service" in s


def test_pytest_timeout():
    kind, s = k("Failed: Timeout (>1.0s) from pytest-timeout.", "Failed")
    assert kind == "test-timeout" and "1.0s" in s


def test_selenium_selector_with_quotes():
    kind, s = k('NoSuchElementException: Message: no such element: Unable to locate element: {"method":"css selector","selector":"[id=\"nope\"]"}', "NoSuchElementException")
    assert kind == "not-found" and '[id="nope"]' in s
