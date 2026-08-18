from fastapi import APIRouter, Query

from fridge_api.dependencies import OwnerDep, SessionDep
from fridge_api.schemas import (
    BatchConsumeRequest,
    ConsumeRevertRequest,
    ConsumeRevertResponse,
    InventoryLotResponse,
)
from fridge_api.services.inventory import (
    consume_inventory_lots,
    list_inventory,
    revert_consumption_for_meal,
)

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


@router.post("/consume/revert", response_model=ConsumeRevertResponse)
def revert_consumption(
    payload: ConsumeRevertRequest,
    session: SessionDep,
    owner_id: OwnerDep,
):
    """Undo what one GlucoTracker entry consumed, when that entry is deleted.

    Idempotent: the movements it reverses are removed as it goes, so calling it
    twice returns zeros rather than putting the food back twice.
    """
    lots, containers = revert_consumption_for_meal(
        session, owner_id, payload.glucotracker_meal_id
    )
    return ConsumeRevertResponse(reverted_lots=lots, reverted_containers=containers)
