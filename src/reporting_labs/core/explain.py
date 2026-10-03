"""Turns a raw error into a short, plain-language explanation. Rule based, no network, no AI.

The Playwright rules are a port of src/explain.ts (0.6.9); the Python, requests/httpx, Selenium and Robot
Framework rules are this port's own. The original message is always kept next to the explanation.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

LABELS = {
    "not-found": "Element not found",
    "ambiguous": "Selector matches several elements",
    "not-visible": "Element not visible",
    "blocked": "Element covered by another element",
    "disabled": "Element disabled",
    "detached": "Element disappeared",
    "wrong-element": "Wrong element type",
    "assertion": "Assertion failed",
    "visual": "Screenshot mismatch",
    "navigation": "Page did not load",
    "network": "Site unreachable",
    "api": "API call failed",
    "test-timeout": "Test timed out",
    "hook-timeout": "Hook timed out",
    "closed": "Browser closed early",
    "script": "Error in test code",
    "file": "File not found",
    "thrown": "Test threw an error",
    "undefined-step": "Step has no keyword",
}

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def secs(ms: float) -> str:
    ms = float(ms)
    if ms >= 1000:
        s = ms / 1000
        return (f"{s:.1f}" if ms % 1000 else f"{int(s)}") + "s"
    return f"{int(ms)}ms"


def short(s: str, n: int = 120) -> str:
    s = s or ""
    return s[: n - 1] + "…" if len(s) > n else s


def _pick(msg: str, pattern: str, flags: int = 0) -> Optional[str]:
    m = re.search(pattern, msg, flags)
    return m.group(1) if m else None


def _out(kind: str, summary: str, hint: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {"kind": kind, "label": LABELS[kind], "summary": summary}
    if hint:
        d["hint"] = hint
    for k, v in extra.items():
        if v is not None and v != "":
            d[k] = v
    return d


def explain(message: str, exc_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """`exc_type` is the exception class name when known (AssertionError, TimeoutError, NoSuchElementException...)."""
    msg = _ANSI.sub("", message or "").strip()
    if not msg:
        return None
    first = msg.split("\n", 1)[0].strip()
    t = exc_type or ""

    out = _playwright(msg, first) or _selenium(msg, first, t) or _http(msg, first, t) or _assertion(msg, first, t) or _python(msg, first, t)
    return out or _out("thrown", short(first), "See the full message and stack trace below.")


# ── Playwright (sync and async Python API print the same text as Node) ──────────────────────────────
def _playwright(msg: str, first: str) -> Optional[Dict[str, Any]]:
    locator = _pick(msg, r"(?:waiting for|Locator:\s*|resolved to \d+ elements?:?\s*|locator\(['\"]|)(locator\([^\n]*?\))(?:\s|$)", re.M) \
        or _pick(msg, r"(?:waiting for|Locator:\s*)\s*(get_by_\w+\([^\n]*?\)(?:\.\w+\([^\n]*?\))*)", re.M) \
        or _pick(msg, r"(?:waiting for|Locator:\s*)\s*(getBy\w+\([^\n]*?\)(?:\.\w+\([^\n]*?\))*)", re.M)
    timeout = _pick(msg, r"(?:Timeout|timeout of|Timed out)\s+(\d+)ms", re.I)
    timeout_ms = int(timeout) if timeout else None
    action = _pick(first, r"^(?:Error: |TimeoutError: )?([a-zA-Z_]+\.[a-zA-Z_]+):")
    url = _pick(msg, r"(?:navigating to|at)\s+\"?(https?://[^\s\"]+)")
    t = (" within " + secs(timeout_ms)) if timeout_ms else ""

    m = re.search(r"strict mode violation: (.+?) resolved to (\d+) elements", msg, re.S)
    if m:
        return _out("ambiguous", f"{short(m.group(1).strip())} matched {m.group(2)} elements, Playwright needs exactly one.",
                    "Make the selector more specific, or pick one with .first, .nth(i) or a filter such as has_text.", locator=m.group(1).strip())

    m = re.search(r"expect\((?:locator|page|received|value)\)\.(\w+)(?:\(\w*\))?", msg) or re.search(r"waiting for expect\((?:locator|page)\)\.(\w+)", msg) \
        or re.search(r"(?:LocatorAssertions|PageAssertions|APIResponseAssertions)\.(\w+)", msg)
    if m or re.match(r"^(?:Error: )?expect\(", first) or re.match(r"^(?:Error: )?Timed out \d+ms waiting for expect", first) or re.search(r"\bLocator expected to\b|\bPage expected to\b|\bexpect\(\)\.", msg):
        matcher = m.group(1) if m else None
        expected = (_pick(msg, r"^Expected(?:[^:\n]{0,40})?:[ \t]*(.+)$", re.M) or "").strip() or None
        received = (_pick(msg, r"^(?:Received|Actual value)(?:[^:\n]{0,40})?:[ \t]*(.+)$", re.M) or "").strip() or None
        if not locator:
            locator = _pick(msg, r"waiting for (locator\([^\n]*?\)|get_by_\w+\([^\n]*?\)(?:\.\w+\([^\n]*?\))*)", re.M)
        if expected is None:
            # Python prints the expectation on the first line: "Locator expected to have text 'Welcome'"
            expected = _pick(first, r"expected (?:to |not to )?(?:have|contain|be) \w+ (.+)$")
        not_found = bool(re.search(r"element\(s\) not found|locator resolved to 0 elements|not found", msg, re.I)) and not re.search(r"unexpected value", msg, re.I)
        base = dict(matcher=matcher, locator=locator, timeoutMs=timeout_ms)
        if (matcher and "screenshot" in matcher.lower()) or re.search(r"Screenshot comparison failed|pixels \(ratio [\d.]+ of all image pixels\) are different", msg):
            px = _pick(msg, r"(\d+) pixels \(ratio")
            return _out("visual", f"The page looks different from the baseline: {px} pixels changed." if px else "The page looks different from the baseline screenshot.",
                        "Open the visual comparison below. If the new look is intended, update the baseline.", **base)
        if not_found and locator:
            return _out("not-found", f"{locator} was not on the page{t}, so {matcher or 'the check'} could not run.",
                        "Check the selector, and whether the element is inside an iframe, behind a login, or only shown after a click.", **base)
        if matcher in ("to_be_visible", "toBeVisible", "to_be_hidden", "toBeHidden"):
            want = "visible" if "visible" in matcher.lower() else "hidden"
            return _out("not-visible" if want == "visible" else "assertion",
                        f"{locator or 'The element'} was expected to be {want}{t} but was {received or ('hidden' if want == 'visible' else 'visible')}.",
                        "The element may still be loading, be hidden by CSS, or sit inside a closed menu or dialog." if want == "visible" else "Something kept the element on screen. Check the step that should hide it.", **base)
        if matcher and re.match(r"^to_?have_?url$", matcher, re.I):
            return _out("assertion", f"The page URL was {received or 'different'}, expected {expected or 'another URL'}.",
                        "The navigation may not have happened yet, or it went to a different page (a redirect, a login screen, an error page).", **base)
        if matcher and re.match(r"^to_?have_?count$", matcher, re.I):
            return _out("assertion", f"{locator or 'The selector'} matched {received or 'a different number of'} elements, expected {expected or 'another count'}.",
                        "The list may not have finished loading, or the selector also matches other elements.", **base)
        if matcher and re.match(r"^to_?be_?(enabled|disabled|checked|editable|focused|empty|attached|in_?viewport)$", matcher, re.I):
            state = re.sub(r"^to_?be_?", "", matcher, flags=re.I).replace("_", " ").lower()
            return _out("assertion", f"{locator or 'The element'} was not in the expected state ({state})" + (f": it was {received}" if received else "") + ".",
                        "Check the step before this one. The element may still be loading or waiting on a previous action.", **base)
        if expected is not None and received is not None:
            ml = (matcher or "").lower()
            what = "text" if "text" in ml else "value" if "value" in ml else "attribute" if "attribute" in ml else "title" if "title" in ml else "class" if "class" in ml else "value"
            who = f"{locator} had the wrong {what}" if locator else f"The {what} was wrong"
            case_only = expected[:1] in "\"'" and received[:1] in "\"'" and expected.lower() == received.lower()
            return _out("assertion", f"{who}: expected {short(expected, 80)}, got {short(received, 80)}.",
                        "Only the letter case differs. Use ignore_case=True if that is fine." if case_only else "Compare expected and received below. A copy change, a data change or a timing issue are the usual causes.", **base)
        return _out("assertion", f"{'expect().' + matcher + '()' if matcher else 'An expect()'} did not pass" + (f" for {locator}" if locator else "") + ".",
                    "See the full message below for the expected and received values.", **base)

    m = re.search(r"net::(ERR_[A-Z_]+)|NS_ERROR_([A-Z_]+)|Could not connect to server|ECONNREFUSED|ENOTFOUND|EAI_AGAIN|ETIMEDOUT|ECONNRESET|ERR_CERT", msg)
    if m and (action or "net::" in msg or "NS_ERROR" in msg):
        code = (m.group(1) or m.group(2) or m.group(0)).upper()
        reason = _reason(code)
        if action and action.startswith("api_request_context.") or action and action.startswith("apiRequestContext."):
            return _out("api", f"The API request could not be sent: {reason} ({code}).", "Check the base URL and that the API is up. In CI, check that the service started before the tests.", action=action, url=url)
        return _out("network", f"The browser could not reach {url or 'the site'}: {reason} ({code}).",
                    "Check base_url, that the app is running, and VPN or proxy settings. In CI, make sure the web server starts before the tests.", action=action, url=url)
    if action and (action.startswith("api_request_context.") or action.startswith("apiRequestContext.")):
        if re.search(r"Request timed out|Timeout \d+ms exceeded", msg):
            return _out("api", "The API request did not answer" + (f" within {secs(timeout_ms)}" if timeout_ms else " in time") + ".", "The API may be slow or hanging. Check its logs, or raise the request timeout.", action=action, url=url, timeoutMs=timeout_ms)
        return _out("api", f"The API call {action} failed: {short(re.sub(r'^Error: ', '', first))}", "See the full message below and the API tab for the request.", action=action, url=url)
    if action and re.match(r"^(page|frame)\.(goto|reload|go_back|go_forward|wait_for_url|wait_for_load_state|goBack|goForward|waitForURL|waitForLoadState)$", action):
        if re.search(r"Timeout \d+ms exceeded|Navigation timeout", msg, re.I):
            return _out("navigation", f"{url or 'The page'} did not finish loading within {secs(timeout_ms) if timeout_ms else 'the timeout'}.",
                        "The app may be slow, stuck on a request, or redirecting in a loop. Try wait_until='domcontentloaded' if the page keeps long-running requests open.", action=action, url=url, timeoutMs=timeout_ms)
        if "interrupted by another navigation" in msg:
            return _out("navigation", "The page navigated somewhere else while this navigation was in progress.", "A redirect or a click started another navigation. Wait for the final URL instead.", action=action, url=url)
        return _out("navigation", f"{action} failed: {short(re.sub(r'^(Error|TimeoutError): ', '', first))}", "See the full message below.", action=action, url=url)
    if re.search(r"Target page, context or browser has been closed|Target closed|Browser has been closed|Browser closed|browser has disconnected|Page closed|Context closed", msg, re.I):
        return _out("closed", "The browser or page was closed before this step could run.", "A previous step closed it, the test ended early, or the browser crashed. Look at the step just before this one.", action=action)
    if re.search(r"Execution context was destroyed|most likely because of a navigation", msg):
        return _out("detached", "The page navigated away while this step was running.", "Wait for the navigation to finish (page.wait_for_url) before touching the page.", action=action, locator=locator)
    if re.search(r"not attached to the DOM|element was detached|Element is not attached", msg, re.I):
        return _out("detached", f"{locator or 'The element'} was removed from the page while Playwright was using it.", "The UI re-rendered the element. Re-locate it after the change, or wait for the update to finish.", action=action, locator=locator)
    if not action and re.search(r"Timeout \d+ms exceeded", first):
        # Python prints "Timeout 5000ms exceeded." then a call log: "waiting for locator(...)" / "- locator.click: ..." / "navigating to ..."
        action = _pick(msg, r"^\s*-\s*((?:locator|page|frame|element_handle|mouse|keyboard)\.[a-z_]+)", re.M) or ("page.goto" if re.search(r"navigating to", msg) else "action")
        if action == "page.goto":
            return _out("navigation", f"{url or 'The page'} did not finish loading within {secs(timeout_ms) if timeout_ms else 'the timeout'}.",
                        "The app may be slow, stuck on a request, or redirecting in a loop. Try wait_until='domcontentloaded' if the page keeps long-running requests open.", action=action, url=url, timeoutMs=timeout_ms)
    if action and re.search(r"Timeout \d+ms exceeded", msg):
        base = dict(action=action, locator=locator, timeoutMs=timeout_ms)
        t2 = f" for {secs(timeout_ms)}" if timeout_ms else ""
        if "intercepts pointer events" in msg:
            by = _pick(msg, r"\n\s*-?\s*(<[^>]+>)[^\n]*intercepts pointer events")
            return _out("blocked", f"{locator or 'The element'} was there, but {(by + ' ') if by else 'another element '}was covering it, so the {action.split('.')[1]} never landed.",
                        "A modal, cookie banner, toast or loading overlay is on top. Close it first, or wait for it to disappear.", **base)
        if "element is not visible" in msg:
            return _out("not-visible", f"{locator or 'The element'} exists but stayed hidden{t2}.", "It may be inside a closed menu, collapsed section or hidden tab, or hidden by CSS. Open the container first.", **base)
        if re.search(r"element is not enabled|is disabled", msg):
            return _out("disabled", f"{locator or 'The element'} stayed disabled{t2}.", "A form may be invalid or still loading. Fill the required fields or wait for the button to enable.", **base)
        if "element is outside of the viewport" in msg:
            return _out("not-visible", f"{locator or 'The element'} was outside the visible area{t2}.", "Scroll it into view, or check for a fixed layout that keeps it off screen.", **base)
        if re.search(r"not an? <input>|Element is not an", msg):
            return _out("wrong-element", f"{locator or 'The element'} is not the kind of element this action works on.", "For example fill() needs an <input> or <textarea>. Check the selector points at the right element.", **base)
        if "waiting for" in msg and "locator resolved to" not in msg:
            return _out("not-found", f"{locator or 'The element'} was not on the page{t}, so {action} could not run.", "Check the selector. The element may be inside an iframe, behind a login, or only shown after another step.", **base)
        if "waiting for element to be visible, enabled and stable" in msg:
            return _out("not-visible", f"{locator or 'The element'} was found but never became ready (visible, enabled and stable){t}.", "The element may be animating, hidden, or disabled. Wait for the animation or the loading state to finish.", **base)
        return _out("not-found", f"{action} did not complete{t}" + (f" on {locator}" if locator else "") + ".", "See the call log below for what Playwright was waiting on.", **base)
    if action and re.search(r"Element is not an? <input>|not an <input>", msg):
        return _out("wrong-element", f"{locator or 'The element'} is not the kind of element this action works on.", "For example fill() needs an <input> or <textarea>. Check the selector.", action=action, locator=locator)
    if action and re.search(r"did not find some options|Option .* not found", msg):
        return _out("assertion", "select_option could not find the requested option" + (f" in {locator}" if locator else "") + ".", "Check the option value or label. Options may load later than the select element.", action=action, locator=locator)
    return None


def _reason(code: str) -> str:
    if "REFUSED" in code:
        return "nothing is listening on that address"
    if re.search(r"NOT_RESOLVED|ENOTFOUND|EAI_AGAIN|NAME_NOT_RESOLVED", code):
        return "the host name could not be resolved"
    if "CERT" in code or "SSL" in code:
        return "the TLS certificate was rejected"
    if re.search(r"TIMED_OUT|ETIMEDOUT|TIMEOUT", code):
        return "the connection timed out"
    if re.search(r"RESET|ABORTED", code):
        return "the connection was dropped"
    return "the connection failed"


# ── Selenium ────────────────────────────────────────────────────────────────────────────────────────
def _selenium(msg: str, first: str, t: str) -> Optional[Dict[str, Any]]:
    if not (t.endswith("Exception") and ("selenium" in msg.lower() or t in _SELENIUM)) and "selenium" not in msg.lower():
        return None
    loc = _pick(msg, r"Unable to locate element:\s*\{?\"?method\"?:\s*\"?([^\"}\n]+)\"?,\s*\"?selector\"?:\s*\"?([^\"}\n]+)")
    sel = None
    m = re.search(r"\"method\":\s*\"([^\"]+)\",\s*\"selector\":\s*\"([^\"]+)\"", msg) or re.search(r"\{\"?method\"?:\s*\"?([\w ]+)\"?,\s*\"?selector\"?:\s*\"?(.+?)\"?\}", msg)
    if m:
        sel = f"{m.group(1)}: {m.group(2)}"
    kind = t or _pick(first, r"^(\w+Exception)") or ""
    if kind == "NoSuchElementException" or "Unable to locate element" in msg or "no such element" in msg:
        return _out("not-found", f"{sel or 'The element'} was not on the page.", "Check the locator, and whether the element is inside an iframe, behind a login, or only shown after another step. An explicit wait may be needed.", locator=sel)
    if kind == "ElementClickInterceptedException" or "click intercepted" in msg:
        by = _pick(msg, r"Other element would receive the click:\s*(<[^>]+>)")
        return _out("blocked", f"{sel or 'The element'} was there, but " + (f"{by} " if by else "another element ") + "was covering it, so the click never landed.",
                    "A modal, cookie banner, toast or loading overlay is on top. Close it first, or wait for it to disappear.", locator=sel)
    if kind == "ElementNotInteractableException" or "not interactable" in msg:
        return _out("not-visible", f"{sel or 'The element'} exists but could not be used: it is hidden, zero-sized or not yet enabled.", "Wait for it to become visible, scroll it into view, or check that the right element is targeted.", locator=sel)
    if kind == "StaleElementReferenceException" or "stale element reference" in msg:
        return _out("detached", f"{sel or 'The element'} was removed from the page after it was found.", "The UI re-rendered the element. Find it again after the change, or wait for the update to finish.", locator=sel)
    if kind == "TimeoutException":
        detail = _pick(msg, r"Message:\s*(.+)")
        return _out("not-found", "Selenium waited for a condition that never became true." + (" Message: " + short(detail, 100) if detail else ""),
                    "Look at the step just before this one; the page may be slow or the condition wrong.", locator=sel)
    if kind in ("NoSuchWindowException", "NoSuchFrameException") or "no such window" in msg or "no such frame" in msg:
        return _out("closed", "The window or frame the test was using is gone.", "A previous step closed it or switched away. Switch back to the right window or frame first.")
    if kind == "InvalidSelectorException" or "invalid selector" in msg:
        return _out("script", f"The locator is not valid: {short(sel or first, 100)}", "Check the XPath or CSS syntax.", locator=sel)
    if kind == "UnexpectedAlertPresentException" or "unexpected alert open" in msg:
        return _out("blocked", "A browser alert was open, so the step could not run.", "Accept or dismiss the alert first (driver.switch_to.alert).")
    if kind == "NoAlertPresentException":
        return _out("assertion", "No alert was open when the test tried to use one.", "Check the step that should have opened the alert.")
    if kind in ("SessionNotCreatedException", "WebDriverException") and re.search(r"cannot find|not found|executable needs|chrome not reachable|session not created|unknown error", msg, re.I):
        return _out("closed", "The browser could not be started: " + short(re.sub(r"^Message:\s*", "", first), 120),
                    "Check that the browser and its driver are installed and that their versions match.")
    if kind == "InvalidElementStateException":
        return _out("disabled", f"{sel or 'The element'} is in a state that does not allow this action (read-only or disabled).", "Fill the required fields or wait for the element to enable.", locator=sel)
    if kind == "MoveTargetOutOfBoundsException":
        return _out("not-visible", f"{sel or 'The element'} is outside the visible area.", "Scroll it into view first.", locator=sel)
    if kind.endswith("Exception") and "selenium" in msg.lower():
        return _out("thrown", short(re.sub(r"^Message:\s*", "", first), 140), "See the full message and stack trace below.")
    return None


_SELENIUM = {"NoSuchElementException", "ElementClickInterceptedException", "ElementNotInteractableException", "StaleElementReferenceException",
             "TimeoutException", "NoSuchWindowException", "NoSuchFrameException", "InvalidSelectorException", "UnexpectedAlertPresentException",
             "NoAlertPresentException", "SessionNotCreatedException", "WebDriverException", "InvalidElementStateException", "MoveTargetOutOfBoundsException"}


# ── HTTP clients: requests, httpx, urllib ───────────────────────────────────────────────────────────
def _http(msg: str, first: str, t: str) -> Optional[Dict[str, Any]]:
    url = _pick(msg, r"(?:url[:=]\s*|for url:\s*|URL\s+)['\"]?(https?://[^\s'\")]+)") or _pick(msg, r"(https?://[^\s'\")]+)")
    low = (t + " " + first).lower()
    if "connectionrefused" in low.replace(" ", "") or "connection refused" in msg.lower() or "errno 111" in low or "winerror 10061" in low:
        return _out("api", "The API request could not be sent: nothing is listening on that address.", "Check the base URL and that the API is up. In CI, check that the service started before the tests.", url=url)
    if re.search(r"NameResolutionError|Name or service not known|nodename nor servname|getaddrinfo failed|Temporary failure in name resolution|\[Errno -2\]|\[Errno 8\]|ConnectError.*resolve", msg):
        return _out("api", "The API request could not be sent: the host name could not be resolved.", "Check the URL for a typo, and DNS, VPN or proxy settings.", url=url)
    if re.search(r"SSLError|SSLCertVerificationError|CERTIFICATE_VERIFY_FAILED|certificate verify failed|SSL: ", msg) or "ssl" in t.lower():
        return _out("api", "The API request could not be sent: the TLS certificate was rejected.", "The server uses a self-signed or expired certificate. Add it to the trust store, or pass verify=False only for a test environment.", url=url)
    if re.search(r"ReadTimeout|ConnectTimeout|ReadTimeoutError|WriteTimeout|PoolTimeout|timed out", t + " " + msg) and ("http" in low or "requests" in low or "httpx" in low or url):
        return _out("api", "The API request did not answer in time.", "The API may be slow or hanging. Check its logs, or raise the request timeout.", url=url)
    if re.search(r"ConnectionResetError|RemoteDisconnected|Connection aborted|ConnectionError|ConnectError|ProtocolError", t + " " + first) and ("http" in low or "requests" in low or "httpx" in low or url):
        return _out("api", "The API request could not be sent: the connection failed or was dropped.", "Check the base URL and that the API is up. In CI, check that the service started before the tests.", url=url)
    m = re.search(r"(\d{3}) (?:Client|Server) Error: ([^\n]+?) for url: (\S+)", msg)
    if m:
        return _out("api", f"The API returned status {m.group(1)} ({m.group(2).strip()}).", "Check the response body in the API tab; the server usually says why.", url=m.group(3))
    m = re.search(r"(?:Client|Server) error '(\d{3}) ([^']+)' for url '([^']+)'", msg)   # httpx raise_for_status
    if m:
        return _out("api", f"The API returned status {m.group(1)} ({m.group(2).strip()}).", "Check the response body in the API tab; the server usually says why.", url=m.group(3))
    m = re.search(r"HTTP Error (\d{3}): (.+)", first)   # urllib
    if m:
        return _out("api", f"The API returned status {m.group(1)} ({m.group(2).strip()}).", "Check the response body in the API tab; the server usually says why.", url=url)
    if re.search(r"JSONDecodeError|Expecting value: line 1 column 1|Unterminated string|Invalid control character", t + " " + first):
        return _out("api", "The response was not valid JSON.", "It may be an HTML error page, an empty body, or a redirect to a login page. Look at the raw body in the API tab.", url=url)
    return None


# ── Assertions: pytest's assert rewriting, unittest, Robot Framework ───────────────────────────────
def _assertion(msg: str, first: str, t: str) -> Optional[Dict[str, Any]]:
    is_assert = t in ("AssertionError", "AssertionFailed") or first.startswith("AssertionError") or first.startswith("assert ") or t.endswith("AssertionError")
    if not is_assert:
        return None
    body = re.sub(r"^AssertionError:?\s*", "", msg).strip()
    bfirst = body.split("\n", 1)[0].strip()
    custom = re.sub(r"\s*\n\s*assert .*$", "", body, flags=re.S).strip() if not bfirst.startswith("assert ") else ""
    # pytest: "<reason>\nassert 404 == 200" or "assert 404 == 200\n +  where ..." or "assert resp.status_code == 200"
    m = re.search(r"^assert (.+?) (==|!=|<=|>=|<|>|in|not in|is|is not) (.+?)$", body, re.M)
    status = re.search(r"\b(status_code|status|statusCode)\b", body)
    if m:
        left, op, right = m.group(1).strip(), m.group(2), m.group(3).strip()
        # the "where" lines carry the evaluated values: "+  where 404 = <Response [404]>.status_code"
        left_v = _pick(body, r"\+\s+where (\S+) = .*?\b" + re.escape(left.split(".")[-1]) + r"\b") if not re.match(r"^[\d'\"\[{(-]", left) else left
        right_v = right if re.match(r"^[\d'\"\[{(-]", right) else _pick(body, r"\+\s+where (\S+) = .*?\b" + re.escape(right.split(".")[-1]) + r"\b")
        lv, rv = left_v or left, right_v or right
        if status and op == "==" and re.match(r"^\d{3}$", lv.strip("'\"")) and re.match(r"^\d{3}$", rv.strip("'\"")):
            return _out("api", f"The API returned status {lv}, the test expected {rv}.", "Check the response body in the API tab; the server usually says why.")
        if op == "==":
            who = short(custom, 80) if custom else ("The value" if re.match(r"^[\d'\"\[{(-]", left) else short(left, 60))
            return _out("assertion", f"{who} was wrong: expected {short(rv, 80)}, got {short(lv, 80)}.", "Compare expected and received below. A copy change, a data change or a timing issue are the usual causes.")
        if op in ("in", "not in"):
            return _out("assertion", f"{short(lv, 60)} was {'not ' if op == 'in' else ''}found in {short(rv, 60)}.", "Check the step just before this assertion.")
        return _out("assertion", short((custom + ": " if custom else "") + f"{lv} {op} {rv} is false", 140), "See the full message below for the values.")
    m = re.match(r"^assert (.+)$", bfirst)
    if m:
        expr = m.group(1).strip()
        if expr in ("False", "not True"):
            return _out("assertion", (short(custom, 100) if custom else "A condition") + " was expected to be true but was false.", "Check the step just before this assertion.")
        return _out("assertion", short((custom + ": " if custom else "") + expr + " was false", 140), "Check the step just before this assertion.")
    # unittest / Robot: "'a' != 'b'", "1 != 2 : reason", "Expected 'x' but got 'y'", "x should be y"
    m = re.match(r"^(.+?) (!=|==) (.+?)(?: : (.+))?$", bfirst)
    if m and m.group(2) == "!=":
        return _out("assertion", (short(m.group(4), 80) + ": " if m.group(4) else "The value was wrong: ") + f"expected {short(m.group(3), 80)}, got {short(m.group(1), 80)}.",
                    "Compare expected and received below.")
    m = re.search(r"Expected (.+?) but (?:got|was|found) (.+?)\.?$", bfirst, re.I)
    if m:
        return _out("assertion", f"The value was wrong: expected {short(m.group(1), 80)}, got {short(m.group(2), 80)}.", "Compare expected and received below.")
    m = re.search(r"^(.+?) should (?:be|equal|contain|have been) (.+?)(?: but (?:was|got|is) (.+?))?\.?$", bfirst, re.I)
    if m:
        return _out("assertion", f"{short(m.group(1), 80)} should be {short(m.group(2), 60)}" + (f", got {short(m.group(3), 60)}" if m.group(3) else "") + ".", "Compare expected and received below.")
    return _out("assertion", "An assertion did not pass." if not bfirst else short(bfirst, 140), "See the full message below for the expected and received values.")


# ── Python ──────────────────────────────────────────────────────────────────────────────────────────
def _python(msg: str, first: str, t: str) -> Optional[Dict[str, Any]]:
    kind = t or _pick(first, r"^(\w+(?:Error|Exception|Failed|Interrupt))\b") or ""
    body = re.sub(r"^\w+(?:Error|Exception):?\s*", "", first).strip()
    if kind in ("Failed",) and re.search(r"Timeout >\s*[\d.]+s", msg):
        secs_ = _pick(msg, r"Timeout >\s*([\d.]+)s")
        return _out("test-timeout", f"The whole test took longer than {secs_}s.", "Find the slow step in the Steps list below. Raise the timeout only if the flow is really that long.", timeoutMs=float(secs_) * 1000 if secs_ else None)
    if "Timeout" in kind and not re.search(r"https?://", msg):
        return _out("test-timeout", short(body or "The test timed out.", 140), "Find the slow step in the Steps list below.")
    if kind in ("FileNotFoundError",) or re.search(r"No such file or directory", msg):
        f = _pick(msg, r"No such file or directory: '([^']+)'")
        return _out("file", "A file the test needs is missing" + (f": {f}" if f else "") + ".", "Check the path, and that the file is committed or generated before the run (a download, a fixture, a data file).")
    if kind in ("KeyError",):
        return _out("script", f"The key {body} was not there.", "If it came from an API response or test data, the shape was not what the test expected. Look at the data in the API tab or the test data block.")
    if kind in ("IndexError",):
        return _out("script", "A list was shorter than the test expected.", "A search returned nothing, or a table had fewer rows than expected.")
    if kind in ("AttributeError",):
        hint = "Something was None at that point: an API response, a fixture, a page object field." if "'NoneType'" in body else "A method is being called on the wrong object, or a helper changed."
        return _out("script", f"{kind} in the test code: {short(body)}", hint)
    if kind in ("TypeError", "NameError", "ValueError", "ImportError", "ModuleNotFoundError", "SyntaxError", "IndentationError", "ZeroDivisionError", "RecursionError", "UnboundLocalError"):
        hint = ("A variable or import is missing." if kind in ("NameError", "ImportError", "ModuleNotFoundError", "UnboundLocalError")
                else "The response was not valid JSON. It may be an HTML error page." if "JSON" in body
                else "This is a bug in the test or a helper, not in the app.")
        return _out("script", f"{kind} in the test code: {short(body)}", hint)
    if kind in ("NotImplementedError",):
        return _out("script", "The test calls something that is not implemented yet.", "Finish the helper, or skip the test until it is.")
    if kind in ("KeyboardInterrupt",):
        return _out("thrown", "The run was interrupted while this test was executing.", None)
    if kind and kind not in ("Exception", "RuntimeError", "Error"):
        return _out("thrown", short((kind + ": " if body else kind) + body, 140), "The test (or a helper) raised this error. The stack trace below points at the line.")
    if body:
        return _out("thrown", short(body, 140), "The test (or a helper) raised this error on purpose or via a failed check. The stack trace below points at the line.")
    return None
