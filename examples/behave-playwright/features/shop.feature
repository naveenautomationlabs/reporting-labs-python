@feature:shop
Feature: Demo shop
  The login page and the cart of a small local shop.

  Background:
    Given I am on the shop

  @P1 @owner:asha @story:SHOP-12
  Scenario: Log in shows a welcome
    When I log in as "demo" with password "S3cretPw!"
    Then I see the message "Welcome demo"

  @P2
  Scenario: Go to the cart
    When I open the cart
    Then the page title is "Your cart"

  @P1 @critical
  Scenario: Checkout is enabled
    # Fails on purpose, so the report has a failure to explain: the button stays disabled.
    When I click checkout
    Then I am on the checkout page

  @P3
  Scenario Outline: Log in as <user>
    When I log in as "<user>" with password "<password>"
    Then I see the message "Welcome <user>"

    Examples:
      | user  | password  |
      | asha  | Pa55word! |
      | priya | Pa55word! |
