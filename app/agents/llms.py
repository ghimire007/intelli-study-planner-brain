"""Per-request chat model cache for the advisor graph."""
from langchain_core.language_models import BaseChatModel

from app.llm.config import LLMConfig
from app.llm.factory import make_chat_model


class LLMRegistry:
    """Lazily build and cache one chat model per role ("parser", "confirm", "full").

    `llm_config` carries the student's own decrypted API key. It lives only in
    this object, which the graph holds for the life of one request, and is
    never written into AdvisorState: the checkpointer msgpacks state into
    Postgres after every step. A registry built with None can serve read-only
    graphs (history, state inspection) and raises if a node asks for a model.
    """

    def __init__(self, llm_config: LLMConfig | None, tools_by_kind: dict[str, list]) -> None:
        self._config = llm_config
        self._tools = tools_by_kind
        self._models: dict[str, BaseChatModel] = {}

    def get(self, kind: str) -> BaseChatModel:
        if kind not in self._models:
            if self._config is None:
                raise RuntimeError("Graph was created without an LLM config.")
            base = make_chat_model(self._config)
            tools = self._tools.get(kind)
            model = base.bind_tools(tools) if tools else base
            self._models[kind] = model.with_retry(
                wait_exponential_jitter=True,
                stop_after_attempt=2,
            )
        return self._models[kind]
