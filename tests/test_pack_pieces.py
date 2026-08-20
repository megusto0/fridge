"""A package counted as one «шт» still holds everything inside it."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fridge_api.models import InventoryLot, InventoryStatus, Product
from fridge_api.services.inventory import list_inventory

OWNER = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _lot(session, **product_kwargs) -> InventoryLot:
    product = Product(owner_id=OWNER, canonical_name="Товар", **product_kwargs)
    session.add(product)
    session.flush()
    lot = InventoryLot(
        owner_id=OWNER,
        product_id=product.id,
        display_name=product.canonical_name,
        original_quantity=Decimal("1"),
        remaining_quantity=Decimal("1"),
        unit="pcs",
        status=InventoryStatus.AVAILABLE,
        purchased_at=datetime.now(UTC),
    )
    session.add(lot)
    session.commit()
    return lot


def test_a_box_of_ten_eggs_is_ten_eggs(session_factory):
    """One lot, one box, ten eggs — not one egg of 60 g."""
    with session_factory() as session:
        _lot(
            session,
            net_quantity=Decimal("10"),
            net_unit="pcs",
            piece_weight_g=Decimal("60"),
        )
        row = list_inventory(session, OWNER, False)[0]

    assert row["estimated_pieces"] == 10
    assert row["weight_grams"] == Decimal("600")


def test_a_box_whose_pieces_have_no_known_weight_still_counts_them(session_factory):
    with session_factory() as session:
        _lot(session, net_quantity=Decimal("25"), net_unit="pcs")
        row = list_inventory(session, OWNER, False)[0]

    assert row["estimated_pieces"] == 25


def test_a_package_measured_in_grams_is_untouched(session_factory):
    """A 900 g bottle is one thing weighing 900 g, not 900 of anything."""
    with session_factory() as session:
        _lot(session, net_quantity=Decimal("900"), net_unit="g")
        row = list_inventory(session, OWNER, False)[0]

    assert row["estimated_pieces"] == 1
    assert row["weight_grams"] == Decimal("900")


def test_a_single_item_with_a_piece_weight_is_untouched(session_factory):
    """A 12 g sweet: one piece, twelve grams."""
    with session_factory() as session:
        _lot(session, piece_weight_g=Decimal("12"))
        row = list_inventory(session, OWNER, False)[0]

    assert row["estimated_pieces"] == 1
    assert row["weight_grams"] == Decimal("12")
