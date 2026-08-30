"""A cheap sanity check on a pasted key, before we spend a network call on it.

Deliberately permissive: prefixes change, and a live verification follows anyway.
The one thing worth rejecting outright is a key that clearly belongs to a
*different* provider than the one selected — by far the most common paste error,
and the one whose provider error message ("invalid x-api-key") explains least.
"""
from app.llm.registry import PROVIDER_LABELS, Provider

#: Prefixes distinctive enough to identify a key's provider on sight.
_SIGNATURES: tuple[tuple[str, Provider], ...] = (
    ("sk-ant-", Provider.ANTHROPIC),
    ("AIza", Provider.GEMINI),
    ("sk-proj-", Provider.OPENAI),
    ("sk-", Provider.OPENAI),  # after sk-ant-/sk-proj-: least specific wins last
)


def identify(api_key: str) -> Provider | None:
    """The provider a key's prefix points at, or None when it isn't recognisable."""
    key = api_key.strip()
    for prefix, provider in _SIGNATURES:
        if key.startswith(prefix):
            return provider
    return None


def mismatch_reason(provider: Provider, api_key: str) -> str | None:
    """An error message when the key visibly belongs to another provider, else None."""
    looks_like = identify(api_key)
    if looks_like is None or looks_like is provider:
        return None
    return (
        f"That looks like a {PROVIDER_LABELS[looks_like]} key, but you chose "
        f"{PROVIDER_LABELS[provider]}. Pick the matching provider, or paste the "
        f"{PROVIDER_LABELS[provider]} key."
    )
