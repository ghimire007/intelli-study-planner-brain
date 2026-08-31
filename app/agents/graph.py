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

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.skills import build_skills
from app.llm.config import LLMConfig
from app.llm.factory import make_chat_model
from app.prompts.builder import build_system_prompt
from app.services.sols_parser import parse_sols


class AdvisorState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    raw_sols: str
    # plain dict (SOLSMeta.model_dump()), not the pydantic model itself — the
    # checkpointer's msgpack serializer only supports plain JSON-ish types and
    # warns (soon: errors) on arbitrary custom classes.
    meta: dict | None
    meta_confirmed: bool
    handbook: str | None


def apply_confirm_metadata(prior_meta: dict | None, new_meta: dict) -> dict:
    """Apply confirmed meta; clear handbook when degree/year/campus change.

    Mid-chat degree (or year/campus) switches must invalidate the cached
    handbook so the next turn re-fetches rules for the new program.
    Major may be stored on meta but does not by itself clear the handbook.
    """
    updates: dict = {"meta": new_meta, "meta_confirmed": True}
    old = prior_meta or {}
    if (
        old.get("degree_code") != new_meta.get("degree_code")
        or old.get("year") != new_meta.get("year")
        or old.get("campus") != new_meta.get("campus")
    ):
        updates["handbook"] = None
    return updates


def fold_tool_results(state: AdvisorState, batch: list[ToolMessage]) -> dict:
    """Fold a chronological tool-result batch into AdvisorState updates.

    Confirm/switch runs before fetch in the same turn so a cleared handbook
    can be replaced by a freshly fetched one without being wiped again.
    """
    updates: dict = {}
    for message in batch:
        if message.name == "confirm_metadata_tool":
            prior = updates.get("meta", state.get("meta"))
            updates.update(apply_confirm_metadata(prior, json.loads(message.content)))
        elif message.name == "fetch_handbook_tool":
            updates["handbook"] = message.content
    return updates


def build_advisor_graph(
    db: AsyncSession,
    checkpointer: BaseCheckpointSaver,
    llm_config: LLMConfig | None = None,
):
    """Compile the advisor StateGraph, bound to a DB session for its skills.

    `checkpointer` persists AdvisorState per thread_id, so callers only ever
    need to supply the *new* message(s) for a turn — not the full history.

    `llm_config` carries the student's own decrypted API key. It is held in this
    closure for the life of the request and deliberately never written into
    AdvisorState: the checkpointer msgpacks state into Postgres after every step,
    so a key placed there would be persisted in the clear. Pass None for
    read-only work (history, state inspection) — no model is then constructed.
    """
    skills = build_skills(db)
    models: dict[str, BaseChatModel] = {}

    def llm(kind: str) -> BaseChatModel:
        """Build a chat model on first use, so a read-only graph needs no key."""
        if kind not in models:
            if llm_config is None:
                raise RuntimeError(
                    "This graph was built without an LLM config — it can read "
                    "checkpointed state but cannot call a model"
                )
            base = make_chat_model(llm_config)
            models[kind] = base if kind == "parser" else base.bind_tools(skills[kind])
        return models[kind]

    async def parse_input(state: AdvisorState) -> dict:
        if state.get("meta") is not None:
            return {}
        meta = await parse_sols(llm("parser"), state["raw_sols"])
        data = meta.model_dump()
        # Never auto-confirm: the agent must ask the student (one question) and
        # call confirm_metadata_tool, even if the parser extracted candidate values.
        return {"meta": data, "meta_confirmed": False}

    async def agent(state: AdvisorState) -> dict:
        confirmed = state.get("meta_confirmed", False)
        agent_llm = llm("full") if confirmed else llm("confirm")

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
        """Update AdvisorState with the latest tool results.

        Processes tools in chronological order so a confirm/switch that
        clears ``handbook`` can be followed by a fresh ``fetch_handbook_tool``
        in the same turn without the clear wiping the new cache.
        """
        batch: list[ToolMessage] = []
        for message in reversed(state["messages"]):
            if not isinstance(message, ToolMessage):
                break  # only the most recent batch of tool results
            batch.append(message)
        batch.reverse()
        return fold_tool_results(state, batch)

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
