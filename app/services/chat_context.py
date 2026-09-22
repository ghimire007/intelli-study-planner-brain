"""Academic-only intake state; no identity or account secrets enter checkpoints."""
import re
from copy import deepcopy

from app.schemas.chat import ChatContext
from app.services.enrolment import UnreadableRecord, parse_enrolment, project
from app.services.pii import scrub_pii

FIELDS = ("degree_code", "year", "campus", "major", "elective_interests")
REQUIRED = ("degree_code", "year", "campus")


class InvalidChatContext(UnreadableRecord):
    pass


class SessionNotFound(ValueError):
    pass


def academic_values(profile: dict) -> dict:
    values = {("year" if key == "commencement_year" else key): value
              for key, value in profile.items()}
    return {key: scrub_pii(value) if isinstance(value, str) else
            [scrub_pii(item) for item in value] if isinstance(value, list) else value
            for key, value in values.items() if key in FIELDS and value is not None}


def merge_academic(state: dict, incoming: dict, source: str) -> dict:
    """Only fill unknowns. Record differing observations for student clarification.

    Remember observations so replaying a stale profile/record on every request
    cannot undo a correction or resurrect a conflict the student has resolved.
    """
    result = deepcopy({key: state.get(key, default) for key, default in (
        ("meta", {}), ("field_sources", {}), ("context_conflicts", {}),
        ("context_observations", {}), ("meta_confirmed", False),
    )})
    result["meta"] = result["meta"] or {}
    meta = result["meta"]
    seen = result["context_observations"].setdefault(source, {})
    for key, value in academic_values(incoming).items():
        if key in seen and seen[key] == value:
            continue
        seen[key] = value
        if meta.get(key) is None:
            meta[key] = value
            result["field_sources"][key] = {"source": source, "confirmed": False}
        elif meta[key] != value:
            result["context_conflicts"][key] = {
                "current": meta[key], "incoming": value, "source": source,
            }
    if result["context_conflicts"]:
        result["meta_confirmed"] = False
    return result


def safe_record(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 100_000:
        raise InvalidChatContext("Supply a non-empty SOLS enrolment record of at most 100000 characters.")
    try:
        return scrub_pii(project(raw))
    except (UnreadableRecord, ValueError) as exc:
        # Parser diagnostics can contain rejected raw cells. Never echo those.
        raise InvalidChatContext(
            "Could not read the enrolment record. Paste the complete SOLS enrolment table, including its column headings."
        ) from exc


def record_values(projected: str) -> dict:
    record = parse_enrolment(projected)
    return {
        "degree_code": record.course_code,
        "campus": record.campus or (max(record.rows, key=lambda row: row.year).campus if record.rows else None),
        # Earliest visible enrolment is a candidate, not proof of commencement.
        "year": min((row.year for row in record.rows), default=None),
        "major": ", ".join(record.majors) or None,
    }


def intake_context(user, context: ChatContext | None, prior: dict, record: str | None = None) -> dict:
    state = merge_academic(prior, {
        key: getattr(user, key, None) for key in (
            "degree_code", "commencement_year", "campus", "major", "elective_interests"
        )
    }, "saved_profile")
    if context and context.profile:
        state = merge_academic(state, context.profile.model_dump(), "client_hint")
    supplied = record if record is not None else (context.enrolment_record if context else None)
    if supplied is not None:
        projected = safe_record(supplied)
        state = merge_academic(state, record_values(projected), "enrolment_record")
        state["raw_sols"] = projected
    elif prior.get("raw_sols"):
        state["raw_sols"] = safe_record(prior["raw_sols"])
    elif not prior:
        state["raw_sols"] = ""
    # Never accept a title as a code, even from a legacy saved profile.
    code = state["meta"].get("degree_code")
    if code is not None and not re.fullmatch(r"\d{3,4}", str(code)):
        state["meta"].pop("degree_code", None)
        state["meta_confirmed"] = False
    return state
