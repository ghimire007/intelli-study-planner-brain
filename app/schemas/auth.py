import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ProfileText = Annotated[str, Field(min_length=1, max_length=120)]


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str = Field(default=None, min_length=3, max_length=320)
    # Disable whitespace normalization for passwords: every character matters.
    current_password: Annotated[
        str, StringConstraints(strip_whitespace=False, min_length=1, max_length=128)
    ] | None = Field(default=None, exclude=True, repr=False)
    degree_code: str = Field(default=None, min_length=1, max_length=12)
    commencement_year: int | None = Field(default=None, ge=1900, le=2100, strict=True)
    campus: str | None = Field(default=None, min_length=1, max_length=32)
    major: str | None = Field(default=None, min_length=1, max_length=120)
    elective_interests: list[ProfileText] = Field(default=None, max_length=100)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return Credentials.normalize_email(value)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address")
        return value


class RegisterRequest(Credentials):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class LoginRequest(Credentials):
    pass


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address")
        return value


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    created_at: datetime
    degree_code: str
    commencement_year: int | None
    campus: str | None
    major: str | None
    elective_interests: list[str]
