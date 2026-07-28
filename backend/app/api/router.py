from fastapi import APIRouter

from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.image import router as image_router
from app.api.video import router as video_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(image_router, tags=["image"])
api_router.include_router(video_router, tags=["video"])
api_router.include_router(files_router, tags=["files"])
