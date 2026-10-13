"""Which models we support, who provides them, and what they cost.

An API key authenticates you to a **provider**, not a model — one Google key
serves every Gemini model — so ``provider_for`` is the lookup that turns the
model a student picked into the credential we need to load.

Adding a model is a one-line edit here. Unknown names still resolve by prefix so
a newly released model works before anyone updates this file; it just reports no
pricing, and the UI then shows no cost rather than a wrong one.
"""
from dataclasses import dataclass
from enum import StrEnum

PER_MILLION = 1 / 1_000_000


class Provider(StrEnum):
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class UnknownModelError(ValueError):
    """A model name we cannot map to any provider."""


@dataclass(frozen=True)
class Pricing:
    """USD per token."""

    input: float
    output: float
    cached_input: float


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: Provider
    label: str
    # None means "we don't have rates for this model" — cost is then reported as
    # unknown rather than guessed with another model's numbers.
    pricing: Pricing | None = None


def _per_million(input_: float, output: float, cached: float) -> Pricing:
    return Pricing(
        input=input_ * PER_MILLION,
        output=output * PER_MILLION,
        cached_input=cached * PER_MILLION,
    )


# Gemini rates below are the Gemini 2.0 Flash published rates this project has
# always billed against (they were the constants in the previous pricing.py).
# Verify them against ai.google.dev/pricing before quoting costs to students.
_GEMINI_FLASH = _per_million(0.075, 0.30, 0.01875)

PROVIDER_LABELS: dict[Provider, str] = {
    Provider.GEMINI: "Google Gemini",
    Provider.ANTHROPIC: "Anthropic Claude",
    Provider.OPENAI: "OpenAI",
}

#: Where each provider's key is issued — shown on the settings page.
PROVIDER_CONSOLE_URLS: dict[Provider, str] = {
    Provider.GEMINI: "https://aistudio.google.com/apikey",
    Provider.ANTHROPIC: "https://console.anthropic.com/settings/keys",
    Provider.OPENAI: "https://platform.openai.com/api-keys",
}

MODELS: dict[str, ModelSpec] = {
    spec.name: spec
    for spec in (
        # ── Google ────────────────────────────────────────────────────────────
        ModelSpec("gemini-3.5-flash", Provider.GEMINI, "Gemini 3.5 Flash", _GEMINI_FLASH),
        # Google may answer a gemini-3.5-flash request as -lite; it comes back in
        # response_metadata under this name. Listed so cost lookups find it —
        # unpriced until someone checks the published rate.
        ModelSpec("gemini-3.5-flash-lite", Provider.GEMINI, "Gemini 3.5 Flash Lite"),
        ModelSpec("gemini-2.5-flash", Provider.GEMINI, "Gemini 2.5 Flash", _GEMINI_FLASH),
        ModelSpec("gemini-2.5-pro", Provider.GEMINI, "Gemini 2.5 Pro"),
        ModelSpec("gemini-2.0-flash", Provider.GEMINI, "Gemini 2.0 Flash", _GEMINI_FLASH),
        # ── Anthropic ─────────────────────────────────────────────────────────
        ModelSpec(
            "claude-opus-5", Provider.ANTHROPIC, "Claude Opus 5", _per_million(5.00, 25.00, 0.50)
        ),
        ModelSpec(
            "claude-sonnet-5", Provider.ANTHROPIC, "Claude Sonnet 5", _per_million(2.00, 10.00, 0.20)
        ),
        ModelSpec(
            "claude-haiku-4-5", Provider.ANTHROPIC, "Claude Haiku 4.5", _per_million(1.00, 5.00, 0.10)
        ),
        # ── OpenAI ────────────────────────────────────────────────────────────
        # Left unpriced deliberately: fill in rates from the OpenAI pricing page
        # rather than shipping numbers nobody checked.
        ModelSpec("gpt-5.1", Provider.OPENAI, "GPT-5.1"),
        ModelSpec("gpt-5.1-mini", Provider.OPENAI, "GPT-5.1 mini"),
    )
}

#: What to reach for when a student has a key for a provider but named no model.
DEFAULT_MODEL_BY_PROVIDER: dict[Provider, str] = {
    Provider.GEMINI: "gemini-3.5-flash",
    Provider.ANTHROPIC: "claude-sonnet-5",
    Provider.OPENAI: "gpt-5.1",
}

#: Fallback for models released after this file was last edited.
_NAME_PREFIXES: tuple[tuple[str, Provider], ...] = (
    ("gemini", Provider.GEMINI),
    ("models/gemini", Provider.GEMINI),
    ("claude", Provider.ANTHROPIC),
    ("gpt-", Provider.OPENAI),
    ("o1", Provider.OPENAI),
    ("o3", Provider.OPENAI),
    ("o4", Provider.OPENAI),
)


def spec_for(model: str) -> ModelSpec | None:
    """The registered spec for a model, or None if it is only prefix-resolvable."""
    return MODELS.get(model.strip())


def provider_for(model: str) -> Provider:
    """Map a model name to the provider whose key can run it."""
    name = model.strip()
    known = MODELS.get(name)
    if known is not None:
        return known.provider

    lowered = name.lower()
    for prefix, provider in _NAME_PREFIXES:
        if lowered.startswith(prefix):
            return provider

    raise UnknownModelError(
        f"Unknown model {model!r}. Supported: {', '.join(sorted(MODELS))}."
    )


def pricing_for(model: str | None) -> Pricing | None:
    if not model:
        return None
    spec = spec_for(model)
    return spec.pricing if spec else None


def models_for(provider: Provider) -> list[ModelSpec]:
    return [spec for spec in MODELS.values() if spec.provider is provider]


def article_for(provider: Provider) -> str:
    """"a" or "an" for a provider's label — user-facing copy, so it should read right."""
    return "an" if PROVIDER_LABELS[provider][0].lower() in "aeiou" else "a"


def coerce_provider(value: str) -> Provider:
    try:
        return Provider(value.strip().lower())
    except ValueError as exc:
        supported = ", ".join(p.value for p in Provider)
        raise ValueError(f"Unknown provider {value!r}. Supported: {supported}.") from exc
