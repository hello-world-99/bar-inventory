from fastapi import FastAPI
from sqlalchemy import text

from app.api.v1.router import api_router
from app.db import get_engine

app = FastAPI(
    title="Bar Inventory API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.include_router(api_router)


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
