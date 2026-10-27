import logging
import re
import uuid
from typing import Literal

from app.agents.graphAPI import build_advisor_graph
from app.agents.history import MessageView, build_history, latest_reply
from app.core.checkpointer import get_checkpointer
from app.llm.config import LLMConfig
from app.llm.errors import ProviderFailure, classify
from app.llm.factory import make_chat_model
from app.llm.registry import PROVIDER_LABELS
from app.models.auth import User
from app.models.session import ChatSession
from app.schemas.chat import ChatContext
from app.services.course_code import normalize_course_code
from app.services.credential_resolver import CredentialResolver
from app.services.enrolment import UnreadableRecord, project
from app.services.pii import scrub_pii
from app.services.sols_parser import extract_sols_metadata
from app.services.vault_service import VaultService
from app.services.wam import calculate_wam, describe_for_prompt
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

ElectiveMode = Literal["degree", "interest"]

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

logger = logging.getLogger(__name__)


def _record_input(message: str, context: ChatContext | None) -> tuple[str, str] | None:
    """Prefer a pasted record, then the record supplied with the chat request.

    Parse before scrubbing: the projection removes PII, while the free-text
    scrubber can erase a flattened record that starts with a Student label.
    """
    try:
        return message, project(message)
    except UnreadableRecord:
        if context is not None and context.enrolment_record:
            raw = context.enrolment_record.strip()
            if raw:
                return raw, project(raw)
        # A malformed table must not travel to the model as free-form chat.
        if re.search(
            r"(?im)^\s*(?:\|\s*Year\s*\|\s*Session\b|Year\s+Session\b|Enrolment History\b)"
            r"|\b(?:19|20)\d{2}(?:\s+|\s*\|\s*)(?:Annual|Autumn|Spring|Summer|Winter)\b",
            message,
        ):
            raise
    return None


def _confirmed_course_code(values: dict) -> str | None:
    """Read only metadata accepted by the conversation's confirmation workflow."""
    if not values.get("meta_confirmed"):
        return None
    return normalize_course_code((values.get("meta") or {}).get("degree_code"))


def _with_wam(projected: str, raw_record: str) -> str:
    """Append the server-calculated WAM to the projected record kept in state.

    The WAM is worked out from the unprojected paste, before its marks are
    dropped, and nothing but the WAM and its credit total comes back out. State
    holds the projected record and every prompt reads it, so the advisor sees
    the WAM and a newly pasted record replaces it. A record whose marks cannot
    be read must not block planning, so that case is noted instead of raised.
    The reason is logged, not shown: it may quote a mark. Any failure at all,
    not only an unreadable record, degrades to that note: the WAM is a bonus
    and must never stop the student getting a plan.
    """
    try:
        note = describe_for_prompt(calculate_wam(raw_record))
    except Exception:
        logger.warning("WAM not calculated", exc_info=True)
        note = "WAM: could not be calculated from this record (marks missing or unreadable)."
    return f"{projected}\n\n{note}"


class CredentialRejected(Exception):
    """The provider refused the key mid-conversation; it has been marked invalid."""


class AgentChatService:
    """LangGraph-backed chat, scoped to one signed-in student.

    Everything conversational — messages, parsed SOLS meta, handbook, per-message
    cost/token metadata — lives entirely in the LangGraph Postgres checkpointer,
    keyed by thread_id = str(session.id). We keep no ChatMessage rows: history
    and cost accounting are both reconstructed from checkpoint state on read
    (see app/agents/history.py). ChatSession itself stays — it's the thin,
    indexable row that owns the session (who it belongs to, which model and
    credential it runs on) and gives the API something to 404 against.

    The student's decrypted API key is resolved per request and handed to
    build_advisor_graph, which keeps it in a closure. It is never placed in
    AdvisorState, because the checkpointer persists state to Postgres.
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
        context: ChatContext | None = None,
        elective_mode: ElectiveMode | None = None,
        elective_interests: list[str] | None = None,
    ) -> tuple[ChatSession, MessageView]:
        session_id = uuid.uuid4()

        elective_mode, elective_interests = _context_elective_preferences(
            context, elective_mode, elective_interests
        )

        cleaned_sols = raw_sols.strip() if raw_sols else ""
        record_input = _record_input(cleaned_sols, context)
        projected_sols = "no enrolment yet"
        initial_messages = []
        planning_requested = False
        meta_payload = None

        if record_input is not None:
            source, projected = record_input
            meta_payload = extract_sols_metadata(source).model_dump()
            initial_messages.append(HumanMessage(content=projected))
            if source != cleaned_sols and cleaned_sols:
                initial_messages.append(HumanMessage(content=scrub_pii(cleaned_sols)))
            projected_sols = _with_wam(projected, source)
            planning_requested = True
        else:
            protected_sols = scrub_pii(cleaned_sols)
            parsed_meta = extract_sols_metadata(protected_sols)
            if any((parsed_meta.degree_code, parsed_meta.year, parsed_meta.campus, parsed_meta.majors)):
                meta_payload = parsed_meta.model_dump()
            initial_messages.append(HumanMessage(content=protected_sols or "Hello"))

        llm_config = await self._resolver.resolve(self._user, requested_model=model)
        graph = build_advisor_graph(self._db, get_checkpointer(), llm_config)

        # Invoke the graph with initial state
        await self._invoke(
            graph,
            llm_config,
            {
                "messages": initial_messages,
                "raw_sols": projected_sols,

                "meta": meta_payload,
                "meta_confirmed": False,

                "elective_mode": elective_mode,
                "elective_interests": elective_interests or [],

                "pending_elective_action": None,

                "conversation_mode": "collecting",

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
                "tool_calls_this_turn": 0,

                "planning_requested": planning_requested,
                "current_stage": None,
            },
            {"configurable": {"thread_id": str(session_id)}},
        )

        state = await graph.aget_state({"configurable": {"thread_id": str(session_id)}})
        # Expose only a course code that the student has confirmed in chat.
        degree_code = _confirmed_course_code(state.values) or "UNKNOWN"

        session = ChatSession(
            id=session_id,
            degree_code=degree_code,
            user_id=self._user.id,
            provider=llm_config.provider.value,
            model=llm_config.model,
            credential_id=llm_config.credential_id,
        )
        self._db.add(session)
        await self._db.commit()

        reply = await latest_reply(graph, str(session_id), fallback_model=llm_config.model)
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

        elective_mode, elective_interests = _context_elective_preferences(
            context, elective_mode, elective_interests
        )

        llm_config = await self._resolver.resolve(
            self._user, requested_model=model, session=session
        )
        graph = build_advisor_graph(self._db, get_checkpointer(), llm_config)
        config = {"configurable": {"thread_id": str(session_id)}}

        protected_message = scrub_pii(user_message)
        payload = {
            "messages": [HumanMessage(content=protected_message)],
            "tool_calls_this_turn": 0
        }

        if elective_mode is not None:
            payload["elective_mode"] = elective_mode

        if elective_interests is not None:
            payload["elective_interests"] = elective_interests

        record_input = _record_input(user_message, context)
        if record_input is not None:
            source, projected = record_input
            projected_with_wam = _with_wam(projected, source)
            if source != user_message:
                current = await graph.aget_state(config)
                # Frontends resend context with every turn. An unchanged record
                # must not erase a plan or turn a question into regeneration.
                if current.values.get("raw_sols") == projected_with_wam:
                    record_input = None

        if record_input is not None:
            print("continue_session: SOLS record detected")
            parsed_meta = extract_sols_metadata(source)
            messages = [HumanMessage(content=projected)]
            if source != user_message:
                messages.append(HumanMessage(content=protected_message))
            payload = {
                "messages": messages,
                "raw_sols": projected_with_wam,
                "planning_requested": True,
                "plan": None,
                "tool_calls_this_turn": 0,
            }

            # Update metadata only when the new record provides it.
            has_metadata = bool(
                parsed_meta.degree_code
                or parsed_meta.year is not None
                or parsed_meta.campus
                or parsed_meta.majors
            )

            if has_metadata:
                payload["meta"] = parsed_meta.model_dump()

                # New metadata must go through confirmation again.
                payload["meta_confirmed"] = False

            if elective_mode is not None:
                payload["elective_mode"] = elective_mode

            if elective_interests is not None:
                payload["elective_interests"] = elective_interests
        else:
            print("continue_session: standard chat message")

        await self._invoke(graph, llm_config, payload, config)

        # Keep the last confirmed course number even when later turns collect
        # other metadata or a replacement record awaits confirmation.
        state = await graph.aget_state(config)
        degree_code = _confirmed_course_code(state.values)
        if degree_code is not None:
            session.degree_code = degree_code

        # A student may switch models mid-conversation; keep the session in step
        # so the next turn resolves the same way without being asked again.
        if session.model != llm_config.model or session.credential_id != llm_config.credential_id:
            session.provider = llm_config.provider.value
            session.model = llm_config.model
            session.credential_id = llm_config.credential_id

        await self._db.commit()

        return await latest_reply(graph, str(session_id), fallback_model=llm_config.model)

    async def get_history(self, session_id: uuid.UUID) -> tuple[ChatSession, list[MessageView]]:
        session = await self._owned_session(session_id)

        # No key needed to read back what was already said.
        graph = build_advisor_graph(self._db, get_checkpointer())
        state = await graph.aget_state({"configurable": {"thread_id": str(session_id)}})

        if not state.values:
            return session, []

        # Older sessions may have confirmed checkpoint metadata but an UNKNOWN
        # SQL row. Repair on read without needing the student's provider key.
        degree_code = _confirmed_course_code(state.values)
        if degree_code is not None and session.degree_code != degree_code:
            session.degree_code = degree_code
            await self._db.commit()

        messages = await build_history(graph, str(session_id), fallback_model=session.model)
        return session, messages

    async def _owned_session(self, session_id: uuid.UUID) -> ChatSession:
        session = await self._db.get(ChatSession, session_id)
        # Sessions predating logins have user_id NULL: unreadable, because we
        # cannot prove whose they are. Same 404 either way — holding a session
        # UUID must not confirm that it exists.
        if session is None or session.user_id != self._user.id:
            raise ValueError(f"Session {session_id} not found")
        return session

    async def _invoke(self, graph, llm_config: LLMConfig, payload: dict, config: dict) -> None:
        """Run a turn, converting a rejected key into a fixable error for the student."""
        try:
            await graph.ainvoke(payload, config=config)
        except Exception as exc:
            if classify(exc) is ProviderFailure.AUTH and llm_config.credential_id is not None:
                await self._vault.mark_rejected(
                    llm_config.credential_id, f"{llm_config.provider} rejected the key in chat"
                )
                raise CredentialRejected(
                    f"Your {PROVIDER_LABELS[llm_config.provider]} key was rejected. "
                    f"Update it in your key settings and try again."
                ) from exc
            raise

        if llm_config.credential_id is not None:
            await self._vault.touch_used(llm_config.credential_id)


    async def generate_title(self, session_id: uuid.UUID) -> str:
        # Retrieve history or opening messages for context
        _session, messages = await self.get_history(session_id)
        if not messages:
            return "New Chat"

        # Get the initial prompt/reply pair
        real_user_msgs = [
            m.content for m in messages
            if m.role == "user" and m.content.strip().lower() not in ("hello", "no enrolment yet")
        ]

        # Fallback to the last available user message if all were generic greetings
        user_context = real_user_msgs[-1] if real_user_msgs else messages[0].content

        # Get the latest assistant response for context
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
                content=f"Student input: {user_context[:1200]}\n\nAssistant reply: {assistant_context[:1200]}"
            ),
        ]

        res = await model.ainvoke(prompt)

        # extract text from res.content
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
