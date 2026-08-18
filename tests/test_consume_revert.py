"""Putting stock back when the entry that consumed it was a mistake."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fridge_api.models import (
    InventoryLot,
    InventoryStatus,
    InventoryTransaction,
    InventoryTransactionKind,
    Product,
)
from tests.conftest import OWNER_ID

MEAL_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


@pytest.fixture
def lot(session_factory) -> uuid.UUID:
    with session_factory() as session:
        product = Product(
            owner_id=OWNER_ID,
            canonical_name="Яблоки свежие",
            kcal_per_100=Decimal("47"),
        )
        session.add(product)
        session.flush()
        row = InventoryLot(
            owner_id=OWNER_ID,
            product_id=product.id,
            display_name="Яблоки свежие",
            original_quantity=Decimal("900"),
            remaining_quantity=Decimal("900"),
            unit="g",
            status=InventoryStatus.AVAILABLE,
            purchased_at=datetime(2026, 8, 18, tzinfo=UTC),
        )
        session.add(row)
        session.commit()
        return row.id


def test_a_deleted_entry_gives_its_stock_back(client, owner_headers, lot, session_factory):
    consumed = client.post(
        "/inventory/consume",
        json={
            "items": [{"lot_id": str(lot), "quantity": "180", "unit": "g"}],
            "glucotracker_meal_id": str(MEAL_ID),
        },
        headers=owner_headers,
    )
    assert consumed.status_code == 200, consumed.text
    with session_factory() as session:
        assert session.get(InventoryLot, lot).remaining_quantity == Decimal("720")

    reverted = client.post(
        "/inventory/consume/revert",
        json={"glucotracker_meal_id": str(MEAL_ID)},
        headers=owner_headers,
    )

    assert reverted.status_code == 200, reverted.text
    assert reverted.json() == {"reverted_lots": 1, "reverted_containers": 0}
    with session_factory() as session:
        assert session.get(InventoryLot, lot).remaining_quantity == Decimal("900")


def test_reverting_twice_does_not_conjure_food(client, owner_headers, lot, session_factory):
    client.post(
        "/inventory/consume",
        json={
            "items": [{"lot_id": str(lot), "quantity": "180", "unit": "g"}],
            "glucotracker_meal_id": str(MEAL_ID),
        },
        headers=owner_headers,
    )
    client.post(
        "/inventory/consume/revert",
        json={"glucotracker_meal_id": str(MEAL_ID)},
        headers=owner_headers,
    )
    second = client.post(
        "/inventory/consume/revert",
        json={"glucotracker_meal_id": str(MEAL_ID)},
        headers=owner_headers,
    )

    assert second.json() == {"reverted_lots": 0, "reverted_containers": 0}
    with session_factory() as session:
        assert session.get(InventoryLot, lot).remaining_quantity == Decimal("900")


def test_an_emptied_lot_comes_back_available(client, owner_headers, lot, session_factory):
    client.post(
        "/inventory/consume",
        json={
            "items": [{"lot_id": str(lot), "quantity": "900", "unit": "g"}],
            "glucotracker_meal_id": str(MEAL_ID),
        },
        headers=owner_headers,
    )
    with session_factory() as session:
        assert session.get(InventoryLot, lot).status == InventoryStatus.DEPLETED

    client.post(
        "/inventory/consume/revert",
        json={"glucotracker_meal_id": str(MEAL_ID)},
        headers=owner_headers,
    )

    with session_factory() as session:
        row = session.get(InventoryLot, lot)
        assert row.remaining_quantity == Decimal("900")
        assert row.status == InventoryStatus.AVAILABLE


def test_the_return_is_written_down_rather_than_erased(
    client, owner_headers, lot, session_factory
):
    """A fridge is an account. One that forgets cannot be checked against the shelf."""
    client.post(
        "/inventory/consume",
        json={
            "items": [{"lot_id": str(lot), "quantity": "180", "unit": "g"}],
            "glucotracker_meal_id": str(MEAL_ID),
        },
        headers=owner_headers,
    )
    client.post(
        "/inventory/consume/revert",
        json={"glucotracker_meal_id": str(MEAL_ID)},
        headers=owner_headers,
    )

    with session_factory() as session:
        movements = session.query(InventoryTransaction).all()
        kinds = [movement.kind for movement in movements]
        assert InventoryTransactionKind.RETURN in kinds
        assert sum(movement.delta_quantity for movement in movements) == Decimal("0")


def test_a_consumption_without_a_meal_is_left_alone(client, owner_headers, lot, session_factory):
    """Stock taken straight out of the fridge is not GlucoTracker's to return."""
    client.post(
        "/inventory/consume",
        json={"items": [{"lot_id": str(lot), "quantity": "180", "unit": "g"}]},
        headers=owner_headers,
    )

    reverted = client.post(
        "/inventory/consume/revert",
        json={"glucotracker_meal_id": str(MEAL_ID)},
        headers=owner_headers,
    )

    assert reverted.json() == {"reverted_lots": 0, "reverted_containers": 0}
    with session_factory() as session:
        assert session.get(InventoryLot, lot).remaining_quantity == Decimal("720")
