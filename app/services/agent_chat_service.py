import uuid

from app.agents.graph import build_advisor_graph
from app.agents.history import MessageView, build_history, latest_reply
from app.core.checkpointer import get_checkpointer
from app.models.session import ChatSession
from app.services.pii import scrub_pii
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession


class AgentChatService:
    """LangGraph-backed equivalent of ChatService, exposing the same public API.

    Everything conversational — messages, parsed SOLS meta, handbook, per-message
    cost/token metadata — lives entirely in the LangGraph Postgres checkpointer,
    keyed by thread_id = str(session.id). We keep no ChatMessage rows: history
    and cost accounting are both reconstructed from checkpoint state on read
    (see app/agents/history.py). ChatSession itself stays — it's the thin,
    indexable row that lets us query/list sessions by degree_code and gives the
    API something to 404 against before a thread necessarily has any state.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def start_session(self, raw_sols: str) -> tuple[ChatSession, MessageView]:
        session_id = uuid.uuid4()
        # Redact name/student-number/contact PII before anything is persisted or
        # sent to the LLM; grades stay (needed to tell completed from enrolled).
        raw_sols = scrub_pii(raw_sols)
        graph = build_advisor_graph(self._db, get_checkpointer())
        await graph.ainvoke(
            {
                "messages": [HumanMessage(content=raw_sols)],
                "raw_sols": raw_sols,
                "meta": None,
                "meta_confirmed": False,
                "handbook": None,
            },
            config={"configurable": {"thread_id": str(session_id)}},
        )

        state = await graph.aget_state({"configurable": {"thread_id": str(session_id)}})
        meta = state.values["meta"]

        # degree_code may be None until the student supplies it (see meta_is_complete) —
        # ChatSession.degree_code is just an indexable label, not the source of truth.
        session = ChatSession(id=session_id, degree_code=meta["degree_code"] or "UNKNOWN")
        self._db.add(session)
        await self._db.commit()

        reply = await latest_reply(graph, str(session_id))
        return session, reply

    async def continue_session(self, session_id: uuid.UUID, user_message: str) -> MessageView:
        session = await self._db.get(ChatSession, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        graph = build_advisor_graph(self._db, get_checkpointer())
        config = {"configurable": {"thread_id": str(session_id)}}
        state = await graph.aget_state(config)
        if "raw_sols" not in state.values:
            raise ValueError(
                f"Session {session_id} has no conversation state — it may be stale or was never started"
            )

        await graph.ainvoke(
            {"messages": [HumanMessage(content=user_message)]},
            config=config,
        )

        return await latest_reply(graph, str(session_id))

    async def get_history(self, session_id: uuid.UUID) -> tuple[ChatSession, list[MessageView]]:
        session = await self._db.get(ChatSession, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        graph = build_advisor_graph(self._db, get_checkpointer())
        state = await graph.aget_state({"configurable": {"thread_id": str(session_id)}})
        if "raw_sols" not in state.values:
            raise ValueError(
                f"Session {session_id} has no conversation state — it may be stale or was never started"
            )

        messages = await build_history(graph, str(session_id))
        return session, messages
