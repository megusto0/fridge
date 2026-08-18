import uuid
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from fridge_api.db import get_session


def get_current_owner(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> uuid.UUID:
    if x_user_id is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="X-User-Id is required")
    try:
        return uuid.UUID(x_user_id)
    except (TypeError, ValueError) as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="X-User-Id must be a valid UUID") from exc


SessionDep = Annotated[Session, Depends(get_session)]
OwnerDep = Annotated[uuid.UUID, Depends(get_current_owner)]
