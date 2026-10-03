"""Playwright + pytest. Install playwright and pytest-playwright, then:

    pytest --tracing retain-on-failure --video retain-on-failure

Every action, every expect() and a screenshot of a failing page land in the report with no extra code.
"""
import pytest
from playwright.sync_api import Page, expect

from reporting_labs import meta, log, step, test_data


@pytest.mark.meta(priority="P1", owner="asha", feature="login", story="SHOP-12")
def test_login_shows_welcome(page: Page, base_url: str):
    test_data({"username": "demo", "password": "S3cretPw!"}, "Login")
    page.goto(base_url + "/")
    with step("Log in"):
        page.fill("#user", "demo")
        page.fill("#password", "S3cretPw!")   # the value is masked in the report
        page.click("#login")
    log("checking the greeting")
    expect(page.locator("#msg")).to_have_text("Welcome demo")


@pytest.mark.meta(priority="P2", feature="cart")
def test_go_to_cart(page: Page, base_url: str):
    page.goto(base_url + "/")
    page.click("#cart")
    expect(page).to_have_url(base_url + "/cart.html")
    expect(page.locator("#cart-title")).to_have_text("Your cart")


@pytest.mark.meta(priority="P1", feature="checkout")
def test_checkout_is_enabled(page: Page, base_url: str):
    """Fails on purpose, so the report has a failure to explain (the button stays disabled)."""
    page.goto(base_url + "/")
    page.click("#checkout", timeout=1500)
