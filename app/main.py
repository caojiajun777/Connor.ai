"""ASGI entrypoint for Connor.ai."""

from app.api import create_app

app = create_app()
