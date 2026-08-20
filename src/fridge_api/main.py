from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from fridge_api import models  # noqa: F401
from fridge_api.config import get_settings
from fridge_api.db import Base, engine
from fridge_api.routers import enrichment, inventory, meal_prep, media, products, receipts


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-User-Id"],
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"status": "ok", "db": "connected"}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Database unreachable: {exc}",
            )

    app.include_router(enrichment.router)
    app.include_router(products.router)
    app.include_router(receipts.router)
    app.include_router(inventory.router)
    app.include_router(meal_prep.router)
    app.include_router(media.router)
    app.mount(
        "/uploaded-media",
        StaticFiles(directory=settings.upload_directory),
        name="uploaded-media",
    )
    ui_dir = Path(settings.web_ui_directory)
    if ui_dir.is_dir():
        app.mount(
            "/fridge",
            StaticFiles(directory=str(ui_dir), html=True),
            name="fridge-ui",
        )

        @app.get("/", include_in_schema=False)
        def root_redirect():
            return RedirectResponse(url="/fridge/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    return app


app = create_app()
