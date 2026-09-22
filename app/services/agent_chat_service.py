import re
import uuid

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
from app.services.chat_context import SessionNotFound, intake_context, safe_record
from app.services.credential_resolver import CredentialResolver
from app.services.pii import scrub_pii
from app.services.vault_service import VaultService
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession


def prepare_first_message(message: str, input_type: str = "enrolment") -> tuple[str, bool]:
    """Route ordinary prose to the LLM; never send a detected raw record unprojected."""
    if not message.strip():
        raise ValueError("Enter a message before sending.")
    looks_like_record = bool(re.search(
        r"(?im)subject\s*code\s*nom(?:inal)?\s*cp|^\s*enrolment history(?:\s*:|[ \t]*$|\s+year\b)|subject\s*code\s*[|\t]|nom(?:inal)?\s*cp\s*[|\t]|"
        r"^\s*(?:\|?\s*year\s*[|\t]|(?:19|20)\d{2}\s+(?:Autumn|Spring|Summer)\s+)",
        message,
    )) or bool(re.search(r"(?im)^\s*student(?: name| number| id)?\s*:", message)
               and ("|" in message or "\t" in message))
    if input_type == "enrolment" or looks_like_record:
        return safe_record(message), True
    return scrub_pii(message), False


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
        self, raw_sols: str, *, model: str | None = None, input_type: str = "enrolment",
        context: ChatContext | None = None,
    ) -> tuple[ChatSession, MessageView]:
        session_id = uuid.uuid4()
        prepared, is_record = prepare_first_message(raw_sols, input_type)

        intake = intake_context(self._user, context, {}, prepared if is_record else None)
        llm_config = await self._resolver.resolve(self._user, requested_model=model)
        graph = build_advisor_graph(self._db, get_checkpointer(), llm_config)

        # Invoke the graph with initial state
        await self._invoke(
            graph,
            llm_config,
            {
                "messages": [HumanMessage(content=prepared)],
                **intake,
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

                "planning_requested": bool(intake.get("raw_sols")),
                "conversation_mode": "collecting",
                "current_stage": None,
            },
            {"configurable": {"thread_id": str(session_id)}},
        )

        state = await graph.aget_state({"configurable": {"thread_id": str(session_id)}})
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
        return session, reply

    async def continue_session(
        self, session_id: uuid.UUID, user_message: str, *, model: str | None = None,
        context: ChatContext | None = None,
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

        prepared, is_record = prepare_first_message(user_message, "question")
        payload = {
            **intake_context(self._user, context, state.values, prepared if is_record else None),
            "messages": [HumanMessage(content=prepared)],
        }
        if is_record or (context and context.enrolment_record is not None):
            payload.update(planning_requested=True, plan=None)
        await self._invoke(graph, llm_config, payload, config)

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
        if "raw_sols" not in state.values:
            raise SessionNotFound(
                f"Session {session_id} has no conversation state — it may be stale or was never started"
            )

        messages = await build_history(graph, str(session_id), fallback_model=session.model)
        return session, messages

    async def _owned_session(self, session_id: uuid.UUID) -> ChatSession:
        session = await self._db.get(ChatSession, session_id)
        # Sessions predating logins have user_id NULL: unreadable, because we
        # cannot prove whose they are. Same 404 either way — holding a session
        # UUID must not confirm that it exists.
        if session is None or session.user_id != self._user.id:
            raise SessionNotFound(f"Session {session_id} not found")
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
