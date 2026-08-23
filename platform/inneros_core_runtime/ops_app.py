"""Entrypoint uvicorn panel ops :2002."""

from raphiia_openai.ops_routes import create_ops_app

app = create_ops_app()
