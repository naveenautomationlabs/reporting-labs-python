"""Selenium + pytest. Every driver command is a step, a screenshot is attached when a test fails."""
import pytest
from selenium.webdriver.common.by import By

from reporting_labs import meta, log, step, test_data


@pytest.mark.meta(priority="P1", owner="ravi", feature="login")
def test_login(driver, base_url):
    test_data({"username": "demo", "password": "S3cretPw!"}, "Login")
    driver.get(base_url + "/")
    with step("Log in"):
        driver.find_element(By.ID, "user").send_keys("demo")
        driver.find_element(By.ID, "password").send_keys("S3cretPw!")   # masked in the report
        driver.find_element(By.ID, "login").click()
    log("checking the greeting")
    assert driver.find_element(By.ID, "msg").text == "Welcome demo"


@pytest.mark.meta(priority="P2", feature="login")
def test_wrong_greeting(driver, base_url):
    """Fails on purpose: the greeting does not match."""
    driver.get(base_url + "/")
    driver.find_element(By.ID, "user").send_keys("demo")
    driver.find_element(By.ID, "login").click()
    assert driver.find_element(By.ID, "msg").text == "Hello demo"
