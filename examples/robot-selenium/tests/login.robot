*** Settings ***
Documentation     Demo Shop login, driven by SeleniumLibrary.
Library           SeleniumLibrary
Suite Setup       Start Site
Suite Teardown    Stop Site
Test Setup        Open Demo Shop
Test Teardown     Close Browser

*** Variables ***
${BASE}    http://127.0.0.1:8797

*** Test Cases ***
Login shows the greeting
    [Tags]    smoke    priority:P1    owner:asha    feature:login
    Input Text        id:user        demo
    Input Password    id:password    S3cretPw!
    Click Element     id:login
    Element Text Should Be    id:msg    Welcome demo
    Capture Page Screenshot

Wrong greeting fails
    [Tags]    priority:P2    feature:login
    Input Text     id:user    demo
    Click Element  id:login
    Element Text Should Be    id:msg    Hello demo

*** Keywords ***
Open Demo Shop
    Open Browser    ${BASE}/    chrome    options=add_argument("--headless=new");add_argument("--no-sandbox");add_argument("--disable-gpu");add_argument("--disable-dev-shm-usage")

Start Site
    ${server}=    Evaluate    __import__("subprocess").Popen(["python","-m","http.server","8797","--directory","site"], cwd=__import__("os").path.dirname(r"${SUITE SOURCE}") + "/..")
    Set Suite Variable    ${server}
    Sleep    0.5s

Stop Site
    Call Method    ${server}    terminate
