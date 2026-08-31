"""Reconstruct user-facing chat history straight from the LangGraph checkpointer —
no ChatMessage table involved. Per-message cost/token metadata comes from
AIMessage.usage_metadata / response_metadata, which every LangChain chat model
populates on each call.

A thread can span providers (a student may switch models mid-conversation), so
provider and cost are derived per message from the model that actually answered,
falling back to the session's current model for older messages that predate
response_metadata carrying one.
"""
from dataclasses import dataclass
from datetime import datetime

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph

from app.llm.pricing import compute_cost
from app.llm.registry import UnknownModelError, provider_for
from app.llm.text import as_text


@dataclass
class MessageView:
    """Duck-types ChatMessage's public attributes so MessageOut(from_attributes=True) still works."""
    id: int
    role: str
    content: str
    created_at: datetime
    provider: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | None = None


def _provider_of(model: str | None) -> str | None:
    if not model:
        return None
    try:
        return provider_for(model).value
    except UnknownModelError:
        return None


def _to_view(
    message: BaseMessage,
    created_at: datetime,
    idx: int,
    fallback_model: str | None = None,
) -> MessageView | None:
    if isinstance(message, HumanMessage):
        return MessageView(id=idx, role="user", content=as_text(message.content), created_at=created_at)

    if isinstance(message, AIMessage):
        content = as_text(message.content)
        if not content:
            return None  # tool-call-only turn — internal plumbing, not user-facing
        usage = message.usage_metadata or {}
        tokens_in = usage.get("input_tokens")
        tokens_out = usage.get("output_tokens")
        cached = (usage.get("input_token_details") or {}).get("cache_read", 0)
        model = message.response_metadata.get("model_name") or fallback_model
        return MessageView(
            id=idx,
            role="assistant",
            content=content,
            created_at=created_at,
            provider=_provider_of(model),
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_tokens=cached or None,
            cost_usd=compute_cost(tokens_in, tokens_out, cached, model=model),
        )

    return None  # ToolMessage etc. — internal plumbing, not user-facing


async def build_history(
    graph: CompiledStateGraph, thread_id: str, fallback_model: str | None = None
) -> list[MessageView]:
    """Walk every checkpoint for this thread oldest-to-newest, diffing the messages
    list at each step so each message gets the timestamp of the turn that produced it.
    """
    config = {"configurable": {"thread_id": thread_id}}
    snapshots = [s async for s in graph.aget_state_history(config)]
    snapshots.reverse()  # aget_state_history yields newest-first

    views: list[MessageView] = []
    seen = 0
    idx = 0
    for snapshot in snapshots:
        messages = snapshot.values.get("messages", [])
        new_messages = messages[seen:]
        seen = len(messages)
        created_at = datetime.fromisoformat(snapshot.created_at)
        for message in new_messages:
            idx += 1
            view = _to_view(message, created_at, idx, fallback_model)
            if view is not None:
                views.append(view)
    return views


async def latest_reply(
    graph: CompiledStateGraph, thread_id: str, fallback_model: str | None = None
) -> MessageView:
    history = await build_history(graph, thread_id, fallback_model)
    return next(v for v in reversed(history) if v.role == "assistant")
