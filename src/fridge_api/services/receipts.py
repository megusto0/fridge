import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from fridge_api.domain import normalize_product_name
from fridge_api.models import (
    EnrichmentJob,
    EnrichmentJobStatus,
    EnrichmentStatus,
    InventoryLot,
    InventoryStatus,
    InventoryTransaction,
    InventoryTransactionKind,
    Product,
    ProductAlias,
    Receipt,
    ReceiptLine,
    ReceiptOperation,
)
from fridge_api.schemas import ReceiptImportRequest, ReceiptImportResponse, ReceiptResponse


def _find_product(
    session: Session,
    owner_id: uuid.UUID,
    merchant_inn: str,
    normalized_name: str,
    gtin: str | None,
    package_quantity: Decimal | None = None,
) -> Product | None:
    visibility = or_(Product.owner_id.is_(None), Product.owner_id == owner_id)
    if gtin:
        product = session.scalar(
            select(Product)
            .where(Product.gtin == gtin, visibility)
            .order_by(Product.owner_id.desc())
        )
        if product is not None:
            return product
    alias = session.scalar(
        select(ProductAlias)
        .join(Product, Product.id == ProductAlias.product_id)
        .where(
            ProductAlias.merchant_inn == merchant_inn,
            ProductAlias.normalized_name == normalized_name,
            or_(ProductAlias.owner_id.is_(None), ProductAlias.owner_id == owner_id),
            visibility,
        )
        .order_by(ProductAlias.owner_id.desc())
    )
    if alias is not None and alias.product is not None:
        if (
            package_quantity is not None
            and alias.product.net_quantity is not None
            and abs(alias.product.net_quantity - package_quantity) > package_quantity * Decimal("0.2")
        ):
            return None
        return alias.product
    return None


def _load_receipt(session: Session, owner_id: uuid.UUID, receipt_id: uuid.UUID) -> Receipt:
    return session.scalar(
        select(Receipt)
        .where(Receipt.id == receipt_id, Receipt.owner_id == owner_id)
        .options(selectinload(Receipt.lines))
    )


def import_receipt(
    session: Session, owner_id: uuid.UUID, payload: ReceiptImportRequest
) -> ReceiptImportResponse:
    existing = session.scalar(
        select(Receipt)
        .where(
            Receipt.owner_id == owner_id,
            Receipt.fiscal_fn == payload.fiscal_fn,
            Receipt.fiscal_fd == payload.fiscal_fd,
            Receipt.fiscal_fp == payload.fiscal_fp,
        )
        .options(selectinload(Receipt.lines))
    )
    if existing is not None:
        return ReceiptImportResponse(
            created=False,
            inventory_lots_created=0,
            enrichment_jobs_created=0,
            receipt=ReceiptResponse.model_validate(existing),
        )

    receipt = Receipt(
        owner_id=owner_id,
        provider=payload.provider,
        fiscal_fn=payload.fiscal_fn,
        fiscal_fd=payload.fiscal_fd,
        fiscal_fp=payload.fiscal_fp,
        operation=payload.operation,
        merchant_name=payload.merchant_name,
        merchant_inn=payload.merchant_inn,
        purchased_at=payload.purchased_at,
        total_minor=payload.total_minor,
        currency=payload.currency,
        source_message_id=payload.source_message_id,
        raw_payload=payload.raw_payload,
    )
    session.add(receipt)

    lots_created = 0
    jobs_created = 0
    for position, item in enumerate(payload.items, start=1):
        normalized_name = normalize_product_name(item.name)
        product = _find_product(
            session,
            owner_id,
            payload.merchant_inn,
            normalized_name,
            item.gtin,
            package_quantity=item.package_quantity,
        )
        line = ReceiptLine(
            owner_id=owner_id,
            receipt=receipt,
            position=position,
            raw_name=item.name,
            normalized_name=normalized_name,
            quantity=item.quantity,
            unit=item.unit,
            unit_price_minor=item.unit_price_minor,
            total_minor=item.total_minor,
            gtin=item.gtin,
            package_quantity=item.package_quantity,
            package_unit=item.package_unit,
            inventory_effect=item.inventory_effect,
            product_id=product.id if product else None,
            enrichment_status=(product.nutrition_status if product else EnrichmentStatus.PENDING),
        )
        session.add(line)
        session.flush()

        if payload.operation == ReceiptOperation.SALE and item.inventory_effect:
            lot = InventoryLot(
                owner_id=owner_id,
                product_id=product.id if product else None,
                receipt_line_id=line.id,
                display_name=product.canonical_name if product else item.name,
                original_quantity=item.quantity,
                remaining_quantity=item.quantity,
                unit=item.unit,
                status=InventoryStatus.AVAILABLE,
                purchased_at=payload.purchased_at,
            )
            session.add(lot)
            session.flush()
            session.add(
                InventoryTransaction(
                    owner_id=owner_id,
                    lot_id=lot.id,
                    kind=InventoryTransactionKind.PURCHASE,
                    delta_quantity=item.quantity,
                    unit=item.unit,
                    reference_type="receipt",
                    reference_id=receipt.id,
                )
            )
            lots_created += 1

        if product is None and item.inventory_effect:
            session.add(
                EnrichmentJob(
                    owner_id=owner_id,
                    receipt_line_id=line.id,
                    status=EnrichmentJobStatus.PENDING,
                )
            )
            jobs_created += 1

    session.commit()
    loaded = _load_receipt(session, owner_id, receipt.id)
    return ReceiptImportResponse(
        created=True,
        inventory_lots_created=lots_created,
        enrichment_jobs_created=jobs_created,
        receipt=ReceiptResponse.model_validate(loaded),
    )


def list_receipts(session: Session, owner_id: uuid.UUID) -> list[Receipt]:
    statement = (
        select(Receipt)
        .where(Receipt.owner_id == owner_id)
        .options(selectinload(Receipt.lines))
        .order_by(Receipt.purchased_at.desc())
    )
    return list(session.scalars(statement))
