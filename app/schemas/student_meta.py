from typing import TypedDict


class StudentMeta(TypedDict, total=False):
    """Shape of `AdvisorState["meta"]`.

    A TypedDict, not a model: the state is checkpointed as plain JSON and older
    sessions hold partly-filled dicts (and the legacy `major` key), so it must
    stay a dict at runtime. Every key may be absent or None until confirmed.
    """

    degree_code: str | None
    year: int | None
    campus: str | None
    majors: list[str]
    major: list[str] | str | None  # legacy spelling still read by the sanitiser
    session: str | None
    interests: str | None
    elective_limit: int | None
