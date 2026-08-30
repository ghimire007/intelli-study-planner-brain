"""Request/response shapes for the key vault.

There is deliberately no schema anywhere in this file that can carry a readable
API key back out — ``last4`` is the most a response ever reveals.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateKeyIn(BaseModel):
    provider: str
    api_key: str = Field(min_length=8, max_length=512)
    label: str | None = Field(default=None, max_length=100)
    #: Make this the key we reach for first for its provider.
    make_default: bool = True

    @field_validator("api_key")
    @classmethod
    def strip_key(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Paste your API key")
        return stripped

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class UpdateKeyIn(BaseModel):
    """Every field optional — this endpoint renames, replaces, or promotes."""

    api_key: str | None = Field(default=None, min_length=8, max_length=512)
    label: str | None = Field(default=None, max_length=100)
    make_default: bool | None = None

    @field_validator("api_key")
    @classmethod
    def strip_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Paste your API key")
        return stripped

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class KeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    label: str
    last4: str
    is_default: bool
    status: str
    created_at: datetime
    last_used_at: datetime | None = None
    last_verified_at: datetime | None = None


class ModelOut(BaseModel):
    name: str
    label: str
    priced: bool


class ProviderOut(BaseModel):
    provider: str
    label: str
    console_url: str
    models: list[ModelOut]
    default_model: str
    key_count: int
    has_usable_key: bool


class ProvidersOut(BaseModel):
    providers: list[ProviderOut]
    #: What a chat request uses when it names no model.
    default_model: str
    #: True when the project's own key covers students who have added none.
    system_fallback_enabled: bool


class VerifyKeyOut(BaseModel):
    id: uuid.UUID
    status: str
    verified: bool
    detail: str
