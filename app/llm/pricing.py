"""Gemini token pricing, shared by GeminiLLM (direct google-genai path) and the
LangGraph agent path (which reads cost back out of AIMessage.usage_metadata
instead of a raw API response)."""

# Gemini 2.0 Flash pricing (USD per token)
INPUT_COST_PER_TOKEN = 0.075 / 1_000_000
OUTPUT_COST_PER_TOKEN = 0.30 / 1_000_000
CACHED_COST_PER_TOKEN = 0.01875 / 1_000_000


def compute_cost(tokens_in: int, tokens_out: int, cached_tokens: int = 0) -> float:
    cost = (
        (tokens_in - cached_tokens) * INPUT_COST_PER_TOKEN
        + cached_tokens * CACHED_COST_PER_TOKEN
        + tokens_out * OUTPUT_COST_PER_TOKEN
    )
    return round(cost, 8)
