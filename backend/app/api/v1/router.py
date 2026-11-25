from fastapi import APIRouter

from app.api.v1 import auth, catalog, dashboard, documents, inventories, sales, settings, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(settings.router)
api_router.include_router(catalog.router)
api_router.include_router(documents.router)
api_router.include_router(inventories.router)
api_router.include_router(dashboard.router)
api_router.include_router(sales.router)
