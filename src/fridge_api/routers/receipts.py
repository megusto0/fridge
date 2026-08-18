from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, status

from fridge_api.dependencies import OwnerDep, SessionDep
from fridge_api.parsers.magnit_email import MagnitReceiptParseError, parse_magnit_receipt_email
from fridge_api.schemas import ReceiptImportRequest, ReceiptImportResponse, ReceiptResponse
from fridge_api.services.receipts import import_receipt, list_receipts

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.post("/import", response_model=ReceiptImportResponse)
def import_fiscal_receipt(payload: ReceiptImportRequest, session: SessionDep, owner_id: OwnerDep):
    return import_receipt(session, owner_id, payload)


@router.post("/import-email", response_model=ReceiptImportResponse)
def import_receipt_email(
    raw_message: Annotated[bytes, Body(media_type="message/rfc822")],
    session: SessionDep,
    owner_id: OwnerDep,
):
    try:
        payload = parse_magnit_receipt_email(raw_message)
    except MagnitReceiptParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return import_receipt(session, owner_id, payload)


@router.get("", response_model=list[ReceiptResponse])
def get_receipts(session: SessionDep, owner_id: OwnerDep):
    return list_receipts(session, owner_id)
