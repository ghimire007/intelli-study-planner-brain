from pydantic import BaseModel, ConfigDict


class PlanEvalVerdict(BaseModel):
    """The Stage 2 auditor's answer. A missing `valid` is an error, not a silent 'invalid'."""

    model_config = ConfigDict(extra="ignore")

    valid: bool
    feedback: str | None = None

    @property
    def issues(self) -> str | None:
        if self.valid:
            return None
        return self.feedback or "Invalid plan."
