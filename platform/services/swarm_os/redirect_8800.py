"""Redirección :8800 → :2002 (panel migrado)."""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

TARGET = "http://192.168.1.4:2002"

app = FastAPI(title="Ralphi IA Portal Redirect")


@app.get("/{full_path:path}")
@app.get("/")
def redirect_all(full_path: str = ""):
    url = f"{TARGET}/{full_path}" if full_path else TARGET
    return RedirectResponse(url, status_code=307)
