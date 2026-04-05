from google import genai
from google.genai import types

from app.core.config import settings
from app.llm.base import BaseLLM, LLMMessage, LLMResponse

# Gemini 2.0 Flash pricing (USD per token)
_INPUT_COST_PER_TOKEN = 0.075 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 0.30 / 1_000_000
_CACHED_COST_PER_TOKEN = 0.01875 / 1_000_000


class GeminiLLM(BaseLLM):
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    @property
    def model_name(self) -> str:
        return settings.GEMINI_MODEL

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def chat(self, system_prompt: str, messages: list[LLMMessage]) -> LLMResponse:
        # Gemini uses "model" instead of "assistant"
        role_map = {"user": "user", "assistant": "model"}
        contents = [
            types.Content(
                role=role_map.get(msg.role, msg.role),
                parts=[types.Part(text=msg.content)],
            )
            for msg in messages
        ]

        response = await self._client.aio.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
            ),
        )

        usage = response.usage_metadata
        tokens_in = usage.prompt_token_count or 0
        tokens_out = usage.candidates_token_count or 0
        cached = usage.cached_content_token_count or 0

        cost = (
            (tokens_in - cached) * _INPUT_COST_PER_TOKEN
            + cached * _CACHED_COST_PER_TOKEN
            + tokens_out * _OUTPUT_COST_PER_TOKEN
        )

        # Build structured parts list from all candidate parts
        raw_parts = response.candidates[0].content.parts if response.candidates else []
        parts = []
        text_chunks = []
        for part in raw_parts:
            if part.text:
                parts.append({"type": "text", "text": part.text})
                text_chunks.append(part.text)
            elif part.function_call:
                parts.append({
                    "type": "function_call",
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args),
                })
            elif part.function_response:
                parts.append({
                    "type": "function_response",
                    "name": part.function_response.name,
                    "response": dict(part.function_response.response),
                })

        return LLMResponse(
            content=" ".join(text_chunks),
            parts=parts,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_tokens=cached,
            cost_usd=round(cost, 8),
            model=self.model_name,
            provider=self.provider_name,
        )
