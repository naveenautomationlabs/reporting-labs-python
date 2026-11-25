"""Plain Behave steps with Playwright. Nothing reportingLabs-specific is needed here: every Playwright action and
expect() of a step shows inside it in the report. log() and test_data() add to the scenario, if you want them."""
from behave import given, then, when
from playwright.sync_api import expect

from reporting_labs import log, test_data


@given("I am on the shop")
def on_the_shop(context):
    context.page.goto(context.base_url + "/")


@when('I log in as "{user}" with password "{password}"')
def log_in(context, user, password):
    test_data({"username": user, "password": password}, "Login")     # the password is masked in the report
    context.page.fill("#user", user)
    context.page.fill("#password", password)                          # masked in the step title too
    context.page.click("#login")


@then('I see the message "{text}"')
def see_message(context, text):
    log("checking the greeting")
    expect(context.page.locator("#msg")).to_have_text(text)


@when("I open the cart")
def open_cart(context):
    context.page.click("#cart")


@then('the page title is "{title}"')
def page_title(context, title):
    expect(context.page).to_have_url(context.base_url + "/cart.html")
    expect(context.page.locator("#cart-title")).to_have_text(title)


@when("I click checkout")
def click_checkout(context):
    context.page.click("#checkout", timeout=1500)


@then("I am on the checkout page")
def on_checkout(context):
    expect(context.page).to_have_url(context.base_url + "/checkout.html")
