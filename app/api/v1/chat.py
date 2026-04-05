import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.llm.gemini import GeminiLLM
from app.schemas.chat import ChatRequest, ContinueSessionOut, HistoryOut, MessageOut, StartSessionOut
from app.services.chat_service import ChatService

router = APIRouter()


def _get_service(db: AsyncSession = Depends(get_db)) -> ChatService:
    return ChatService(db=db, llm=GeminiLLM())


@router.post("", response_model=StartSessionOut, status_code=201)
async def start_session(
    body: ChatRequest,
    service: ChatService = Depends(_get_service),
):
    try:
        session, reply = await service.start_session(body.message)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return StartSessionOut(session_id=str(session.id), reply=MessageOut.model_validate(reply))


@router.post("/{session_id}", response_model=ContinueSessionOut)
async def continue_session(
    session_id: uuid.UUID,
    body: ChatRequest,
    service: ChatService = Depends(_get_service),
):
    try:
        reply = await service.continue_session(session_id, body.message)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ContinueSessionOut(session_id=str(session_id), reply=MessageOut.model_validate(reply))


@router.get("/{session_id}", response_model=HistoryOut)
async def get_history(
    session_id: uuid.UUID,
    service: ChatService = Depends(_get_service),
):
    try:
        session, messages = await service.get_history(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return HistoryOut(
        session_id=str(session_id),
        degree_code=session.degree_code,
        messages=[MessageOut.model_validate(m) for m in messages if m.role.value != "system"],
    )
