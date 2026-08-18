from fastapi import APIRouter, Query

from fridge_api.dependencies import OwnerDep, SessionDep
from fridge_api.schemas import BatchConsumeRequest, InventoryLotResponse
from fridge_api.services.inventory import consume_inventory_lots, list_inventory

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("", response_model=list[InventoryLotResponse])
def get_inventory(
    session: SessionDep,
    owner_id: OwnerDep,
    include_empty: bool = Query(default=False),
):
    return list_inventory(session, owner_id, include_empty)


@router.post("/consume", response_model=list[InventoryLotResponse])
def consume_inventory(
    payload: BatchConsumeRequest,
    session: SessionDep,
    owner_id: OwnerDep,
):
    return consume_inventory_lots(session, owner_id, payload)
