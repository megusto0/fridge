import uuid

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from fridge_api.domain import normalize_product_name
from fridge_api.models import (
    EnrichmentJob,
    EnrichmentJobStatus,
    InventoryLot,
    Product,
    ProductAlias,
    ReceiptLine,
    ServingUnit,
    utcnow,
)
from fridge_api.schemas import ProductAliasCreate, ProductCreate, ResolveReceiptLineRequest


def create_product(session: Session, owner_id: uuid.UUID, payload: ProductCreate) -> Product:
    product = Product(owner_id=owner_id, **payload.model_dump())
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def list_products(session: Session, owner_id: uuid.UUID) -> list[Product]:
    statement = (
        select(Product)
        .where(or_(Product.owner_id.is_(None), Product.owner_id == owner_id))
        .order_by(Product.canonical_name)
    )
    return list(session.scalars(statement))


def get_visible_product(session: Session, owner_id: uuid.UUID, product_id: uuid.UUID) -> Product:
    product = session.scalar(
        select(Product).where(
            Product.id == product_id,
            or_(Product.owner_id.is_(None), Product.owner_id == owner_id),
        )
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def set_serving_unit(
    session: Session,
    owner_id: uuid.UUID,
    product_id: uuid.UUID,
    serving_unit: ServingUnit,
) -> Product:
    """Record how this product is eaten.

    Answered once and kept, because the answer belongs to the product and not
    to whoever asked: a tub of ice cream is eaten by the spoonful in every app
    that shows it, and on every phone.
    """
    product = get_visible_product(session, owner_id, product_id)
    product.serving_unit = serving_unit
    session.commit()
    session.refresh(product)
    return product


def add_alias(
    session: Session,
    owner_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: ProductAliasCreate,
) -> ProductAlias:
    get_visible_product(session, owner_id, product_id)
    alias = ProductAlias(
        owner_id=owner_id,
        product_id=product_id,
        merchant_inn=payload.merchant_inn,
        raw_name=payload.raw_name,
        normalized_name=normalize_product_name(payload.raw_name),
    )
    session.add(alias)
    session.commit()
    session.refresh(alias)
    return alias


def resolve_receipt_line(
    session: Session,
    owner_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: ResolveReceiptLineRequest,
) -> ReceiptLine:
    line = session.scalar(
        select(ReceiptLine).where(ReceiptLine.id == line_id, ReceiptLine.owner_id == owner_id)
    )
    if line is None:
        raise HTTPException(status_code=404, detail="Receipt line not found")
    product = get_visible_product(session, owner_id, payload.product_id)
    line.product_id = product.id
    line.enrichment_status = product.nutrition_status
    lot = session.scalar(
        select(InventoryLot).where(
            InventoryLot.receipt_line_id == line.id, InventoryLot.owner_id == owner_id
        )
    )
    if lot is not None:
        lot.product_id = product.id
    job = session.scalar(
        select(EnrichmentJob).where(
            EnrichmentJob.receipt_line_id == line.id,
            EnrichmentJob.owner_id == owner_id,
        )
    )
    if job is not None:
        job.status = EnrichmentJobStatus.COMPLETED
        job.completed_at = utcnow()
        job.locked_at = None
        job.result = {"product_id": str(product.id)}
    if payload.save_alias:
        existing = session.scalar(
            select(ProductAlias).where(
                ProductAlias.owner_id == owner_id,
                ProductAlias.merchant_inn == line.receipt.merchant_inn,
                ProductAlias.normalized_name == line.normalized_name,
            )
        )
        if existing is None:
            session.add(
                ProductAlias(
                    owner_id=owner_id,
                    product_id=product.id,
                    merchant_inn=line.receipt.merchant_inn,
                    raw_name=line.raw_name,
                    normalized_name=line.normalized_name,
                )
            )
    session.commit()
    session.refresh(line)
    return line
