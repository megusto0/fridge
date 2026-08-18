import uuid
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from fridge_api.config import get_settings
from fridge_api.domain import ZERO, make_container_code, nutrient_amount
from fridge_api.models import (
    BatchIngredient,
    BatchStatus,
    Consumption,
    ContainerStatus,
    ContainerType,
    InventoryLot,
    InventoryStatus,
    InventoryTransaction,
    InventoryTransactionKind,
    MealPrepBatch,
    MealPrepContainer,
    utcnow,
)
from fridge_api.schemas import (
    ConsumptionCreate,
    ContainerCreate,
    ContainerTypeCreate,
    MealPrepBatchCreate,
    MealPrepBatchUpdate,
    NameSuggestionMode,
    PortionMode,
    PortionPlanRequest,
)
from fridge_api.services.naming import fast_dish_name, hermes_dish_name


def _batch_query(owner_id: uuid.UUID, batch_id: uuid.UUID):
    return (
        select(MealPrepBatch)
        .where(MealPrepBatch.id == batch_id, MealPrepBatch.owner_id == owner_id)
        .options(
            selectinload(MealPrepBatch.ingredients),
            selectinload(MealPrepBatch.containers),
        )
    )


def get_batch(session: Session, owner_id: uuid.UUID, batch_id: uuid.UUID) -> MealPrepBatch:
    batch = session.scalar(_batch_query(owner_id, batch_id))
    if batch is None:
        raise HTTPException(status_code=404, detail="Meal-prep batch not found")
    return batch


def list_batches(session: Session, owner_id: uuid.UUID) -> list[MealPrepBatch]:
    return list(
        session.scalars(
            select(MealPrepBatch)
            .where(MealPrepBatch.owner_id == owner_id)
            .options(
                selectinload(MealPrepBatch.ingredients),
                selectinload(MealPrepBatch.containers),
            )
            .order_by(MealPrepBatch.created_at.desc())
        )
    )


def _calc_deduct_qty(lot: InventoryLot, requested_qty: Decimal, requested_unit: str) -> Decimal:
    lot_unit = (lot.unit or "").lower().strip()
    req_unit = (requested_unit or "").lower().strip()
    if lot_unit == req_unit or not req_unit:
        return requested_qty

    # Direct mass / volume conversions
    if lot_unit in ["kg", "кг"] and req_unit in ["g", "г", "ml", "мл"]:
        return requested_qty / Decimal("1000")
    if lot_unit in ["g", "г", "ml", "мл"] and req_unit in ["kg", "кг", "l", "л"]:
        return requested_qty * Decimal("1000")
    if lot_unit in ["l", "л"] and req_unit in ["ml", "мл", "g", "г"]:
        return requested_qty / Decimal("1000")
    if lot_unit in ["ml", "мл"] and req_unit in ["l", "л"]:
        return requested_qty * Decimal("1000")

    p = lot.product
    pack_weight = None
    if p:
        p_unit = (p.net_unit or "").lower().strip()
        if p_unit in ["kg", "кг", "l", "л"] and p.net_quantity:
            pack_weight = Decimal(str(p.net_quantity)) * Decimal("1000")
        elif p_unit in ["g", "г", "ml", "мл"] and p.net_quantity:
            pack_weight = Decimal(str(p.net_quantity))
        elif p.piece_weight_g:
            pack_weight = Decimal(str(p.piece_weight_g))

    if lot_unit in ["pcs", "шт"] and req_unit in ["g", "г", "ml", "мл"]:
        if pack_weight and pack_weight > ZERO:
            return requested_qty / pack_weight
        if requested_qty >= Decimal("10"):
            return min(Decimal("1.0"), requested_qty / Decimal("400"))
        return requested_qty

    if lot_unit in ["g", "г", "ml", "мл"] and req_unit in ["pcs", "шт"]:
        if pack_weight and pack_weight > ZERO:
            return requested_qty * pack_weight
        return requested_qty * Decimal("100")

    return requested_qty


def create_batch(
    session: Session, owner_id: uuid.UUID, payload: MealPrepBatchCreate
) -> tuple[MealPrepBatch, bool]:
    existing = session.scalar(
        select(MealPrepBatch).where(
            MealPrepBatch.owner_id == owner_id,
            MealPrepBatch.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return get_batch(session, owner_id, existing.id), False

    lot_ids = [ingredient.lot_id for ingredient in payload.ingredients]
    if len(lot_ids) != len(set(lot_ids)):
        raise HTTPException(status_code=422, detail="Each inventory lot may appear only once")
    lots = list(
        session.scalars(
            select(InventoryLot)
            .where(InventoryLot.owner_id == owner_id, InventoryLot.id.in_(lot_ids))
            .options(selectinload(InventoryLot.product))
        )
    )
    lots_by_id = {lot.id: lot for lot in lots}
    if len(lots_by_id) != len(lot_ids):
        raise HTTPException(status_code=404, detail="One or more inventory lots were not found")

    batch = MealPrepBatch(
        owner_id=owner_id,
        idempotency_key=payload.idempotency_key,
        name=payload.name,
        name_source="manual",
        image_url=payload.image_url,
        identification_confidence=payload.identification_confidence,
    )
    session.add(batch)
    session.flush()

    totals = {"kcal": ZERO, "protein": ZERO, "fat": ZERO, "carbs": ZERO}
    for requested in payload.ingredients:
        lot = lots_by_id[requested.lot_id]
        deduct_qty = _calc_deduct_qty(lot, requested.quantity, requested.unit)
        if lot.remaining_quantity < deduct_qty and (deduct_qty - lot.remaining_quantity) > Decimal("0.01"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Not enough {lot.display_name}: {lot.remaining_quantity} {lot.unit} available"
                ),
            )
        deduct_qty = min(deduct_qty, lot.remaining_quantity)
        product = lot.product
        values: dict[str, Decimal] = {}
        estimated = product is None
        for field, source_field in (
            ("kcal", "kcal_per_100"),
            ("protein", "protein_per_100"),
            ("fat", "fat_per_100"),
            ("carbs", "carbs_per_100"),
        ):
            value, field_estimated = nutrient_amount(
                getattr(product, source_field) if product else None,
                requested.quantity,
                requested.unit,
                product.net_quantity if product else None,
                product.net_unit if product else None,
            )
            values[field] = value
            estimated = estimated or field_estimated
            totals[field] += value

        session.add(
            BatchIngredient(
                owner_id=owner_id,
                batch_id=batch.id,
                lot_id=lot.id,
                product_id=lot.product_id,
                display_name=lot.display_name,
                quantity=requested.quantity,
                unit=requested.unit,
                nutrition_estimated=estimated,
                **values,
            )
        )
        lot.remaining_quantity = max(ZERO, lot.remaining_quantity - deduct_qty)
        if lot.remaining_quantity == ZERO:
            lot.status = InventoryStatus.DEPLETED
        session.add(
            InventoryTransaction(
                owner_id=owner_id,
                lot_id=lot.id,
                kind=InventoryTransactionKind.RESERVE,
                delta_quantity=-deduct_qty,
                unit=lot.unit,
                reference_type="meal_prep_batch",
                reference_id=batch.id,
            )
        )

    batch.kcal_total = totals["kcal"]
    batch.protein_total = totals["protein"]
    batch.fat_total = totals["fat"]
    batch.carbs_total = totals["carbs"]
    session.commit()
    return get_batch(session, owner_id, batch.id), True


def update_batch(
    session: Session,
    owner_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: MealPrepBatchUpdate,
) -> MealPrepBatch:
    batch = get_batch(session, owner_id, batch_id)
    if batch.status not in (BatchStatus.PORTIONING, BatchStatus.READY):
        raise HTTPException(status_code=409, detail="Only portioning or ready batches can be edited")
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(batch, key, value)
    session.commit()
    return get_batch(session, owner_id, batch.id)


def suggest_batch_name(
    session: Session,
    owner_id: uuid.UUID,
    batch_id: uuid.UUID,
    mode: NameSuggestionMode,
) -> tuple[str, str, bool]:
    batch = get_batch(session, owner_id, batch_id)
    names = [ingredient.display_name for ingredient in batch.ingredients]
    local = fast_dish_name(names)
    if mode == NameSuggestionMode.FAST:
        return local, "fast", False
    settings = get_settings()
    suggested = hermes_dish_name(
        names,
        executable=settings.enrichment_hermes_bin,
        timeout_seconds=settings.naming_hermes_timeout_seconds,
    )
    if suggested is None:
        return local, "fast_fallback", True
    return suggested, "hermes", False


def create_container_type(
    session: Session, owner_id: uuid.UUID, payload: ContainerTypeCreate
) -> ContainerType:
    container_type = ContainerType(owner_id=owner_id, **payload.model_dump())
    session.add(container_type)
    session.commit()
    session.refresh(container_type)
    return container_type


def list_container_types(session: Session, owner_id: uuid.UUID) -> list[ContainerType]:
    return list(
        session.scalars(
            select(ContainerType)
            .where(ContainerType.owner_id == owner_id)
            .order_by(ContainerType.name)
        )
    )


def _resolve_tare(
    session: Session,
    owner_id: uuid.UUID,
    container_type_id: uuid.UUID | None,
    tare_weight_g: Decimal | None,
) -> tuple[ContainerType | None, Decimal]:
    container_type = None
    if container_type_id is not None:
        container_type = session.scalar(
            select(ContainerType).where(
                ContainerType.id == container_type_id,
                ContainerType.owner_id == owner_id,
            )
        )
        if container_type is None:
            raise HTTPException(status_code=404, detail="Container type not found")
    tare = tare_weight_g
    if tare is None and container_type is not None:
        tare = container_type.tare_weight_g
    if tare is None:
        raise HTTPException(status_code=422, detail="Container tare is required")
    return container_type, tare


def _allocate_container_nutrition(batch: MealPrepBatch) -> None:
    if batch.total_net_weight_g <= ZERO:
        return
    for container in batch.containers:
        ratio = container.net_weight_g / batch.total_net_weight_g
        container.kcal = batch.kcal_total * ratio
        container.protein = batch.protein_total * ratio
        container.fat = batch.fat_total * ratio
        container.carbs = batch.carbs_total * ratio


def _portion_weights(payload: PortionPlanRequest) -> list[tuple[Decimal, str | None]]:
    total = payload.cooked_yield_g
    if payload.mode == PortionMode.EQUAL:
        count = payload.container_count or 1
        base = (total / Decimal(count)).quantize(Decimal("0.001"))
        weights = [base for _ in range(count)]
        weights[-1] += total - sum(weights, ZERO)
        return [(weight, None) for weight in weights]
    if payload.mode == PortionMode.FIXED:
        fixed = payload.fixed_net_weight_g or total
        full_count = int(total // fixed)
        weights = [fixed for _ in range(full_count)]
        remainder = total - sum(weights, ZERO)
        if remainder > ZERO and payload.include_remainder:
            weights.append(remainder)
        if not weights:
            weights = [total]
        return [(weight, None) for weight in weights]
    return [(portion.net_weight_g, portion.image_url) for portion in payload.portions]


def replace_portions(
    session: Session,
    owner_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: PortionPlanRequest,
) -> MealPrepBatch:
    batch = get_batch(session, owner_id, batch_id)
    if batch.status != BatchStatus.PORTIONING:
        raise HTTPException(status_code=409, detail="Batch is no longer accepting containers")
    container_type, tare = _resolve_tare(
        session, owner_id, payload.container_type_id, payload.tare_weight_g
    )
    weights = _portion_weights(payload)
    if not weights:
        raise HTTPException(status_code=422, detail="Portion plan creates no containers")
    total_weight = sum((weight for weight, _ in weights), ZERO)
    if total_weight != payload.cooked_yield_g:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Portion weights must equal cooked yield",
                "cooked_yield_g": str(payload.cooked_yield_g),
                "portioned_weight_g": str(total_weight),
                "difference_g": str(payload.cooked_yield_g - total_weight),
            },
        )
    for existing in list(batch.containers):
        session.delete(existing)
    session.flush()
    batch.containers = []
    for net, image_url in weights:
        batch.containers.append(
            MealPrepContainer(
                owner_id=owner_id,
                container_type_id=container_type.id if container_type else None,
                public_code=make_container_code(),
                gross_weight_g=net + tare,
                tare_weight_g=tare,
                net_weight_g=net,
                remaining_weight_g=net,
                image_url=image_url,
            )
        )
    batch.cooked_yield_g = payload.cooked_yield_g
    batch.total_net_weight_g = payload.cooked_yield_g
    session.flush()
    _allocate_container_nutrition(batch)
    session.commit()
    return get_batch(session, owner_id, batch.id)


def add_container(
    session: Session,
    owner_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: ContainerCreate,
) -> MealPrepContainer:
    batch = get_batch(session, owner_id, batch_id)
    if batch.status != BatchStatus.PORTIONING:
        raise HTTPException(status_code=409, detail="Batch is no longer accepting containers")

    container_type, tare = _resolve_tare(
        session, owner_id, payload.container_type_id, payload.tare_weight_g
    )
    if payload.gross_weight_g <= tare:
        raise HTTPException(status_code=422, detail="Gross weight must be greater than tare")
    net = payload.gross_weight_g - tare
    container = MealPrepContainer(
        owner_id=owner_id,
        batch_id=batch.id,
        container_type_id=container_type.id if container_type else None,
        public_code=make_container_code(),
        gross_weight_g=payload.gross_weight_g,
        tare_weight_g=tare,
        net_weight_g=net,
        remaining_weight_g=net,
        image_url=payload.image_url,
    )
    session.add(container)
    batch.total_net_weight_g += net
    batch.cooked_yield_g = batch.total_net_weight_g
    session.commit()
    session.refresh(container)
    return container


def finalize_batch(session: Session, owner_id: uuid.UUID, batch_id: uuid.UUID) -> MealPrepBatch:
    batch = get_batch(session, owner_id, batch_id)
    if batch.status == BatchStatus.READY:
        return batch
    if not batch.containers or batch.total_net_weight_g <= ZERO:
        raise HTTPException(status_code=409, detail="Add at least one weighed container first")
    if batch.cooked_yield_g is not None and batch.total_net_weight_g != batch.cooked_yield_g:
        raise HTTPException(
            status_code=409,
            detail="Container net weights do not equal the cooked yield",
        )
    _allocate_container_nutrition(batch)
    for ingredient in batch.ingredients:
        session.add(
            InventoryTransaction(
                owner_id=owner_id,
                lot_id=ingredient.lot_id,
                kind=InventoryTransactionKind.CONSUME,
                delta_quantity=ZERO,
                unit=ingredient.unit,
                reference_type="meal_prep_batch",
                reference_id=batch.id,
            )
        )
    batch.status = BatchStatus.READY
    batch.finalized_at = utcnow()
    session.commit()
    return get_batch(session, owner_id, batch.id)


def cancel_batch(session: Session, owner_id: uuid.UUID, batch_id: uuid.UUID) -> MealPrepBatch:
    batch = get_batch(session, owner_id, batch_id)
    if batch.status == BatchStatus.CANCELLED:
        return batch
    if batch.status == BatchStatus.READY:
        raise HTTPException(status_code=409, detail="A ready batch cannot be cancelled")
    for ingredient in batch.ingredients:
        lot = session.scalar(
            select(InventoryLot).where(
                InventoryLot.id == ingredient.lot_id,
                InventoryLot.owner_id == owner_id,
            )
        )
        if lot is None:
            raise HTTPException(status_code=409, detail="Reserved inventory lot no longer exists")
        lot.remaining_quantity += ingredient.quantity
        lot.status = InventoryStatus.AVAILABLE
        session.add(
            InventoryTransaction(
                owner_id=owner_id,
                lot_id=lot.id,
                kind=InventoryTransactionKind.RELEASE,
                delta_quantity=ingredient.quantity,
                unit=ingredient.unit,
                reference_type="meal_prep_batch",
                reference_id=batch.id,
            )
        )
    for container in batch.containers:
        container.status = ContainerStatus.DISCARDED
    batch.status = BatchStatus.CANCELLED
    batch.cancelled_at = utcnow()
    session.commit()
    return get_batch(session, owner_id, batch.id)


def get_container_by_code(
    session: Session, owner_id: uuid.UUID, public_code: str
) -> MealPrepContainer:
    container = session.scalar(
        select(MealPrepContainer).where(
            MealPrepContainer.owner_id == owner_id,
            MealPrepContainer.public_code == public_code,
        )
    )
    if container is None:
        raise HTTPException(status_code=404, detail="Container not found")
    return container


def get_container(
    session: Session, owner_id: uuid.UUID, container_id: uuid.UUID
) -> MealPrepContainer:
    container = session.scalar(
        select(MealPrepContainer)
        .where(
            MealPrepContainer.id == container_id,
            MealPrepContainer.owner_id == owner_id,
        )
        .options(selectinload(MealPrepContainer.batch))
    )
    if container is None:
        raise HTTPException(status_code=404, detail="Container not found")
    return container


def container_label(
    session: Session, owner_id: uuid.UUID, container_id: uuid.UUID
) -> dict[str, object]:
    container = get_container(session, owner_id, container_id)
    return {
        "container_id": container.id,
        "public_code": container.public_code,
        "data_matrix_value": container.public_code,
        "dish_name": container.batch.name,
        "prepared_at": container.batch.finalized_at or container.batch.created_at,
        "net_weight_g": container.net_weight_g,
        "kcal": container.kcal,
        "protein": container.protein,
        "fat": container.fat,
        "carbs": container.carbs,
    }


def consume_container(
    session: Session,
    owner_id: uuid.UUID,
    container_id: uuid.UUID,
    payload: ConsumptionCreate,
) -> Consumption:
    container = session.scalar(
        select(MealPrepContainer).where(
            MealPrepContainer.id == container_id,
            MealPrepContainer.owner_id == owner_id,
        )
    )
    if container is None:
        raise HTTPException(status_code=404, detail="Container not found")
    if container.status == ContainerStatus.CONSUMED:
        raise HTTPException(status_code=409, detail="Container is already consumed")
    amount = payload.consumed_weight_g or container.remaining_weight_g
    if amount > container.remaining_weight_g:
        raise HTTPException(status_code=409, detail="Consumed weight exceeds remaining weight")
    ratio = amount / container.net_weight_g
    consumption = Consumption(
        owner_id=owner_id,
        container_id=container.id,
        consumed_weight_g=amount,
        kcal=container.kcal * ratio,
        protein=container.protein * ratio,
        fat=container.fat * ratio,
        carbs=container.carbs * ratio,
        glucotracker_meal_id=payload.glucotracker_meal_id,
    )
    session.add(consumption)
    container.remaining_weight_g -= amount
    container.status = (
        ContainerStatus.CONSUMED
        if container.remaining_weight_g == ZERO
        else ContainerStatus.PARTIAL
    )
    session.commit()
    session.refresh(consumption)
    return consumption
