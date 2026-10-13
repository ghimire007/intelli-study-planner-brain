"""The decision logic around the vault, isolated from the database."""
import uuid
from types import SimpleNamespace

import pytest
from app.core.ratelimit import RateLimiter
from app.llm.errors import ProviderFailure, classify
from app.llm.registry import Provider
from app.services.credential_resolver import CredentialResolver, NoCredentialError

pytestmark = pytest.mark.smoke


def credential(**kwargs):
    return SimpleNamespace(id=kwargs.pop("id", uuid.uuid4()), **kwargs)


# ── which of a student's keys gets picked ─────────────────────────────────────


def test_pinned_credential_wins_over_the_default() -> None:
    """A long conversation must not silently change key when the default moves."""
    default = credential()
    pinned = credential()
    session = SimpleNamespace(credential_id=pinned.id)

    chosen = CredentialResolver._choose([default, pinned], session)
    assert chosen is pinned


def test_falls_back_to_the_default_when_the_pinned_key_is_gone() -> None:
    session = SimpleNamespace(credential_id=uuid.uuid4())  # deleted since
    default = credential()
    assert CredentialResolver._choose([default], session) is default


def test_first_candidate_wins_without_a_session() -> None:
    first, second = credential(), credential()
    assert CredentialResolver._choose([first, second], None) is first


def test_no_candidates_means_no_choice() -> None:
    assert CredentialResolver._choose([], None) is None


# ── the message a student sees when there is no key ───────────────────────────


def test_missing_key_message_names_the_provider() -> None:
    error = NoCredentialError(Provider.ANTHROPIC)
    assert "Anthropic" in str(error)
    assert "settings" in str(error)


def test_a_rejected_key_gets_a_different_message_than_a_missing_one() -> None:
    missing = str(NoCredentialError(Provider.OPENAI))
    rejected = str(NoCredentialError(Provider.OPENAI, invalid_only=True))
    assert missing != rejected
    assert "rejected" in rejected


# ── provider failures, without importing three SDKs ───────────────────────────


class FakeProviderError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"http {status_code}")
        self.status_code = status_code


class FakeGoogleError(Exception):
    """google-genai reports its HTTP status on `.code`, not `.status_code`."""

    def __init__(self, code: int) -> None:
        super().__init__(f"http {code}")
        self.code = code


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (FakeProviderError(401), ProviderFailure.AUTH),
        (FakeProviderError(403), ProviderFailure.AUTH),
        (FakeGoogleError(403), ProviderFailure.AUTH),
        (FakeProviderError(429), ProviderFailure.RATE_LIMIT),
        (FakeProviderError(503), ProviderFailure.UNAVAILABLE),
        (ValueError("something of ours broke"), ProviderFailure.UNKNOWN),
    ],
)
def test_classify_reads_whichever_status_attribute_exists(exc, expected) -> None:
    assert classify(exc) is expected


def test_classify_unwraps_langchain_style_nesting() -> None:
    """LangChain wraps the SDK error a layer or two deep."""
    try:
        try:
            raise FakeProviderError(401)
        except FakeProviderError as inner:
            raise RuntimeError("chat model call failed") from inner
    except RuntimeError as wrapped:
        assert classify(wrapped) is ProviderFailure.AUTH


def test_classify_terminates_on_a_self_referential_chain() -> None:
    first = ValueError("a")
    second = ValueError("b")
    first.__cause__ = second
    second.__cause__ = first
    assert classify(first) is ProviderFailure.UNKNOWN


# ── the oracle guard ──────────────────────────────────────────────────────────


def test_rate_limiter_stops_at_the_limit() -> None:
    limiter = RateLimiter(limit=3, window_seconds=3600)
    assert [limiter.allow("user-a") for _ in range(4)] == [True, True, True, False]


def test_rate_limits_are_per_user() -> None:
    limiter = RateLimiter(limit=1, window_seconds=3600)
    assert limiter.allow("user-a") is True
    assert limiter.allow("user-b") is True
    assert limiter.allow("user-a") is False


def test_reset_clears_one_user() -> None:
    limiter = RateLimiter(limit=1, window_seconds=3600)
    limiter.allow("user-a")
    limiter.reset("user-a")
    assert limiter.allow("user-a") is True


# ── user-facing copy ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        (Provider.GEMINI, "Add a Google Gemini API key"),
        (Provider.ANTHROPIC, "Add an Anthropic Claude API key"),
        (Provider.OPENAI, "Add an OpenAI API key"),
    ],
)
def test_the_missing_key_message_reads_like_english(provider, expected) -> None:
    assert str(NoCredentialError(provider)).startswith(expected)


# ── where a credential's secret lives ─────────────────────────────────────────


def test_a_row_with_no_backend_recorded_is_local() -> None:
    """Rows written before the backend column existed are locally sealed."""
    from app.services.secret_store import LOCAL, store_for

    assert store_for(None).name == LOCAL
    assert store_for("").name == LOCAL
    assert store_for("local").name == LOCAL


def test_an_unknown_backend_is_refused_rather_than_guessed() -> None:
    from app.services.secret_store import SecretStoreError, store_for

    with pytest.raises(SecretStoreError, match="Unknown secret backend"):
        store_for("hashicorp")


def test_secret_name_is_a_legal_infisical_key() -> None:
    """Infisical keys are [A-Z0-9_] — a bare UUID's hyphens would be rejected."""
    import re

    from app.services.infisical_store import secret_name

    name = secret_name(uuid.UUID("2e1482ff-b605-4a70-88a0-854613742f15"))
    assert name == "LLM_CRED_2E1482FFB6054A7088A0854613742F15"
    assert re.fullmatch(r"[A-Z0-9_]+", name)


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        # The regression: Infisical reports a repeat create as 400 with a message,
        # not the 409 the status code would imply. Matching on status alone made
        # every rotation fail with "Secret already exists".
        (400, {"message": "Secret already exists"}, True),
        (409, {"message": "Secret already exists"}, True),
        (400, {"message": "secret already exists"}, True),
        (400, {"message": "Invalid workspace id"}, False),
        (403, {"message": "Secret already exists"}, False),
        (200, {}, False),
    ],
)
def test_only_a_genuine_clash_turns_a_create_into_an_update(status, payload, expected) -> None:
    from app.services.infisical_store import _already_exists

    assert _already_exists(status, payload) is expected


# ── the project's own key as a last resort ────────────────────────────────────


def test_the_system_fallback_is_on_by_default() -> None:
    """A student who has added nothing can still use the advisor."""
    from app.core.config import Settings

    assert Settings().ALLOW_SYSTEM_FALLBACK_KEY is True


def test_the_fallback_only_covers_gemini() -> None:
    """It is the one provider we hold a key for, so it is the only one we can lend."""
    from app.core.config import Settings
    from app.llm.registry import DEFAULT_MODEL_BY_PROVIDER, provider_for

    settings = Settings()
    assert provider_for(settings.GEMINI_MODEL) is Provider.GEMINI
    # Asking for another provider by name still needs the student's own key.
    assert provider_for(DEFAULT_MODEL_BY_PROVIDER[Provider.ANTHROPIC]) is Provider.ANTHROPIC


def test_a_students_own_key_outranks_the_fallback() -> None:
    """The fallback is the last rung: any active credential wins over it."""
    own = credential()
    assert CredentialResolver._choose([own], None) is own
    assert CredentialResolver._choose([], None) is None  # only then does the ladder fall through


class FakeGoogleBadKey(Exception):
    """Google answers an invalid key with 400 INVALID_ARGUMENT, not 401."""

    def __init__(self) -> None:
        super().__init__(
            "400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': "
            "'API key not valid. Please pass a valid API key.', "
            "'status': 'INVALID_ARGUMENT'}}"
        )
        self.code = 400


def test_a_bad_gemini_key_is_auth_not_unknown() -> None:
    """The 400-not-401 case: it used to fall through and surface as a 500."""
    assert classify(FakeGoogleBadKey()) is ProviderFailure.AUTH


def test_the_langchain_wrapper_around_it_is_too() -> None:
    """ChatGoogleGenerativeAIError carries the message but no status at all."""
    try:
        try:
            raise FakeGoogleBadKey()
        except FakeGoogleBadKey as inner:
            raise RuntimeError(
                "Error calling model 'gemini-3.5-flash' (INVALID_ARGUMENT): 400 "
                "INVALID_ARGUMENT. API key not valid. Please pass a valid API key."
            ) from inner
    except RuntimeError as wrapped:
        assert classify(wrapped) is ProviderFailure.AUTH


def test_an_ordinary_400_is_still_not_an_auth_failure() -> None:
    """Only a message that actually names the key counts — 400 alone does not."""
    assert classify(FakeProviderError(400)) is ProviderFailure.UNKNOWN
