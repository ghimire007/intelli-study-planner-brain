import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.llm.errors import ProviderFailure, classify
from app.llm.factory import ProviderNotInstalled
from app.models.auth import User
from app.schemas.chat import (
    ChatRequest,
    ContinueSessionOut,
    HistoryOut,
    MessageOut,
    StartSessionOut,
    TitleOut,
)
from app.services.agent_chat_service import AgentChatService, CredentialRejected
from app.services.chat_context import InvalidChatContext, SessionNotFound
from app.services.credential_resolver import CredentialUnreadable, NoCredentialError
from app.services.handbook_service import HandbookUnavailable
from app.services.study_plan import PlanGenerationError

logger = logging.getLogger("uvicorn.error")
router = APIRouter()


def _raise_llm_http_error(exc: Exception) -> None:
    """Turn a provider failure into something the student can act on."""
    failure = classify(exc)
    if failure is ProviderFailure.TIMEOUT:
        raise HTTPException(status_code=504, detail="Plan generation timed out. Your saved chat is preserved. Retry or select another available model.") from exc
    if failure is ProviderFailure.MODEL_UNAVAILABLE:
        raise HTTPException(status_code=422, detail="Your AI provider does not offer the selected model for this key. Select an available model in settings and retry; your saved chat is preserved.") from exc
    if failure is ProviderFailure.RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Your AI provider is rate limiting this key, or its quota is used up. "
                "Wait a little and retry, or switch to a key with available quota."
            ),
        ) from exc
    if failure is ProviderFailure.UNKNOWN:
        # Not a recognisable provider failure — almost certainly our bug. Let it
        # through as a 500 with a traceback rather than blaming the provider.
        raise exc
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="The study-planner AI provider is temporarily unavailable.",
    ) from exc


def _get_agent_service(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentChatService:
    return AgentChatService(db=db, user=user)

@router.post("", response_model=StartSessionOut, status_code=201)
async def start_session(
    body: ChatRequest,
    service: AgentChatService = Depends(_get_agent_service),
):
    logger.debug("Starting chat (input_type=%s)", body.input_type)
    try:
        session, reply = await service.start_session(
            body.message, 
            model=body.model, input_type=body.input_type, context=body.context,
            elective_mode=(
                body.context.profile.elective_mode
                if body.context and body.context.profile
                else None
            ),
            elective_interests=(
                body.context.profile.elective_interests
                if body.context and body.context.profile
                else None
            )
        )

        print("BACKEND CONTEXT:", body.context)
        print(
            "BACKEND ELECTIVE MODE:",
            body.context.profile.elective_mode
            if body.context and body.context.profile
            else None,
        )
        print(
            "BACKEND ELECTIVE INTERESTS:",
            body.context.profile.elective_interests
            if body.context and body.context.profile
            else None,
        )
    except (NoCredentialError, CredentialUnreadable) as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except CredentialRejected as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ProviderNotInstalled as e:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(e)) from e
    except HandbookUnavailable as e:
        raise HTTPException(status_code=503, detail="The course handbook is unavailable. Please try again later.") from e
    except PlanGenerationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except InvalidChatContext as e:
        # The message is sanitized by safe_record; never log the raw record.
        logger.warning("Chat enrolment validation failed: %s", e)
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        _raise_llm_http_error(e)
    return StartSessionOut(session_id=str(session.id), reply=MessageOut.model_validate(reply))


@router.post("/{session_id}", response_model=ContinueSessionOut)
async def continue_session(
    session_id: uuid.UUID,
    body: ChatRequest,
    service: AgentChatService = Depends(_get_agent_service),
):
    try:
        reply = await service.continue_session(
            session_id, 
            body.message, 
            model=body.model, context=body.context,
            elective_mode=body.context.profile.elective_mode if body.context else None,
            elective_interests=body.context.profile.elective_interests if body.context else None
        )
    except (NoCredentialError, CredentialUnreadable) as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except CredentialRejected as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ProviderNotInstalled as e:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(e)) from e
    except SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except HandbookUnavailable as e:
        raise HTTPException(status_code=503, detail="The course handbook is unavailable. Please try again later.") from e
    except PlanGenerationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except InvalidChatContext as e:
        # The message is sanitized by safe_record; never log the raw record.
        logger.warning("Chat enrolment validation failed: %s", e)
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        _raise_llm_http_error(e)
    return ContinueSessionOut(session_id=str(session_id), reply=MessageOut.model_validate(reply))


@router.get("/{session_id}", response_model=HistoryOut)
async def get_history(
    session_id: uuid.UUID,
    service: AgentChatService = Depends(_get_agent_service),
):
    try:
        session, messages = await service.get_history(session_id)
    except SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except HandbookUnavailable as e:
        raise HTTPException(status_code=503, detail="The course handbook is unavailable. Please try again later.") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return HistoryOut(
        session_id=str(session_id),
        degree_code=session.degree_code,
        model=session.model,
        messages=[MessageOut.model_validate(m) for m in messages if m.role != "system"],
    )


@router.post("/{session_id}/title", response_model=TitleOut)
async def generate_title(
    session_id: uuid.UUID,
    service: AgentChatService = Depends(_get_agent_service),
):
    try:
        title = await service.generate_title(session_id)
        return TitleOut(session_id=str(session_id), title=title)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        _raise_llm_http_error(e)
