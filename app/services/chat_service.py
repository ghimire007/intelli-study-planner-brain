import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import BaseLLM, LLMMessage
from app.models.handbook import Handbook
from app.models.message import ChatMessage, LLMProvider, MessageRole
from app.models.session import ChatSession
from app.prompts.parser import PARSER_PROMPT
from app.prompts.system import SYSTEM_PROMPT
from app.services.sols_parser import SOLSMeta


class ChatService:
    def __init__(self, db: AsyncSession, llm: BaseLLM) -> None:
        self._db = db
        self._llm = llm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_session(self, raw_sols: str) -> tuple[ChatSession, ChatMessage]:
        """
        Initialise a new chat session from a raw SOLS paste.

        1. Extract degree_code + year from SOLS via LLM parser
        2. Fetch handbook from DB
        3. Build and store system message
        4. Store user message (raw SOLS)
        5. Call LLM and store assistant response
        """
        meta = await self._parse_sols_meta(raw_sols)
        handbook = await self._fetch_handbook(meta.degree_code, meta.year, meta.campus)
        system_content = self._build_system_prompt(handbook.information, raw_sols)

        session = ChatSession(degree_code=meta.degree_code)
        self._db.add(session)
        await self._db.flush()  # get session.id

        await self._store_message(session.id, MessageRole.system, system_content)
        await self._store_message(session.id, MessageRole.user, raw_sols)

        reply = await self._call_and_store(session.id, system_content, [
            LLMMessage(role="user", content=raw_sols),
        ])

        await self._db.commit()
        return session, reply

    async def continue_session(self, session_id: uuid.UUID, user_message: str) -> ChatMessage:
        """
        Continue an existing session with a new user message.

        1. Load session + full message history from DB
        2. Extract system message
        3. Append new user message to history
        4. Call LLM and store response
        """
        session = await self._db.get(ChatSession, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        history = await self._load_history(session_id)
        system_content = next(m.content for m in history if m.role == MessageRole.system)

        llm_messages = [
            LLMMessage(role="assistant" if m.role == MessageRole.assistant else "user", content=m.content)
            for m in history
            if m.role in (MessageRole.user, MessageRole.assistant)
        ]
        llm_messages.append(LLMMessage(role="user", content=user_message))

        await self._store_message(session_id, MessageRole.user, user_message)
        reply = await self._call_and_store(session_id, system_content, llm_messages)

        await self._db.commit()
        return reply

    async def get_history(self, session_id: uuid.UUID) -> tuple[ChatSession, list[ChatMessage]]:
        session = await self._db.get(ChatSession, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        messages = await self._load_history(session_id)
        return session, messages

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _parse_sols_meta(self, raw_sols: str) -> SOLSMeta:
        response = await self._llm.chat(
            system_prompt=PARSER_PROMPT,
            messages=[LLMMessage(role="user", content=raw_sols)],
        )
        raw_json = _strip_code_block(response.content)
        data = json.loads(raw_json)
        return SOLSMeta(**data)

    async def _fetch_handbook(self, degree_code: str, year: int, campus: str) -> Handbook:
        # Prefer the handbook year closest to (but not exceeding) the student's commencement year.
        # Fall back to the most recent available year, then to any campus entry if the specific campus is missing.
        for campus_filter in [campus, None]:
            query = (
                select(Handbook)
                .where(Handbook.course == degree_code)
                .order_by(Handbook.year.desc())
            )
            if campus_filter is not None:
                query = query.where(Handbook.campus == campus_filter)
            result = await self._db.execute(query.limit(1))
            handbook = result.scalar_one_or_none()
            if handbook:
                return handbook
        raise ValueError(f"No handbook found for course {degree_code}")

    def _build_system_prompt(self, handbook_md: str, raw_sols: str) -> str:
        return (
            SYSTEM_PROMPT
            .replace("{{handbook}}", handbook_md)
            .replace("{{sols}}", raw_sols)
        )

    async def _store_message(
        self,
        session_id: uuid.UUID,
        role: MessageRole,
        content: str,
    ) -> ChatMessage:
        msg = ChatMessage(session_id=session_id, role=role, content=content)
        self._db.add(msg)
        await self._db.flush()
        return msg

    async def _call_and_store(
        self,
        session_id: uuid.UUID,
        system_content: str,
        messages: list[LLMMessage],
    ) -> ChatMessage:
        llm_response = await self._llm.chat(
            system_prompt=system_content,
            messages=messages,
        )
        msg = ChatMessage(
            session_id=session_id,
            role=MessageRole.assistant,
            content=llm_response.content,
            parts=llm_response.parts,
            provider=LLMProvider(llm_response.provider),
            model=llm_response.model,
            tokens_in=llm_response.tokens_in,
            tokens_out=llm_response.tokens_out,
            cached_tokens=llm_response.cached_tokens,
            cost_usd=llm_response.cost_usd,
        )
        self._db.add(msg)
        await self._db.flush()
        return msg

    async def _load_history(self, session_id: uuid.UUID) -> list[ChatMessage]:
        result = await self._db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        return list(result.scalars().all())


def _strip_code_block(text: str) -> str:
    """Remove markdown code block wrappers if LLM wraps JSON in them."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()
