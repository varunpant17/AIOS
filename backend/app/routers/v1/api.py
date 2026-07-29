from fastapi import APIRouter

from app.routers.health import router as health_router
from app.routers.users import router as users_router

router = APIRouter(prefix="/api/v1")

router.include_router(health_router)
router.include_router(users_router)