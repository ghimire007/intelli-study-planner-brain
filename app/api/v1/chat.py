import uuid

from fastapi import APIRouter, Depends, HTTPException
from google.genai.errors import APIError
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.chat import (
    ChatRequest,
    ContinueSessionOut,
    HistoryOut,
    MessageOut,
    StartSessionOut,
)
from app.services.agent_chat_service import AgentChatService

router = APIRouter()


def _raise_llm_http_error(exc: Exception) -> None:
    cause: BaseException | None = exc
    while cause is not None and not isinstance(cause, APIError):
        cause = cause.__cause__

    if isinstance(cause, APIError) and cause.code == 429:
        raise HTTPException(
            status_code=429,
            detail=(
                "The study-planner AI quota is currently exhausted. "
                "Please retry later or configure a Gemini API key with available quota."
            ),
        ) from exc
    raise HTTPException(
        status_code=502,
        detail="The study-planner AI provider is temporarily unavailable.",
    ) from exc


def _get_agent_service(db: AsyncSession = Depends(get_db)) -> AgentChatService:
    return AgentChatService(db=db)


@router.post("", response_model=StartSessionOut, status_code=201)
async def start_session(
    body: ChatRequest,
    service: AgentChatService = Depends(_get_agent_service),
):
    try:
        session, reply = await service.start_session(body.message)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except (APIError, ChatGoogleGenerativeAIError) as e:
        _raise_llm_http_error(e)
    return StartSessionOut(session_id=str(session.id), reply=MessageOut.model_validate(reply))


@router.post("/{session_id}", response_model=ContinueSessionOut)
async def continue_session(
    session_id: uuid.UUID,
    body: ChatRequest,
    service: AgentChatService = Depends(_get_agent_service),
):
    try:
        reply = await service.continue_session(session_id, body.message)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (APIError, ChatGoogleGenerativeAIError) as e:
        _raise_llm_http_error(e)
    return ContinueSessionOut(session_id=str(session_id), reply=MessageOut.model_validate(reply))


@router.get("/{session_id}", response_model=HistoryOut)
async def get_history(
    session_id: uuid.UUID,
    service: AgentChatService = Depends(_get_agent_service),
):
    try:
        session, messages = await service.get_history(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return HistoryOut(
        session_id=str(session_id),
        degree_code=session.degree_code,
        messages=[MessageOut.model_validate(m) for m in messages if m.role != "system"],
    )
