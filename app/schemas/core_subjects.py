import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

_SUBJECT_CODE = re.compile(r"^[A-Z]{2,4}\d{3}[A-Z]?$")


class CoreSubject(BaseModel):
    """One required/core subject as the Stage-1 model is asked to emit it."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    code: str
    name: str
    valid_sessions: str
    credit_points: int = Field(gt=0)
    pre_requisites: str = Field(default="None", alias="pre-requisites")
    co_requisites: str = Field(default="None", alias="co-requisites")

    @field_validator("code")
    @classmethod
    def _normalise_code(cls, value: str) -> str:
        code = value.upper().replace(" ", "")
        if not _SUBJECT_CODE.match(code):
            raise ValueError(f"{value!r} is not a subject code")
        return code

    @field_validator("pre_requisites", "co_requisites", mode="before")
    @classmethod
    def _none_means_none(cls, value: Any) -> Any:
        return "None" if value is None else value


class CoreSubjectList(BaseModel):
    subjects: list[CoreSubject]

    @model_validator(mode="after")
    def _no_duplicates(self) -> "CoreSubjectList":
        codes = [subject.code for subject in self.subjects]
        repeated = sorted({code for code in codes if codes.count(code) > 1})
        if repeated:
            raise ValueError(f"duplicate subjects: {', '.join(repeated)}")
        return self

    @classmethod
    def from_llm(cls, parsed: object) -> "CoreSubjectList":
        """Type the model's parsed JSON, or raise CoreSubjectFormatError listing every problem."""
        if not isinstance(parsed, dict):
            raise CoreSubjectFormatError(["The output was not a JSON object with a `subjects` list."])
        try:
            return cls.model_validate(parsed)
        except ValidationError as exc:
            raise CoreSubjectFormatError([
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            ]) from exc

    def to_state(self) -> str:
        """Serialised with the prompt's own key names, for the string-typed state slot."""
        return self.model_dump_json(by_alias=True)


class CoreSubjectFormatError(ValueError):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


class CoreEvalVerdict(BaseModel):
    """The auditor's answer. A missing `remaining_valid` is an error, not a silent 'invalid'."""

    model_config = ConfigDict(extra="ignore")

    remaining_valid: bool
    remaining_feedback: str | None = None

    @property
    def feedback(self) -> str | None:
        if self.remaining_valid:
            return None
        return self.remaining_feedback or "Invalid core subjects."
