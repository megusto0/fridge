"""What the enrichment is doing to the things you just put in the fridge."""

from fastapi import APIRouter, Query

from fridge_api.dependencies import OwnerDep, SessionDep
from fridge_api.schemas import EnrichmentStatusResponse
from fridge_api.services import enrichment_status as service

router = APIRouter(tags=["enrichment"])


@router.get("/enrichment/status", response_model=EnrichmentStatusResponse)
def enrichment_status(
    session: SessionDep,
    owner_id: OwnerDep,
    limit: int = Query(default=20, ge=1, le=100),
):
    """Counts by state, and the most recent items with what happened to each."""
    return service.enrichment_status(session, owner_id, limit)
