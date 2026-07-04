"""FastAPI application factory."""

from fastapi import FastAPI

from app.api.routes import router


def create_app() -> FastAPI:
    """Create the Connor.ai API application."""

    app = FastAPI(
        title="Connor.ai API",
        version="0.1.0",
        description="Dashboard and replay API for Connor.ai daily intelligence runs.",
    )
    app.include_router(router)
    return app
