"""Model → provider resolution, and honest pricing."""
import pytest
from app.llm.config import LLMConfig
from app.llm.keyshape import identify, mismatch_reason
from app.llm.pricing import compute_cost
from app.llm.registry import (
    DEFAULT_MODEL_BY_PROVIDER,
    MODELS,
    Provider,
    UnknownModelError,
    provider_for,
)

pytestmark = pytest.mark.smoke


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gemini-3.5-flash", Provider.GEMINI),
        ("claude-opus-5", Provider.ANTHROPIC),
        ("gpt-5.1", Provider.OPENAI),
    ],
)
def test_registered_models_resolve(model, expected) -> None:
    assert provider_for(model) is expected


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gemini-9-ultra", Provider.GEMINI),
        ("claude-something-new", Provider.ANTHROPIC),
        ("gpt-7", Provider.OPENAI),
    ],
)
def test_unregistered_models_still_resolve_by_prefix(model, expected) -> None:
    """A model released after this file was last edited must still be usable."""
    assert provider_for(model) is expected


def test_a_name_we_cannot_place_is_an_error() -> None:
    with pytest.raises(UnknownModelError):
        provider_for("llama-3-70b")


def test_every_provider_has_a_default_model_that_maps_back() -> None:
    for provider, model in DEFAULT_MODEL_BY_PROVIDER.items():
        assert provider_for(model) is provider


def test_registered_model_names_match_their_keys() -> None:
    assert all(name == spec.name for name, spec in MODELS.items())


def test_cost_uses_the_answering_model_not_a_global_rate() -> None:
    gemini = compute_cost(1_000_000, 1_000_000, 0, model="gemini-3.5-flash")
    claude = compute_cost(1_000_000, 1_000_000, 0, model="claude-opus-5")
    assert gemini == pytest.approx(0.375)
    assert claude == pytest.approx(30.0)


def test_cached_tokens_are_cheaper() -> None:
    full = compute_cost(1_000_000, 0, 0, model="claude-opus-5")
    cached = compute_cost(1_000_000, 0, 1_000_000, model="claude-opus-5")
    assert cached < full


@pytest.mark.parametrize(
    ("tokens_in", "tokens_out", "model"),
    [(100, 100, "gpt-5.1"), (100, 100, None), (None, 100, "claude-opus-5")],
    ids=["unpriced-model", "no-model", "no-usage"],
)
def test_no_rates_means_no_number_rather_than_a_wrong_one(tokens_in, tokens_out, model) -> None:
    assert compute_cost(tokens_in, tokens_out, 0, model=model) is None


# ── paste-error detection ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("sk-ant-api03-xxxx", Provider.ANTHROPIC),
        ("AIzaSyD-xxxxxxxx", Provider.GEMINI),
        ("sk-proj-xxxxxxxx", Provider.OPENAI),
        ("sk-xxxxxxxxxxxx", Provider.OPENAI),
        ("totally-opaque-token", None),
    ],
)
def test_identify_key_provider(key, expected) -> None:
    assert identify(key) is expected


def test_a_key_for_the_wrong_provider_is_caught_before_the_network_call() -> None:
    reason = mismatch_reason(Provider.OPENAI, "sk-ant-api03-xxxx")
    assert reason and "Anthropic" in reason


def test_an_unrecognisable_key_is_left_to_live_verification() -> None:
    assert mismatch_reason(Provider.OPENAI, "totally-opaque-token") is None


# ── the key must not leak through a repr ──────────────────────────────────────


def test_llm_config_never_prints_the_key() -> None:
    config = LLMConfig(provider=Provider.GEMINI, model="gemini-3.5-flash", api_key="AIza-secret")
    assert "AIza-secret" not in repr(config)
    assert "AIza-secret" not in f"{config}"
    assert "AIza-secret" not in str(config)
