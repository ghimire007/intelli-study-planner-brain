"""Prove a key works before we store it.

Cheapest call each provider offers is "list models" — no tokens billed, and it
fails loudly on a bad key. Doing this at write time means a typo surfaces on the
settings page instead of three turns into a conversation.
"""
from app.llm.errors import ProviderFailure, classify
from app.llm.registry import PROVIDER_LABELS, Provider


class KeyRejected(Exception):
    """The provider refused the key — it is wrong, revoked, or lacks permission."""


class VerificationUnavailable(Exception):
    """We could not reach the provider, so the key is neither proven nor disproven."""


async def verify_key(provider: Provider, api_key: str) -> None:
    """Return quietly if the key works; raise otherwise."""
    try:
        if provider is Provider.GEMINI:
            await _verify_gemini(api_key)
        elif provider is Provider.ANTHROPIC:
            await _verify_anthropic(api_key)
        elif provider is Provider.OPENAI:
            await _verify_openai(api_key)
        else:  # pragma: no cover - guarded by coerce_provider upstream
            raise VerificationUnavailable(f"No verifier for provider {provider!r}")
    except (KeyRejected, VerificationUnavailable):
        raise
    except ImportError as exc:
        raise VerificationUnavailable(
            f"{PROVIDER_LABELS[provider]} support is not installed on this server"
        ) from exc
    except Exception as exc:
        failure = classify(exc)
        if failure is ProviderFailure.AUTH:
            raise KeyRejected(
                f"{PROVIDER_LABELS[provider]} rejected this key."
            ) from exc
        if failure is ProviderFailure.RATE_LIMIT:
            raise VerificationUnavailable(
                f"{PROVIDER_LABELS[provider]} is rate limiting us — try saving again shortly."
            ) from exc
        raise VerificationUnavailable(
            f"Could not reach {PROVIDER_LABELS[provider]} to check this key."
        ) from exc


async def _verify_gemini(api_key: str) -> None:
    from google import genai

    client = genai.Client(api_key=api_key)
    pager = await client.aio.models.list(config={"page_size": 1})
    # The request is issued when the first page is fetched above; touching the
    # page keeps linters (and any future lazy pager) honest.
    _ = pager.page


async def _verify_anthropic(api_key: str) -> None:
    from anthropic import AsyncAnthropic

    async with AsyncAnthropic(api_key=api_key, max_retries=0) as client:
        await client.models.list(limit=1)


async def _verify_openai(api_key: str) -> None:
    from openai import AsyncOpenAI

    async with AsyncOpenAI(api_key=api_key, max_retries=0) as client:
        await client.models.list()
