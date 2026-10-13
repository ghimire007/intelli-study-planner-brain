import logging
import uuid
from typing import NoReturn

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
from app.services.credential_resolver import CredentialUnreadable, NoCredentialError
from app.services.handbook_service import HandbookUnavailable

logger = logging.getLogger(__name__)

router = APIRouter()

def _get_elective_preferences(body: ChatRequest):
    """Extract elective settings from the request's profile, if present."""

    context = getattr(body, "context", None)
    profile = getattr(context, "profile", None) if context else None

    if profile is None:
        return None, None

    mode = getattr(profile, "elective_mode", None)
    interests = getattr(profile, "elective_interests", None)

    # Validate mode at the API boundary if your schema does not
    # already restrict it to the supported values.
    if mode not in (None, "degree", "interest"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid elective mode.",
        )

    if interests is not None:
        if isinstance(interests, str) or not isinstance(
            interests, (list, tuple)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Elective interests must be a list of strings.",
            )

        if any(not isinstance(item, str) for item in interests):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Each elective interest must be a string.",
            )

        interests = list(interests)

    return mode, interests

def _raise_llm_http_error(exc: Exception) -> NoReturn:
    """Translate recognized provider errors into safe HTTP responses."""

    # Preserve HTTP errors intentionally raised elsewhere.
    if isinstance(exc, HTTPException):
        raise exc

    failure = classify(exc)

    if failure is ProviderFailure.AUTH:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Your AI provider rejected the configured credentials. "
                "Check your API key in settings and retry."
            ),
        ) from exc

    if failure is ProviderFailure.RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Your AI provider is rate limiting this key or its quota "
                "has been exhausted. Wait and retry, or use a key with "
                "available quota."
            ),
        ) from exc

    if failure is ProviderFailure.TIMEOUT:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=(
                "Plan generation timed out. Check your saved chat before "
                "retrying to avoid duplicating work."
            ),
        ) from exc

    if failure is ProviderFailure.MODEL_UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "The selected model may not be available to your provider "
                "or API key. Check your model selection and retry."
            ),
        ) from exc

    if failure is ProviderFailure.UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI provider is temporarily unavailable. Please retry.",
        ) from exc

    # Unknown errors are application bugs until proven otherwise.
    logger.exception(
        "Unexpected error during AI request",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    raise exc


def _get_agent_service(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentChatService:
    return AgentChatService(db=db, user=user)

@router.post(
    "",
    response_model=StartSessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_session(
    body: ChatRequest,
    service: AgentChatService = Depends(_get_agent_service),
):
    elective_mode, elective_interests = _get_elective_preferences(body)

    logger.debug(
        "Starting chat session; elective_mode=%s, interest_count=%s",
        elective_mode,
        len(elective_interests) if elective_interests is not None else None,
    )

    try:
        session, reply = await service.start_session(
            body.message,
            model=body.model,
            elective_mode=elective_mode,
            elective_interests=elective_interests,
        )

        return StartSessionOut(
            session_id=str(session.id),
            reply=MessageOut.model_validate(reply),
        )

    except (NoCredentialError, CredentialUnreadable) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except CredentialRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except ProviderNotInstalled as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc

    except HandbookUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        _raise_llm_http_error(exc)


@router.post(
    "/{session_id}",
    response_model=ContinueSessionOut,
)
async def continue_session(
    session_id: uuid.UUID,
    body: ChatRequest,
    service: AgentChatService = Depends(_get_agent_service),
):
    elective_mode, elective_interests = _get_elective_preferences(body)

    logger.debug(
        "Continuing chat session %s; elective_mode=%s, interest_count=%s",
        session_id,
        elective_mode,
        len(elective_interests) if elective_interests is not None else None,
    )

    try:
        reply = await service.continue_session(
            session_id,
            body.message,
            model=body.model,
            elective_mode=elective_mode,
            elective_interests=elective_interests,
        )

        return ContinueSessionOut(
            session_id=str(session_id),
            reply=MessageOut.model_validate(reply),
        )

    except (NoCredentialError, CredentialUnreadable) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except CredentialRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except ProviderNotInstalled as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc

    except HandbookUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        # Keep this mapping only if ValueError from this service
        # specifically means that the session was not found.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        _raise_llm_http_error(exc)


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
