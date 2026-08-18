import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from fridge_api.models import ContainerStatus, InventoryLot, InventoryStatus
from fridge_api.schemas import BatchConsumeRequest


def list_inventory(
    session: Session, owner_id: uuid.UUID, include_empty: bool = False
) -> list[dict[str, object]]:
    statement = (
        select(InventoryLot)
        .where(InventoryLot.owner_id == owner_id)
        .options(selectinload(InventoryLot.product))
    )
    if not include_empty:
        statement = statement.where(
            InventoryLot.remaining_quantity > Decimal("0"),
            InventoryLot.status.in_([InventoryStatus.AVAILABLE, InventoryStatus.RESERVED]),
        )
    lots = list(
        session.scalars(statement.order_by(InventoryLot.purchased_at, InventoryLot.created_at))
    )
    now = datetime.now(UTC)
    result = []
    for lot in lots:
        expires_at = lot.expires_at
        days_to_expiry = None
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            days_to_expiry = (expires_at.date() - now.date()).days

        # Dual unit calculations (grams & pieces)
        unit_norm = lot.unit.lower().strip()
        weight_grams: Decimal | None = None
        estimated_pieces: int | None = None
        rem = lot.remaining_quantity
        p = lot.product

        if unit_norm in ("kg", "кг"):
            weight_grams = rem * Decimal("1000")
            if p and p.piece_weight_g and p.piece_weight_g > 0:
                estimated_pieces = max(1, round(float(weight_grams / p.piece_weight_g)))
        elif unit_norm in ("g", "г", "gr", "гр"):
            weight_grams = rem
            if p and p.piece_weight_g and p.piece_weight_g > 0:
                estimated_pieces = max(1, round(float(weight_grams / p.piece_weight_g)))
        elif unit_norm in ("pcs", "шт", "pack", "уп"):
            estimated_pieces = int(rem)
            if p and p.piece_weight_g and p.piece_weight_g > 0:
                weight_grams = rem * p.piece_weight_g
            elif p and p.net_quantity and p.net_quantity > 0:
                unit_p = (p.net_unit or "").lower()
                if unit_p in ("g", "г", "gr", "гр", "ml", "мл"):
                    weight_grams = rem * p.net_quantity
                elif unit_p in ("kg", "кг", "l", "л"):
                    weight_grams = rem * p.net_quantity * Decimal("1000")

        result.append(
            {
                "id": lot.id,
                "product_id": lot.product_id,
                "receipt_line_id": lot.receipt_line_id,
                "display_name": lot.display_name,
                "original_quantity": lot.original_quantity,
                "remaining_quantity": lot.remaining_quantity,
                "unit": lot.unit,
                "status": lot.status,
                "purchased_at": lot.purchased_at,
                "expires_at": lot.expires_at,
                "days_to_expiry": days_to_expiry,
                "weight_grams": weight_grams,
                "estimated_pieces": estimated_pieces,
                "product": lot.product,
            }
        )
    return result


def revert_consumption_for_meal(
    session: Session,
    owner_id: uuid.UUID,
    meal_id: uuid.UUID,
) -> tuple[int, int]:
    """Put back everything one GlucoTracker entry took out.

    Whole, not partial. An entry from GlucoTracker is either the whole thing or
    a mistake — nobody eats half a container and then deletes the record of it —
    so a container goes back to its full net weight and a lot gets the entire
    deducted quantity returned.

    The compensating movement is added rather than the original deleted: a
    fridge is an account, and an account that forgets its mistakes cannot be
    reconciled against the shelf. A container's `Consumption` row does go,
    because that row is the claim that the food was eaten — and it was not.
    """
    from fridge_api.models import (
        Consumption,
        InventoryTransaction,
        InventoryTransactionKind,
        MealPrepContainer,
    )

    reverted_lots = 0
    movements = session.scalars(
        select(InventoryTransaction).where(
            InventoryTransaction.owner_id == owner_id,
            InventoryTransaction.kind == InventoryTransactionKind.CONSUME,
            InventoryTransaction.reference_type == "glucotracker_meal",
            InventoryTransaction.reference_id == meal_id,
        )
    ).all()
    already_returned = {
        movement.lot_id
        for movement in session.scalars(
            select(InventoryTransaction).where(
                InventoryTransaction.owner_id == owner_id,
                InventoryTransaction.reference_type == "glucotracker_meal_revert",
                InventoryTransaction.reference_id == meal_id,
            )
        )
    }
    for movement in movements:
        # Idempotent by looking for the return, not by erasing what it undoes.
        # Deleting the original would make a second call a no-op too, and would
        # also make the ledger stop adding up.
        if movement.lot_id in already_returned:
            continue
        lot = session.get(InventoryLot, movement.lot_id)
        if lot is None:
            continue
        returned = -movement.delta_quantity
        lot.remaining_quantity = lot.remaining_quantity + returned
        if lot.status == InventoryStatus.DEPLETED and lot.remaining_quantity > 0:
            lot.status = InventoryStatus.AVAILABLE
        session.add(
            InventoryTransaction(
                owner_id=owner_id,
                lot_id=lot.id,
                kind=InventoryTransactionKind.RETURN,
                delta_quantity=returned,
                unit=movement.unit,
                reference_type="glucotracker_meal_revert",
                reference_id=meal_id,
            )
        )
        reverted_lots += 1

    reverted_containers = 0
    consumptions = session.scalars(
        select(Consumption).where(
            Consumption.owner_id == owner_id,
            Consumption.glucotracker_meal_id == meal_id,
        )
    ).all()
    for consumption in consumptions:
        container = session.get(MealPrepContainer, consumption.container_id)
        if container is not None:
            container.remaining_weight_g = container.net_weight_g
            container.status = ContainerStatus.READY
        session.delete(consumption)
        reverted_containers += 1

    session.commit()
    return reverted_lots, reverted_containers


def consume_inventory_lots(
    session: Session,
    owner_id: uuid.UUID,
    payload: BatchConsumeRequest,
) -> list[dict[str, object]]:
    from fridge_api.models import InventoryTransaction, InventoryTransactionKind
    from fridge_api.services.meal_prep import _calc_deduct_qty

    lot_ids = [item.lot_id for item in payload.items]
    statement = (
        select(InventoryLot)
        .where(InventoryLot.owner_id == owner_id, InventoryLot.id.in_(lot_ids))
        .options(selectinload(InventoryLot.product))
    )
    lots = {lot.id: lot for lot in session.scalars(statement)}

    for item in payload.items:
        lot = lots.get(item.lot_id)
        if not lot:
            continue
        if item.quantity is not None and item.unit is not None:
            deduct = _calc_deduct_qty(lot, item.quantity, item.unit)
        else:
            deduct = lot.remaining_quantity
        deduct = min(deduct, lot.remaining_quantity)
        lot.remaining_quantity = max(Decimal("0"), lot.remaining_quantity - deduct)
        if lot.remaining_quantity == Decimal("0"):
            lot.status = InventoryStatus.DEPLETED

        session.add(
            InventoryTransaction(
                owner_id=owner_id,
                lot_id=lot.id,
                kind=InventoryTransactionKind.CONSUME,
                delta_quantity=-deduct,
                unit=lot.unit,
                # The meal when there is one, so deleting that meal can find
                # this movement again. Falls back to the lot, which is what it
                # always said and what makes an untraceable consumption.
                reference_type=(
                    "glucotracker_meal"
                    if payload.glucotracker_meal_id
                    else "direct_consumption"
                ),
                reference_id=payload.glucotracker_meal_id or lot.id,
            )
        )
    session.commit()
    return list_inventory(session, owner_id, include_empty=True)
