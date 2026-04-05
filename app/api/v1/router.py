from fastapi import APIRouter
from app.api.v1.chat import router as chat_router

router = APIRouter(prefix="/api/v1")
router.include_router(chat_router, prefix="/chat", tags=["chat"])
