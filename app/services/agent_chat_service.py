import uuid

from datetime import datetime, UTC

import json

from app.agents.graphAPI import build_advisor_graph
from app.agents.history import MessageView, build_history, latest_reply
from app.core.checkpointer import get_checkpointer
from app.llm.config import LLMConfig
from app.llm.errors import ProviderFailure, classify
from app.llm.registry import PROVIDER_LABELS
from app.models.auth import User
from app.models.session import ChatSession
from app.services.credential_resolver import CredentialResolver
from app.services.enrolment import project
from app.services.pii import scrub_pii
from app.services.vault_service import VaultService
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession
from app.llm.factory import make_chat_model


from app.services.enrolment import UnreadableRecord

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
        self, raw_sols: str, *, model: str | None = None
    ) -> tuple[ChatSession, MessageView]:
        session_id = uuid.uuid4()
        
        # Project the paste onto its allowlisted fields before anything is
        # persisted or sent to a provider. The paste itself stops here: only
        # `projected` travels, and an unreadable one raises UnreadableRecord
        # rather than falling back to the raw text. The state key stays
        # `raw_sols` so existing checkpoints keep loading.
        # projected = project(raw_sols)

        cleaned_sols = raw_sols.strip() if raw_sols else ""

        print("start session beginning, cleaned_sols:", cleaned_sols, ".")

        projected_sols: str | None = None
        initial_messages = []
        planning_requested = False

        # Evaluate SOLS input if provided
        if cleaned_sols:
            print("sols detected")
            protected_sols = scrub_pii(raw_sols)
            try:
                # Parse and format into clean allowlisted Markdown
                projected_sols = project(protected_sols)
                initial_messages.append(HumanMessage(content=projected_sols))
                planning_requested = True
            except UnreadableRecord:
                # Re-raise so API returns 422 if an explicit SOLS paste was invalid
                print("this is the error")
                raise

        else:
            print("NO SOLS")
            projected_sols = "no enrolment yet"
            initial_messages.append(HumanMessage(content="Hello"))
            planning_requested = False

        llm_config = await self._resolver.resolve(self._user, requested_model=model)
        graph = build_advisor_graph(self._db, get_checkpointer(), llm_config)

        # Invoke the graph with initial state
        await self._invoke(
            graph,
            llm_config,
            {
                "messages": initial_messages,
                "raw_sols": projected_sols,
                "meta": None,
                "meta_confirmed": False,
                "handbook": None,
                "electives": None,
                "remaining_subjects": None,
                "electives_feedback": None,
                "remaining_feedback": None,
                "plan": None,
                "plan_feedback": None,
                "retry_count": None,
                "stage1_retry_count": None,
                "planning_requested": planning_requested,
                "current_stage": None,
            },
            {"configurable": {"thread_id": str(session_id)}},
        )

        state = await graph.aget_state({"configurable": {"thread_id": str(session_id)}})
        meta = state.values.get("meta") or {}

        # Handle fallback for missing degree_code
        degree_code = meta.get("degree_code") or "UNKNOWN"

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
        self, session_id: uuid.UUID, user_message: str, *, model: str | None = None
    ) -> MessageView:
        session = await self._owned_session(session_id)

        llm_config = await self._resolver.resolve(
            self._user, requested_model=model, session=session
        )
        graph = build_advisor_graph(self._db, get_checkpointer(), llm_config)
        config = {"configurable": {"thread_id": str(session_id)}}

        protected_message = scrub_pii(user_message)
        payload = {"messages": [HumanMessage(content=protected_message)]}

        try:
            projected = project(protected_message)
            # If valid SOLS, update the SOLS payload forcing reset of advisor metadata
            payload["raw_sols"] = projected
            payload["messages"] = [HumanMessage(content=projected)]
            payload["planning_requested"] = True
            payload["plan"] = None
        except Exception:
            # Standard chat turn — keep the default message payload
            pass

        await self._invoke(graph, llm_config, payload, config)

        state = await graph.aget_state(config)
        print("STATE VALUES:", state.values)
        print("SESSION ID:", session_id)

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
        session, messages = await self.get_history(session_id)
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
