import uuid

from fastapi import APIRouter, Response, status

from fridge_api.dependencies import OwnerDep, SessionDep
from fridge_api.schemas import (
    ConsumptionCreate,
    ConsumptionResponse,
    ContainerCreate,
    ContainerLabelResponse,
    ContainerResponse,
    ContainerTypeCreate,
    ContainerTypeResponse,
    MealPrepBatchCreate,
    MealPrepBatchResponse,
    MealPrepBatchUpdate,
    NameSuggestionRequest,
    NameSuggestionResponse,
    PortionPlanRequest,
)
from fridge_api.services import meal_prep as service

router = APIRouter(tags=["meal-prep"])


@router.post("/container-types", response_model=ContainerTypeResponse, status_code=201)
def create_container_type(payload: ContainerTypeCreate, session: SessionDep, owner_id: OwnerDep):
    return service.create_container_type(session, owner_id, payload)


@router.get("/container-types", response_model=list[ContainerTypeResponse])
def get_container_types(session: SessionDep, owner_id: OwnerDep):
    return service.list_container_types(session, owner_id)


@router.post("/meal-prep/batches", response_model=MealPrepBatchResponse)
def create_batch(
    payload: MealPrepBatchCreate,
    response: Response,
    session: SessionDep,
    owner_id: OwnerDep,
):
    batch, created = service.create_batch(session, owner_id, payload)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return batch


@router.get("/meal-prep/batches", response_model=list[MealPrepBatchResponse])
def list_batches(session: SessionDep, owner_id: OwnerDep):
    return service.list_batches(session, owner_id)


@router.get("/meal-prep/batches/{batch_id}", response_model=MealPrepBatchResponse)
def get_batch(batch_id: uuid.UUID, session: SessionDep, owner_id: OwnerDep):
    return service.get_batch(session, owner_id, batch_id)


@router.patch("/meal-prep/batches/{batch_id}", response_model=MealPrepBatchResponse)
def update_batch(
    batch_id: uuid.UUID,
    payload: MealPrepBatchUpdate,
    session: SessionDep,
    owner_id: OwnerDep,
):
    return service.update_batch(session, owner_id, batch_id, payload)


@router.post(
    "/meal-prep/batches/{batch_id}/suggest-name",
    response_model=NameSuggestionResponse,
)
def suggest_batch_name(
    batch_id: uuid.UUID,
    payload: NameSuggestionRequest,
    session: SessionDep,
    owner_id: OwnerDep,
):
    name, source, fallback_used = service.suggest_batch_name(
        session, owner_id, batch_id, payload.mode
    )
    return NameSuggestionResponse(name=name, source=source, fallback_used=fallback_used)


@router.put(
    "/meal-prep/batches/{batch_id}/portions",
    response_model=MealPrepBatchResponse,
)
def replace_portions(
    batch_id: uuid.UUID,
    payload: PortionPlanRequest,
    session: SessionDep,
    owner_id: OwnerDep,
):
    return service.replace_portions(session, owner_id, batch_id, payload)


@router.post(
    "/meal-prep/batches/{batch_id}/containers",
    response_model=ContainerResponse,
    status_code=201,
)
def add_container(
    batch_id: uuid.UUID,
    payload: ContainerCreate,
    session: SessionDep,
    owner_id: OwnerDep,
):
    return service.add_container(session, owner_id, batch_id, payload)


@router.post("/meal-prep/batches/{batch_id}/finalize", response_model=MealPrepBatchResponse)
def finalize_batch(batch_id: uuid.UUID, session: SessionDep, owner_id: OwnerDep):
    return service.finalize_batch(session, owner_id, batch_id)


@router.post("/meal-prep/batches/{batch_id}/cancel", response_model=MealPrepBatchResponse)
def cancel_batch(batch_id: uuid.UUID, session: SessionDep, owner_id: OwnerDep):
    return service.cancel_batch(session, owner_id, batch_id)


@router.get("/containers/by-code/{public_code:path}", response_model=ContainerResponse)
def get_container_by_code(public_code: str, session: SessionDep, owner_id: OwnerDep):
    return service.get_container_by_code(session, owner_id, public_code)


@router.get("/containers/{container_id}", response_model=ContainerResponse)
def get_container(container_id: uuid.UUID, session: SessionDep, owner_id: OwnerDep):
    return service.get_container(session, owner_id, container_id)


@router.get("/containers/{container_id}/label", response_model=ContainerLabelResponse)
def get_container_label(container_id: uuid.UUID, session: SessionDep, owner_id: OwnerDep):
    return service.container_label(session, owner_id, container_id)


@router.post(
    "/containers/{container_id}/consume",
    response_model=ConsumptionResponse,
    status_code=201,
)
def consume_container(
    container_id: uuid.UUID,
    payload: ConsumptionCreate,
    session: SessionDep,
    owner_id: OwnerDep,
):
    return service.consume_container(session, owner_id, container_id, payload)
