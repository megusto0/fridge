from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from fridge_api import models  # noqa: F401
from fridge_api.config import get_settings
from fridge_api.db import Base, engine
from fridge_api.routers import inventory, meal_prep, media, products, receipts


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
        allow_origins=["null", "http://127.0.0.1:8011", "http://localhost:8011"],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-User-Id"],
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

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
    ui_dir = settings.web_ui_directory if Path(settings.web_ui_directory).is_dir() else settings.mockup_directory
    if Path(ui_dir).is_dir():
        app.mount(
            "/fridge",
            StaticFiles(directory=ui_dir, html=True),
            name="fridge-ui",
        )
        app.mount(
            "/app",
            StaticFiles(directory=ui_dir, html=True),
            name="app",
        )
        app.mount(
            "/mockup",
            StaticFiles(directory=ui_dir, html=True),
            name="mockup-compat",
        )
        app.mount(
            "/",
            StaticFiles(directory=ui_dir, html=True),
            name="root-ui",
        )
    return app


app = create_app()
