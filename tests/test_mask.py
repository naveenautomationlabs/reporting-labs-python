from reporting_labs.core.mask import Masker, parse_csv


def m(**kw):
    kw.setdefault("from_env", False)
    return Masker(**kw)


def test_sensitive_keys_in_data():
    masker = m()
    out = masker.mask({"username": "demo", "password": "S3cret", "nested": {"api_key": "abc", "ok": "keep"}})
    assert out == {"username": "demo", "password": "****", "nested": {"api_key": "****", "ok": "keep"}}


def test_bearer_keeps_scheme():
    assert m().mask_str("Authorization: Bearer abcdefgh12345") == "Authorization: **** ****"


def test_key_equals_value_in_text():
    assert m().mask_str("logging in with password=Sup3rSecret and token: abc12345") == "logging in with password=**** and token: ****"


def test_json_token_in_text():
    assert m().mask_str('{"access_token": "abc.def.ghi"}') == '{"access_token": "****"}'


def test_python_dict_repr():
    assert m().mask_str("{'token': 'abc123xyz'}") == "{'token': '****'}"


def test_spoken_password():
    assert m().mask_str("the password is Hunter2x9pw") == "the password is ****"
    # a plain word after "password is" is left alone
    assert m().mask_str("the password is valid") == "the password is valid"


def test_url_userinfo():
    assert m().mask_str("connect to https://admin:S3cretPw@host/db") == "connect to https://admin:****@host/db"


def test_set_cookie():
    assert "****" in m().mask_str("Set-Cookie: sid=abc123def456; Path=/")


def test_card_number_luhn():
    assert m().mask_str("card 4242 4242 4242 4242 charged") == "card **** charged"
    # a non-Luhn number is left alone
    assert m().mask_str("order 1234 5678 9012 3456 shipped") == "order 1234 5678 9012 3456 shipped"


def test_provider_keys():
    for tok in ("ghp_" + "a" * 36, "AKIA" + "A" * 16, "glpat-" + "x" * 20, "AIza" + "b" * 35):
        assert m().mask_str(f"key is {tok} ok") == "key is **** ok"


def test_learned_value_blanked_later():
    masker = m()
    masker.mask_str("password=Sw0rdfish99")
    assert masker.mask_str("Logging in as admin / Sw0rdfish99") == "Logging in as admin / ****"


def test_known_values_and_env():
    masker = Masker(known_values=["from-config-9f8e7d"], from_env=True, environ={"DB_PASSWORD": "env-secret-123"})
    assert masker.mask_str("value from-config-9f8e7d appears") == "value **** appears"
    assert masker.mask_str("db pass env-secret-123 here") == "db pass **** here"


def test_assertion_compare_masks_secret():
    out = m().mask_str("token mismatch\nExpected: tok_aaa111bbb\nReceived: tok_ccc222ddd")
    assert "tok_aaa111bbb" not in out and "tok_ccc222ddd" not in out


def test_not_over_eager():
    # ordinary words near "auth" / "pin" are not masked
    assert m().mask_str("the author pinned a message") == "the author pinned a message"


def test_parse_csv():
    cols, rows = parse_csv('a,b,c\n1,2,3\n"x,y",5,6')
    assert cols == ["a", "b", "c"]
    assert rows == [["1", "2", "3"], ["x,y", "5", "6"]]
