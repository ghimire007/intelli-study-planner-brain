"""Build a LangChain chat model for whichever provider the student's key belongs to.

Provider packages are imported lazily so the app still boots — and every other
provider still works — when one of them isn't installed.
"""
from langchain_core.language_models import BaseChatModel

from app.llm.config import LLMConfig
from app.llm.registry import PROVIDER_LABELS, Provider

_INSTALL_HINT = {
    Provider.GEMINI: "langchain-google-genai",
    Provider.ANTHROPIC: "langchain-anthropic",
    Provider.OPENAI: "langchain-openai",
}


class ProviderNotInstalled(RuntimeError):
    """The package backing a provider is missing from this deployment."""


def make_chat_model(config: LLMConfig) -> BaseChatModel:
    """A chat model bound to one student's key. Never cache these across users."""
    try:
        if config.provider is Provider.GEMINI:
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(model=config.model, google_api_key=config.api_key)

        if config.provider is Provider.ANTHROPIC:
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(model=config.model, api_key=config.api_key)

        if config.provider is Provider.OPENAI:
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model=config.model, api_key=config.api_key)
    except ImportError as exc:
        raise ProviderNotInstalled(
            f"{PROVIDER_LABELS[config.provider]} support needs "
            f"`pip install {_INSTALL_HINT[config.provider]}`"
        ) from exc

    raise ValueError(f"No chat model wired up for provider {config.provider!r}")
