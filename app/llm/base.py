from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMMessage:
    role: str   # "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str        # joined plain text from all text parts
    parts: list         # full raw parts array (text, tool calls, tool responses)
    tokens_in: int
    tokens_out: int
    cached_tokens: int
    cost_usd: float
    model: str
    provider: str       # e.g. "gemini", "anthropic", "openai"


class BaseLLM(ABC):
    """
    Abstract base for all LLM providers.

    Contract:
    - system_prompt is passed separately (maps to provider's system instruction)
    - messages is the full conversation history in chronological order
    - Returns a structured LLMResponse with token counts and cost
    """

    @abstractmethod
    async def chat(self, system_prompt: str, messages: list[LLMMessage]) -> LLMResponse:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...
