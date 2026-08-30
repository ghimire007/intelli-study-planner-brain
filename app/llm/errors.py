"""Classify a provider failure without importing every provider SDK.

Google, Anthropic and OpenAI all surface an HTTP status on their exceptions, but
under different attribute names, and LangChain wraps them a layer or two deep.
Walking the cause chain and reading whichever status attribute exists keeps this
working for a provider whose package isn't even installed.
"""
from enum import StrEnum

_STATUS_ATTRS = ("status_code", "code", "http_status")
_AUTH_STATUSES = {401, 403}

#: Google answers a bad key with 400 INVALID_ARGUMENT rather than 401 or 403, and
#: LangChain wraps that in an error carrying no status at all. Without matching on
#: the message, a student's wrong Gemini key reads as an unknown server fault
#: instead of "your key was rejected". Anthropic and OpenAI both use 401.
_BAD_KEY_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "invalid api key",
    "invalid_api_key",
    "api key expired",
    "api_key_expired",
    "invalid authentication",
)


class ProviderFailure(StrEnum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


def _status_of(exc: BaseException) -> int | None:
    for attr in _STATUS_ATTRS:
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    return None


def _says_the_key_is_bad(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _BAD_KEY_MARKERS)


def classify(exc: BaseException) -> ProviderFailure:
    """Walk the exception chain and report the first meaningful failure."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = _status_of(current)
        if status in _AUTH_STATUSES or _says_the_key_is_bad(current):
            return ProviderFailure.AUTH
        if status == 429:
            return ProviderFailure.RATE_LIMIT
        if status is not None and status >= 500:
            return ProviderFailure.UNAVAILABLE
        current = current.__cause__ or current.__context__
    return ProviderFailure.UNKNOWN
