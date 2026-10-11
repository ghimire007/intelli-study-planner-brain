import asyncio
import re
import uuid
from typing import Literal

from app.agents.graphAPI import build_advisor_graph
from app.agents.history import MessageView, build_history, latest_reply
from app.agents.nodes.conversation import looks_like_sols_record
from app.core.checkpointer import get_checkpointer
from app.core.config import settings
from app.llm.config import LLMConfig
from app.llm.errors import ProviderFailure, classify
from app.llm.factory import make_chat_model
from app.llm.registry import PROVIDER_LABELS
from app.models.auth import User
from app.models.session import ChatSession
from app.schemas.chat import ChatContext
from app.services.chat_context import SessionNotFound, intake_context, safe_record
from app.services.credential_resolver import CredentialResolver
from app.services.pii import scrub_pii
from app.services.vault_service import VaultService
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

ElectiveMode = Literal["degree", "interest"]


def prepare_first_message(
    message: str,
    input_type: Literal["enrolment", "question"] = "question",
) -> tuple[str, bool]:
    if not message.strip():
        raise ValueError("Enter a message before sending.")

    looks_like_record = looks_like_sols_record(message)

    if looks_like_record:
        return safe_record(message), True

    if input_type == "enrolment":
        # Do not silently interpret arbitrary prose as a SOLS record.
        raise ValueError(
            "The enrolment submission does not look like a valid SOLS record."
        )

    return scrub_pii(message), False


def wants_plan(message: str) -> bool:
    """Recognise explicit generation/revision requests without replanning explanations."""
    return bool(
        re.search(
            r"\b(?:create|generate|build|make|revise|update|change|modify|adjust|regenerate)"
            r"\b.{0,100}\b(?:plan|schedule)\b|"
            r"\b(?:plan|schedule)\b.{0,100}\b(?:revise|update|change|modify|adjust)\b",
            message,
            re.I | re.S,
        )
    )


def _context_elective_preferences(
    context: ChatContext | None,
    elective_mode: ElectiveMode | None,
    elective_interests: list[str] | None,
) -> tuple[ElectiveMode | None, list[str] | None]:
    """Use explicit arguments first, falling back to preferences in the profile context."""
    profile = context.profile if context is not None else None
    if elective_mode is None and profile is not None:
        elective_mode = profile.elective_mode
    if elective_interests is None and profile is not None:
        elective_interests = profile.elective_interests
    return elective_mode, list(elective_interests) if elective_interests is not None else None


class CredentialRejected(Exception):
    """The provider refused the key mid-conversation; it has been marked invalid."""


class AgentChatService:
    """LangGraph-backed chat, scoped to one signed-in student.

    Conversational state, parsed SOLS metadata, handbook data, elective preferences,
    and per-message cost/token metadata live in the LangGraph Postgres checkpointer,
    keyed by thread_id = str(session.id). ChatSession remains the indexable row
    that owns the session and records its model and credential.

    The student's decrypted API key is resolved per request and handed to
    build_advisor_graph. It is never placed in AdvisorState.
    """

    def __init__(self, db: AsyncSession, user: User) -> None:
        self._db = db
        self._user = user
        self._vault = VaultService(db)
        self._resolver = CredentialResolver(db)

    async def start_session(
        self,
        raw_sols: str,
        *,
        model: str | None = None,
        input_type: str = "question",
        context: ChatContext | None = None,
        elective_mode: ElectiveMode | None = None,
        elective_interests: list[str] | None = None,
    ) -> tuple[ChatSession, MessageView]:
        session_id = uuid.uuid4()
        prepared, is_record = prepare_first_message(raw_sols, input_type=input_type)
        elective_mode, elective_interests = _context_elective_preferences(
            context, elective_mode, elective_interests
        )

        intake = intake_context(
            self._user, context, {}, prepared if is_record else None
        )
        llm_config = await self._resolver.resolve(self._user, requested_model=model)
        graph = build_advisor_graph(self._db, get_checkpointer(), llm_config)

        initial_state = {
            "messages": [HumanMessage(content=prepared)],
            **intake,
            "elective_mode": elective_mode,
            "elective_interests": elective_interests or [],
            "handbook": None,
            "electives": None,
            "remaining_subjects": None,
            "electives_feedback": None,
            "remaining_feedback": None,
            "plan": None,
            "plan_feedback": None,
            "retry_count": 0,
            "stage1_retry_count": 0,
            "stage2_retry_count": 0,
            "stage2_tool_loop_count": 0,
            "planning_requested": bool(is_record or wants_plan(raw_sols)),
            "sols_prompted": False,
            "no_enrolment_history": False,
            "conversation_mode": "collecting",
            "current_stage": None,
        }

        await self._invoke(
            graph,
            llm_config,
            initial_state,
            {"configurable": {"thread_id": str(session_id)}},
        )

        state = await graph.aget_state(
            {"configurable": {"thread_id": str(session_id)}}
        )
        meta = state.values.get("meta") or {}
        session = ChatSession(
            id=session_id,
            degree_code=meta.get("degree_code") or "UNKNOWN",
            user_id=self._user.id,
            provider=llm_config.provider.value,
            model=llm_config.model,
            credential_id=llm_config.credential_id,
        )
        self._db.add(session)
        await self._db.commit()

        reply = await latest_reply(graph, str(session_id), fallback_model=llm_config.model)
        if reply is None:
            raise ValueError(
                "The advisor returned no response. Confirm the academic details and retry."
            )
        return session, reply

    async def continue_session(
        self,
        session_id: uuid.UUID,
        user_message: str,
        *,
        model: str | None = None,
        context: ChatContext | None = None,
        elective_mode: ElectiveMode | None = None,
        elective_interests: list[str] | None = None,
    ) -> MessageView:
        session = await self._owned_session(session_id)
        llm_config = await self._resolver.resolve(
            self._user, requested_model=model, session=session
        )
        graph = build_advisor_graph(self._db, get_checkpointer(), llm_config)
        config = {"configurable": {"thread_id": str(session_id)}}

        state = await graph.aget_state(config)
        if "raw_sols" not in state.values:
            raise SessionNotFound(
                f"Session {session_id} has no conversation state — it may be stale or was never started"
            )

        prepared, is_record = prepare_first_message(user_message, input_type="question")
        payload = {
            **intake_context(
                self._user, context, state.values, prepared if is_record else None
            ),
            "messages": [HumanMessage(content=prepared)],
        }

        elective_mode, elective_interests = _context_elective_preferences(
            context, elective_mode, elective_interests
        )
        # Only overwrite persisted preferences when the request supplies a value.
        # An explicitly supplied [] clears the previously saved interests.
        if elective_mode is not None:
            payload["elective_mode"] = elective_mode
        if elective_interests is not None:
            payload["elective_interests"] = list(elective_interests)

        if is_record or wants_plan(user_message):
            payload["planning_requested"] = True

        await self._invoke(graph, llm_config, payload, config)

        if session.model != llm_config.model or session.credential_id != llm_config.credential_id:
            session.provider = llm_config.provider.value
            session.model = llm_config.model
            session.credential_id = llm_config.credential_id
            await self._db.commit()

        reply = await latest_reply(graph, str(session_id), fallback_model=llm_config.model)
        if reply is None:
            raise ValueError(
                "The advisor returned no response. Confirm the academic details and retry."
            )
        return reply

    async def get_history(self, session_id: uuid.UUID) -> tuple[ChatSession, list[MessageView]]:
        session = await self._owned_session(session_id)
        graph = build_advisor_graph(self._db, get_checkpointer())
        state = await graph.aget_state(
            {"configurable": {"thread_id": str(session_id)}}
        )
        if "raw_sols" not in state.values:
            raise SessionNotFound(
                f"Session {session_id} has no conversation state — it may be stale or was never started"
            )
        messages = await build_history(graph, str(session_id), fallback_model=session.model)
        return session, messages

    async def _owned_session(self, session_id: uuid.UUID) -> ChatSession:
        session = await self._db.get(ChatSession, session_id)
        # Sessions without an owner cannot be proven to belong to this user.
        if session is None or session.user_id != self._user.id:
            raise SessionNotFound(f"Session {session_id} not found")
        return session

    async def _invoke(self, graph, llm_config: LLMConfig, payload: dict, config: dict) -> None:
        """Run a turn, converting a rejected key into a fixable error for the student."""
        try:
            async with asyncio.timeout(settings.CHAT_TURN_TIMEOUT_SECONDS):
                await graph.ainvoke(payload, config=config)
        except Exception as exc:
            if (
                classify(exc) is ProviderFailure.AUTH
                and llm_config.credential_id is not None
            ):
                await self._vault.mark_rejected(
                    llm_config.credential_id,
                    f"{llm_config.provider} rejected the key in chat",
                )
                raise CredentialRejected(
                    f"Your {PROVIDER_LABELS[llm_config.provider]} key was rejected. "
                    "Update it in your key settings and try again."
                ) from exc
            raise

        if llm_config.credential_id is not None:
            await self._vault.touch_used(llm_config.credential_id)

    async def generate_title(self, session_id: uuid.UUID) -> str:
        """Generate a short title from the chat's opening context and latest reply."""
        _session, messages = await self.get_history(session_id)
        if not messages:
            return "New Chat"

        real_user_msgs = [
            m.content for m in messages
            if m.role == "user"
            and m.content.strip().lower() not in ("hello", "no enrolment yet")
        ]
        user_context = real_user_msgs[-1] if real_user_msgs else messages[0].content
        assistant_msgs = [m.content for m in messages if m.role == "assistant"]
        assistant_context = assistant_msgs[-1] if assistant_msgs else ""

        llm_config = await self._resolver.resolve(self._user)
        model = make_chat_model(llm_config)
        prompt = [
            SystemMessage(
                content=(
                    "Create a concise, personalised title for this Courseo study-planning chat.\n"
                    "Focus on the student's degree, major, specific core subjects, or question.\n"
                    "Return ONLY the title text: 3 to 7 words, maximum 48 characters.\n"
                    "Do NOT use JSON, quotes, or markdown formatting."
                )
            ),
            HumanMessage(
                content=(
                    f"Student input: {user_context[:1200]}\n\n"
                    f"Assistant reply: {assistant_context[:1200]}"
                )
            ),
        ]
        res = await model.ainvoke(prompt)
        raw_text = ""

        if isinstance(res.content, str):
            raw_text = res.content
        elif isinstance(res.content, list):
            for block in res.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    raw_text += block.get("text", "")
                elif hasattr(block, "text"):
                    raw_text += getattr(block, "text", "")

        return raw_text.strip().strip('"').strip("'")
