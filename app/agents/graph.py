"""LangGraph state graph for the advisor agent.

Replaces ChatService's fixed parse -> fetch -> prompt pipeline with an
explicit graph: parse_input (conditional) -> agent (tool-calling) -> tools,
looping until the agent stops requesting tools.

Conversation state (messages, parsed meta, handbook) is persisted by the
Postgres checkpointer passed into build_advisor_graph(), keyed by thread_id.
Our own Alembic-managed tables (chat_session, chat_message, handbook, ...)
are untouched by this and still own domain data + API-facing history.
"""
import json
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.skills import build_skills
from app.core.config import settings
from app.prompts.builder import build_system_prompt
from app.services.sols_parser import meta_is_complete, parse_sols


class AdvisorState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    raw_sols: str
    # plain dict (SOLSMeta.model_dump()), not the pydantic model itself — the
    # checkpointer's msgpack serializer only supports plain JSON-ish types and
    # warns (soon: errors) on arbitrary custom classes.
    meta: dict | None
    meta_confirmed: bool
    handbook: str | None


def _make_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
    )


def build_advisor_graph(db: AsyncSession, checkpointer: BaseCheckpointSaver):
    """Compile the advisor StateGraph, bound to a DB session for its skills.

    `checkpointer` persists AdvisorState per thread_id, so callers only ever
    need to supply the *new* message(s) for a turn — not the full history.
    """
    skills = build_skills(db)
    parser_llm = _make_llm()
    confirm_llm = _make_llm().bind_tools(skills["confirm"])
    full_llm = _make_llm().bind_tools(skills["full"])

    async def parse_input(state: AdvisorState) -> dict:
        if state.get("meta") is not None:
            return {}
        meta = await parse_sols(parser_llm, state["raw_sols"])
        data = meta.model_dump()
        return {"meta": data, "meta_confirmed": meta_is_complete(data)}

    async def agent(state: AdvisorState) -> dict:
        confirmed = state.get("meta_confirmed", False)
        agent_llm = full_llm if confirmed else confirm_llm

        system_content = build_system_prompt(
            meta=state["meta"],
            meta_confirmed=confirmed,
            handbook=state.get("handbook"),
            raw_sols=state["raw_sols"],
        )
        response = await agent_llm.ainvoke(
            [SystemMessage(content=system_content), *state["messages"]]
        )
        return {"messages": [response]}

    def should_continue(state: AdvisorState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    def capture_tool_results(state: AdvisorState) -> dict:
        """Cache fetch_handbook_tool's result into state.handbook, and
        confirm_metadata_tool's result into state.meta/meta_confirmed, so
        later turns reuse them instead of re-deriving them every time."""
        updates: dict = {}
        for message in reversed(state["messages"]):
            if not isinstance(message, ToolMessage):
                break  # only the most recent batch of tool results
            if message.name == "fetch_handbook_tool" and "handbook" not in updates:
                updates["handbook"] = message.content
            if message.name == "confirm_metadata_tool" and "meta_confirmed" not in updates:
                updates["meta"] = json.loads(message.content)
                updates["meta_confirmed"] = True
        return updates

    graph = StateGraph(AdvisorState)
    graph.add_node("parse_input", parse_input)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(skills["full"]))
    graph.add_node("capture_tool_results", capture_tool_results)

    graph.set_entry_point("parse_input")
    graph.add_edge("parse_input", "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "capture_tool_results")
    graph.add_edge("capture_tool_results", "agent")

    return graph.compile(checkpointer=checkpointer)
