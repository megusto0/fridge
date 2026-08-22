"""«2x64 г» in a name is two doughnuts of sixty-four grams."""

from decimal import Decimal

from fridge_api.models import Product
from fridge_api.services.enrichment.worker import EnrichmentWorker
from fridge_api.services.naming import multipack_from_name


def test_a_multipack_is_read_off_the_name():
    assert multipack_from_name("Пончики Перекрёсток Берлинские с кремом 2x64 г") == (
        2,
        Decimal("64"),
    )
    assert multipack_from_name("Крупа Увелка Гречневая ядрица Экстра 5пак*80г") == (
        5,
        Decimal("80"),
    )
    assert multipack_from_name("Йогурт 6 х 100 мл") == (6, Decimal("100"))


def test_a_count_without_a_unit_is_not_a_weight():
    """«Twix 3*2» means something else, and 2 g of Twix is not a piece."""
    assert multipack_from_name("Шоколадный батончик Twix 3*2") is None
    assert multipack_from_name("Нечто 2x3 г") is None
    assert multipack_from_name("Молоко 1 л") is None
    assert multipack_from_name("") is None


def test_the_pack_total_replaces_the_piece_the_parser_mistook_for_it():
    product = Product(
        canonical_name="Пончики Перекрёсток Берлинские с кремом 2x64 г",
        net_quantity=Decimal("64"),
        net_unit="g",
    )

    EnrichmentWorker._apply_multipack(product)

    assert product.piece_weight_g == Decimal("64")
    assert product.net_quantity == Decimal("128")


def test_a_pack_total_that_is_already_right_is_left_alone():
    product = Product(
        canonical_name="Крупа Увелка Гречневая ядрица Экстра 5пак*80г",
        net_quantity=Decimal("400"),
        net_unit="g",
    )

    EnrichmentWorker._apply_multipack(product)

    assert product.piece_weight_g == Decimal("80")
    assert product.net_quantity == Decimal("400")


def test_a_measured_piece_weight_outranks_the_label():
    product = Product(
        canonical_name="Пончики 2x64 г",
        net_quantity=Decimal("128"),
        net_unit="g",
        piece_weight_g=Decimal("70"),
    )

    EnrichmentWorker._apply_multipack(product)

    assert product.piece_weight_g == Decimal("70")
