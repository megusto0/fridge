from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, status

from fridge_api.config import get_settings
from fridge_api.dependencies import OwnerDep
from fridge_api.schemas import ImageUploadResponse

router = APIRouter(prefix="/media", tags=["media"])


def _image_type(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


@router.post("/images", response_model=ImageUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: UploadFile,
    request: Request,
    owner_id: OwnerDep,
) -> ImageUploadResponse:
    settings = get_settings()
    data = await file.read(settings.upload_max_bytes + 1)
    await file.close()
    if len(data) > settings.upload_max_bytes:
        raise HTTPException(status_code=413, detail="Image is larger than the configured limit")
    detected = _image_type(data)
    if detected is None:
        raise HTTPException(status_code=422, detail="Only JPEG, PNG and WebP images are accepted")
    extension, content_type = detected
    digest = hashlib.sha256(data).hexdigest()
    relative = Path(str(owner_id)) / f"{digest}.{extension}"
    target = Path(settings.upload_directory) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)
    url = request.url_for("uploaded-media", path=str(relative))
    return ImageUploadResponse(url=str(url), content_type=content_type, size=len(data))
