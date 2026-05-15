from fastapi import APIRouter
from app.api.v1.chat import router as chat_router
from app.api.v1.test_records import router as test_records_router

router = APIRouter(prefix="/api/v1")
router.include_router(chat_router, prefix="/chat", tags=["chat"])
router.include_router(test_records_router, prefix="/test-records", tags=["dev"])
