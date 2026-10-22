"""FastAPI application entry point."""

from fastapi import FastAPI

from app import __version__
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=__version__)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
