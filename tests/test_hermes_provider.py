from fridge_api.services.enrichment.hermes import _valid_url


def test_hermes_rejects_generic_calorizator_homepage() -> None:
    assert _valid_url("https://calorizator.ru/product") is None
    assert _valid_url("https://calorizator.ru/product/tvorog") is not None
    assert _valid_url("https://magnit.ru/product/1000175641") is not None
