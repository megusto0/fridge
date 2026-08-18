from decimal import Decimal

from fridge_api.services.enrichment.types import nutrition_plausible
from fridge_api.services.enrichment.yandex_eda import (
    eda_product_image,
    is_strict_match,
    parse_yandex_nutrients,
)


def test_strict_match_accepts_same_sku() -> None:
    assert is_strict_match(
        "СЫР БРЕСТ-ЛИТОВСК КОРОЛЕВСКИЙ 45% 200Г",
        "Сыр полутвердый Брест-Литовск Королевский 45% 200 г",
        receipt_qty=Decimal("200"),
        receipt_unit="g",
    )


def test_strict_match_rejects_different_pack_size() -> None:
    assert not is_strict_match(
        "ТОМАТЫ ЧЕРРИ 250Г",
        "Томаты черри Премьер Оф Тейст Горячее сердце 200 г",
        receipt_qty=Decimal("250"),
        receipt_unit="g",
    )


def test_strict_match_rejects_different_fat_percent() -> None:
    assert not is_strict_match(
        "ТВОРОГ 5% 200Г",
        "Творог Село Зелёное 9% 200 г",
    )


def test_parse_yandex_nutrients_from_card() -> None:
    parsed = parse_yandex_nutrients(
        [
            {"title": "protein", "value": "25 g"},
            {"title": "fat", "value": "24 g"},
            {"title": "carbohydrates", "value": "0 g"},
            {"title": "kcal", "value": "316"},
        ]
    )
    assert parsed == (Decimal("316"), Decimal("25"), Decimal("24"), Decimal("0"))
    assert nutrition_plausible(*parsed)


def test_eda_product_image_rejects_promo_feed() -> None:
    assert (
        eda_product_image(
            "https://avatars.mds.yandex.net/get-feeds-media/5396768/abc/orig"
        )
        is None
    )
    good = (
        "https://avatars.mds.yandex.net/get-eda/1962206/"
        "756b443b0d89f468549a50487b986442/400x400nocrop"
    )
    assert eda_product_image(good) == good


def test_parse_yandex_nutrients_rejects_inconsistent_macros() -> None:
    assert (
        parse_yandex_nutrients(
            [
                {"title": "protein", "value": "5 g"},
                {"title": "fat", "value": "5 g"},
                {"title": "carbohydrates", "value": "10 g"},
                {"title": "kcal", "value": "150"},
            ]
        )
        is None
    )
