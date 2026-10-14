"""WAM calculation. Deterministic and LLM-free: marks never leave this process.

POST /wam/{session_id} calculates the WAM for a signed-in student and adds the
summary (aggregates only) to their chat session. The record itself is parsed,
averaged and dropped.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.auth import User
from app.services.agent_chat_service import AgentChatService
from app.services.enrolment import UnreadableRecord
from app.services.wam import WamResult, calculate_wam

router = APIRouter()


class WamRequest(BaseModel):
    enrolment_record: str


@router.post("/{session_id}", response_model=WamResult)
async def wam_for_session(
    session_id: uuid.UUID,
    body: WamRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WamResult:
    try:
        result = calculate_wam(body.enrolment_record)
    except UnreadableRecord as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    try:
        await AgentChatService(db=db, user=user).record_wam(session_id, result)
    except ValueError as exc:  # session missing or not theirs
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return result
