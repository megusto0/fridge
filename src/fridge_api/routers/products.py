import uuid

from fastapi import APIRouter, status

from fridge_api.dependencies import OwnerDep, SessionDep
from fridge_api.schemas import (
    ProductAliasCreate,
    ProductCreate,
    ProductResponse,
    ProductServingUnitUpdate,
    ReceiptLineResponse,
    ResolveReceiptLineRequest,
)
from fridge_api.services import products as service

router = APIRouter(tags=["products"])


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, session: SessionDep, owner_id: OwnerDep):
    return service.create_product(session, owner_id, payload)


@router.get("/products", response_model=list[ProductResponse])
def list_products(session: SessionDep, owner_id: OwnerDep):
    return service.list_products(session, owner_id)


@router.patch("/products/{product_id}/serving-unit", response_model=ProductResponse)
def set_serving_unit(
    product_id: uuid.UUID,
    payload: ProductServingUnitUpdate,
    session: SessionDep,
    owner_id: OwnerDep,
):
    return service.set_serving_unit(session, owner_id, product_id, payload.serving_unit)


@router.post("/products/{product_id}/aliases", status_code=status.HTTP_201_CREATED)
def add_alias(
    product_id: uuid.UUID,
    payload: ProductAliasCreate,
    session: SessionDep,
    owner_id: OwnerDep,
):
    alias = service.add_alias(session, owner_id, product_id, payload)
    return {"id": alias.id, "product_id": alias.product_id, "raw_name": alias.raw_name}


@router.post("/receipt-lines/{line_id}/resolve", response_model=ReceiptLineResponse)
def resolve_receipt_line(
    line_id: uuid.UUID,
    payload: ResolveReceiptLineRequest,
    session: SessionDep,
    owner_id: OwnerDep,
):
    return service.resolve_receipt_line(session, owner_id, line_id, payload)
