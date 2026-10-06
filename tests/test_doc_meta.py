from reporting_labs.core.doc_meta import parse


def test_pairs_and_tags():
    meta, tags = parse("Places an order.\n\n@owner naveen  @priority P0  @jira SHOP-12\n@smoke")
    assert meta == {"owner": "naveen", "priority": "P0", "jira": "SHOP-12"}
    assert tags == ["smoke"]


def test_multiword_value_and_email():
    meta, _ = parse("@feature Cart and checkout @owner asha@shop.io")
    assert meta == {"feature": "Cart and checkout", "owner": "asha@shop.io"}


def test_separators_and_bare_tags():
    meta, tags = parse("@priority: P1 @severity=critical @P2 @critical")
    assert meta == {"priority": "P1", "severity": "critical"}
    assert tags == ["P2", "critical"]


def test_docstring_noise_is_ignored():
    assert parse("Contact naveen@x.com.\n@param x the value\n@returns nothing\n@pytest.mark.slow") == ({}, [])


def test_quoted_values():
    meta, _ = parse("@owner 'naveen'  @feature \"Cart and checkout\"")
    assert meta == {"owner": "naveen", "feature": "Cart and checkout"}


def test_mentions_in_sentences_are_not_tags():
    meta, tags = parse("Regression reported by @naveen, thanks @asha\n@smoke")
    assert tags == ["smoke"]
