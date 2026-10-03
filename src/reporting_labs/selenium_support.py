"""Zero-code Selenium support: every command the driver sends (open, click, type, find, switch, script...) is a step
with the element described by the locator that found it, and a screenshot of every live driver is attached when
a test fails. Appium drivers go through the same WebDriver.execute, so taps and swipes are steps too.
"""
from __future__ import annotations

import inspect
import threading
import time
import weakref
from typing import Any, Dict, List, Optional

from .core import context
from .core.model import Attempt, now_ms

_installed = False
_local = threading.local()
_drivers_seen: List[str] = []

# command name -> how it reads in the report; commands not listed are not steps (reads like getText, getAttribute).
STEP_COMMANDS: Dict[str, str] = {
    "get": "open", "goBack": "back", "goForward": "forward", "refresh": "refresh",
    "clickElement": "click", "sendKeysToElement": "type", "clearElement": "clear", "submitElement": "submit",
    "findElement": "find", "findElements": "find all", "findChildElement": "find", "findChildElements": "find all",
    "executeScript": "run script", "executeAsyncScript": "run async script", "w3cExecuteScript": "run script", "w3cExecuteScriptAsync": "run async script",
    "findElementFromShadowRoot": "find", "findElementsFromShadowRoot": "find all",
    "switchToFrame": "switch to frame", "switchToParentFrame": "switch to parent frame", "switchToWindow": "switch to window",
    "newWindow": "new window", "close": "close window", "quit": "quit",
    "setWindowRect": "resize window", "maximizeWindow": "maximize window", "w3cMaximizeWindow": "maximize window", "fullscreenWindow": "fullscreen window", "minimizeWindow": "minimize window",
    "acceptAlert": "accept alert", "w3cAcceptAlert": "accept alert", "dismissAlert": "dismiss alert", "w3cDismissAlert": "dismiss alert", "setAlertValue": "type into alert", "w3cSetAlertValue": "type into alert",
    "actions": "perform actions", "addCookie": "add cookie", "deleteCookie": "delete cookie", "deleteAllCookies": "delete all cookies",
    "uploadFile": "upload file", "setTimeouts": "set timeouts", "print": "print page",
    # Appium
    "touchAction": "touch", "multiAction": "multi touch", "performTouch": "touch", "pressKeyCode": "press key", "hideKeyboard": "hide keyboard",
    "startActivity": "start activity", "background": "background app", "lock": "lock", "unlock": "unlock", "installApp": "install app",
    "terminateApp": "terminate app", "activateApp": "activate app", "setOrientation": "rotate",
}
MAX_VALUE = 80
_SECRET_FIELD = ("password", "passwd", "pwd", "pass", "pw", "secret", "token", "pin", "otp", "cvv")


def _short(v: Any) -> str:
    s = str(v)
    return s if len(s) <= MAX_VALUE else s[: MAX_VALUE - 1] + "…"


def _elements(driver: Any) -> Dict[str, str]:
    return driver.__dict__.setdefault("_rl_elements", {})


def _describe(driver: Any, element_id: Optional[str]) -> str:
    if not element_id:
        return "element"
    return _elements(driver).get(element_id, "element")


def _element_id(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "element" in k.lower():
                return str(v)
    return getattr(obj, "id", None) or getattr(obj, "_id", None)


def _title(driver: Any, command: str, params: Dict[str, Any]) -> Optional[str]:
    verb = STEP_COMMANDS.get(command)
    if verb is None:
        return None
    p = params or {}
    if command == "get":
        return f"open {_short(p.get('url', ''))}"
    if command in ("findElement", "findElements"):
        return f"{verb} {p.get('using', '')}: {_short(p.get('value', ''))}"
    if command in ("findChildElement", "findChildElements", "findElementFromShadowRoot", "findElementsFromShadowRoot"):
        parent = "shadow root" if "ShadowRoot" in command else _describe(driver, _element_id(p.get('id')))
        return f"{verb} {parent} -> {p.get('using', '')}: {_short(p.get('value', ''))}"
    if command == "sendKeysToElement":
        desc = _describe(driver, _element_id(p.get('id')))
        text = "".join(p.get("value") or []) if isinstance(p.get("value"), list) else str(p.get("text") or p.get("value") or "")
        if any(w in desc.lower() for w in _SECRET_FIELD):
            text = "****"
        return f'type "{_short(text)}" into {desc}'
    if command in ("clickElement", "clearElement", "submitElement"):
        return f"{verb} {_describe(driver, _element_id(p.get('id')))}"
    if command in ("executeScript", "executeAsyncScript", "w3cExecuteScript", "w3cExecuteScriptAsync"):
        script = str(p.get("script", "")).strip().replace("\n", " ")
        return f"{verb} {_short(script)}"
    if command == "switchToFrame":
        f = p.get("id")
        if f is None:
            return "switch to default content"
        if isinstance(f, dict):
            return f"switch to frame {_describe(driver, _element_id(f))}"
        return f"switch to frame {f}"
    if command == "switchToWindow":
        return f"switch to window {_short(p.get('handle') or p.get('name') or '')}"
    if command == "newWindow":
        return f"new {p.get('type', 'window')}"
    if command in ("setAlertValue", "w3cSetAlertValue"):
        return f'type "{_short(p.get("text") or p.get("value") or "")}" into alert'
    if command == "actions":
        kinds = []
        for chain in p.get("actions") or []:
            for a in chain.get("actions") or []:
                k = a.get("type")
                if k and k != "pause" and k not in kinds:
                    kinds.append(k)
        return "perform actions" + (": " + ", ".join(kinds[:4]) if kinds else "")
    if command == "setWindowRect":
        return f"resize window {p.get('width')}x{p.get('height')}" if p.get("width") else "move window"
    if command == "addCookie":
        return f"add cookie {(p.get('cookie') or {}).get('name', '')}"
    if command == "deleteCookie":
        return f"delete cookie {p.get('name', '')}"
    return verb


def _remember_driver(attempt: Attempt, driver: Any) -> None:
    drivers: List[Any] = attempt.__dict__.setdefault("_rl_drivers", [])
    if not any(d() is driver for d in drivers):
        drivers.append(weakref.ref(driver))
    try:
        caps = driver.capabilities or {}
        if caps.get("browserName"):
            name = f"{caps['browserName']} {caps.get('browserVersion') or caps.get('version') or ''}".strip()
            if name not in _drivers_seen:
                _drivers_seen.append(name)
    except Exception:
        pass


def install(opts: Any = None) -> bool:
    global _installed
    if _installed:
        return True
    try:
        from selenium.webdriver.remote.webdriver import WebDriver
    except ImportError:
        return False
    original = WebDriver.execute

    def execute(self: Any, driver_command: str, params: Optional[Dict[str, Any]] = None) -> Any:
        attempt = context.current()
        if attempt is None or getattr(_local, "busy", False):
            return original(self, driver_command, params)
        _remember_driver(attempt, self)
        title = _title(self, driver_command, params or {})
        start = now_ms()
        _local.busy = True
        try:
            result = original(self, driver_command, params)
        except BaseException as e:
            _local.busy = False
            if title:
                attempt.record_step(title, "selenium", start, now_ms() - start, f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}")
            raise
        _local.busy = False
        if driver_command in ("findElement", "findChildElement", "findElements", "findChildElements", "findElementFromShadowRoot", "findElementsFromShadowRoot"):
            _remember_elements(self, driver_command, params or {}, result)
        if title and driver_command != "quit":
            attempt.record_step(title, "selenium", start, now_ms() - start)
        if driver_command == "quit":
            attempt.record_step("quit", "selenium", start, now_ms() - start)
        return result

    execute._rl_wrapped = True  # type: ignore[attr-defined]
    WebDriver.execute = execute  # type: ignore[assignment]
    _installed = True
    return True


def _remember_elements(driver: Any, command: str, params: Dict[str, Any], result: Any) -> None:
    """Map each found element id to the locator chain that found it, so later steps can name the element."""
    value = (result or {}).get("value") if isinstance(result, dict) else None
    desc = f"{params.get('using', '')}: {params.get('value', '')}"
    if command in ("findChildElement", "findChildElements"):
        desc = f"{_describe(driver, _element_id(params.get('id')))} -> {desc}"
    elif "ShadowRoot" in command:
        desc = f"shadow root -> {desc}"
    table = _elements(driver)
    found = value if isinstance(value, list) else [value]
    for i, el in enumerate(found):
        eid = _element_id(el) if not hasattr(el, "id") else el.id
        if eid:
            table[eid] = desc if len(found) == 1 else f"{desc} [{i}]"
    if len(table) > 2000:
        for k in list(table)[:1000]:
            table.pop(k, None)


def live_drivers(attempt: Attempt) -> List[Any]:
    out = []
    for ref in attempt.__dict__.get("_rl_drivers", []):
        d = ref()
        if d is not None and getattr(d, "session_id", None):
            out.append(d)
    return out


def on_failure(item: Any, attempt: Attempt) -> None:
    for i, driver in enumerate(live_drivers(attempt)):
        _local.busy = True
        try:
            png = driver.get_screenshot_as_png()
            name = "screenshot" if i == 0 else f"screenshot {i + 1}"
            attempt.attach(name, png, "image/png")
            try:
                attempt.log(f"{name}: {driver.current_url}")
            except Exception:
                pass
        except Exception:
            pass
        finally:
            _local.busy = False


def after_teardown(item: Any, attempt: Attempt) -> None:
    return None


def env_rows() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    try:
        from importlib.metadata import version
        rows.append({"k": "Selenium", "v": version("selenium")})
    except Exception:
        pass
    if _drivers_seen:
        rows.append({"k": "Browsers", "v": ", ".join(_drivers_seen)})
    return rows
