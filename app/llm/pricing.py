"""Per-model token pricing.

Rates live in app/llm/registry.py next to the model they belong to, so adding a
model and pricing it is one edit. A model with no published rate returns None
rather than being costed with some other model's numbers — the UI then shows no
cost, which is honest, instead of a confidently wrong one.
"""
from app.llm.registry import pricing_for


def compute_cost(
    tokens_in: int | None,
    tokens_out: int | None,
    cached_tokens: int = 0,
    *,
    model: str | None = None,
) -> float | None:
    """USD for one call, or None when we have no rates for ``model``."""
    pricing = pricing_for(model)
    if pricing is None or tokens_in is None or tokens_out is None:
        return None

    cached = min(cached_tokens or 0, tokens_in)
    cost = (
        (tokens_in - cached) * pricing.input
        + cached * pricing.cached_input
        + tokens_out * pricing.output
    )
    return round(cost, 8)
