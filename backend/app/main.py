from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.services import fx


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    stop = fx.start_background(get_sessionmaker()) if get_settings().rate_auto_update else None
    yield
    if stop is not None:
        stop.set()


app = FastAPI(
    title="Bar Inventory API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.include_router(api_router)


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
