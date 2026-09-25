"""AdvisorState and the pure helpers the advisor graph nodes share.

No node or graph wiring lives here, so every node module can import it
without a cycle.
"""
import json
import re
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.graph.message import add_messages

from app.schemas.elective_ranking import ElectivePriorityInput
from app.services.elective_ranking import flatten_ranked_electives, get_elective_priorities
from app.services.enrolment import UnreadableRecord, parse_enrolment

# CONSTANTS for max retries/loops to keep the model requests per minute < 15 for free API key tiers
# Stage 1 generation passes per planning run. The evaluator is skipped on the
# last pass because its verdict could no longer trigger a retry.
MAX_STAGE1_RETRIES = 2
MAX_STAGE2_RETRIES = 2
MAX_STAGE2_TOOL_LOOPS = 3


# function to get information from JSON
def extract_and_parse_json(raw_input):
    """
    Extract JSON from:

    - strings
    - markdown fenced JSON
    - LangChain content blocks
    - already parsed dict/list values

    Returns parsed JSON when possible.
    Otherwise returns cleaned text.
    """

    # get text from LangChain content blocks
    if isinstance(raw_input, list):
        text_blocks = []

        for block in raw_input:
            if not isinstance(block, dict):
                continue

            if block.get("type") == "text":
                text = block.get("text")

                if isinstance(text, str):
                    text_blocks.append(text)

            elif "text" in block:
                text = block.get("text")

                if isinstance(text, str):
                    text_blocks.append(text)

        if text_blocks:
            raw_input = "\n".join(text_blocks)

    # Already parsed JSON.
    if not isinstance(raw_input, str):
        return raw_input

    cleaned = raw_input.strip()

    # remove markdown from fenced JSON
    fenced_match = re.fullmatch(
        r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, flags=re.IGNORECASE)

    if fenced_match:
        cleaned = fenced_match.group(1).strip()

    # Do not modify escaped JSON before json.loads().
    cleaned = cleaned.replace("\xa0", " ").strip()

    # Parse
    try:
        return json.loads(cleaned)

    except json.JSONDecodeError:
        return cleaned


# get needed info from SOLS record for ranking electives function
def _major_for_ranking(
    raw: str | None,
) -> str | None:
    if not raw or not str(raw).strip():
        return None

    text = str(raw).strip()

    code_match = re.search(
        r"\b(MAJ\d+)\b", text, flags=re.IGNORECASE)

    if code_match:
        return code_match.group(1).upper()

    if text.upper().startswith("MAJ"):
        return text.upper()

    return (
        re.split(r"\s+[—–-]\s+", text, maxsplit=1)[0].strip()  # noqa: RUF001 (en dash is intentional)
        or text
    )


def sols_codes_for_ranking(
    raw_sols: str | None,
) -> tuple[list[str], list[str]]:
    """
    Split SOLS into completed and currently enrolled subjects.
    """

    if not raw_sols or raw_sols == "no enrolment yet":
        return [], []

    try:
        record = parse_enrolment(raw_sols)

    except UnreadableRecord:
        return [], []

    completed: list[str] = []
    planned: list[str] = []

    for row in record.rows:
        if row.status == "Complete":
            completed.append(row.code)

        elif row.status == "Enrolled":
            planned.append(row.code)

    for credit in record.specified_credit:
        if credit.code:
            completed.append(credit.code)

    return completed, planned


# STAGE 1 ELECTIVES
def stage1_electives_from_advisor_state(
    state: "AdvisorState",
) -> str:
    """
    Deterministically generate Stage 1 elective candidates.
    """

    meta = state.get("meta") or {}

    completed, planned = sols_codes_for_ranking(state.get("raw_sols"))

    raw_major = (
        str(meta.get("major")).strip()
        if meta.get("major")
        else None
    )

    major = _major_for_ranking(raw_major)

    elective_preference = (
        state.get("elective_preference")
        or meta.get("interests")
    )

    unresolved_major_preference = (
        raw_major
        if raw_major
        and not re.fullmatch(r"MAJ\d+", raw_major, flags=re.IGNORECASE)
        and not elective_preference
        else None
    )

    mode = (
        "interest"
        if elective_preference or unresolved_major_preference
        else ("major" if major else "interest")
    )

    if unresolved_major_preference:
        elective_preference = unresolved_major_preference

        print(
            "UNRESOLVED MAJOR TREATED AS KEYWORD PREFERENCE:",
            unresolved_major_preference
        )

    # Metadata must have been confirmed before Stage 1 reaches this node.
    course = str(meta.get("degree_code") or "").strip()
    campus = str(meta.get("campus") or "").strip()
    session = str(meta.get("session") or "").strip()

    if not course or not campus:
        print("STAGE 1 ELECTIVES BLOCKED: confirmed course/campus missing")

        return json.dumps(
            {
                "mode": mode,
                "pools": [],
            },
        )

    student = ElectivePriorityInput(
        course=course,
        campus=campus,
        session=session,
        major=major,
        completed_subjects=completed,
        planned_subjects=planned,
        mode=mode,
        interests=(
            elective_preference
            if mode == "interest"
            else None
        ),
        limit=int(
            meta.get("elective_limit") or 25,
        ),
    )

    #debugging
    print("ELECTIVE INPUT:")
    print("  meta:", meta)
    print("  major:", major)
    print("  raw_major:", raw_major)
    print("  elective_preference:", elective_preference)
    print("  mode:", mode)
    print("  interests:", student.interests)
    print("  completed:", completed)
    print("  planned:", planned)

    print(
        "STAGE 1 ELECTIVES:",
        student.course,
        student.campus,
        student.session,
    )

    ranking = get_elective_priorities(student)

    print("RANKING RESULT:", ranking)

    result = flatten_ranked_electives(
        ranking,
        campus=student.campus,
        session=student.session,
        course=student.course,
    )

    print("FLATTENED ELECTIVES:", result)

    return json.dumps(result.model_dump(by_alias=True))


# GRAPH STATE
class AdvisorState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    raw_sols: str | None

    # Metadata
    meta: dict | None
    meta_confirmed: bool
    planning_requested: bool
    elective_preference: str | None

    conversation_mode: Literal[
        "collecting",
        "planning",
        "post_plan",
    ]

    # Handbook
    handbook: str | None
    handbook_degree_code: str | None
    handbook_year: int | None
    handbook_campus: str | None
    handbook_valid: bool

    # Stage 1
    electives: str | None
    remaining_subjects: str | None
    remaining_feedback: str | None
    stage1_retry_count: int

    # Stage 2
    plan: str | None
    plan_feedback: str | None
    stage2_retry_count: int
    stage2_tool_loop_count: int

# get the type of message to control whether the planning branch should be executed
def latest_student_message(
    state: AdvisorState,
) -> str:
    """
    Return latest student message text.
    """
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return _message_text(message)

    return ""


def is_plan_explanation_question(
    text: str,
) -> bool:
    """
    Detect questions about an existing plan.
    These should not trigger regeneration.
    """

    patterns = [
        r"\bwhy is\b.*\blisted\b",
        r"\bwhy is\b.*\bduplicated\b",
        r"\bwhy does\b.*\bappear\b",
        r"\bwhy are\b.*\btwice\b",
        r"\bexplain\b.*\bplan\b",
        r"\bwhat is\b.*\bsubject\b",
        r"\bis this\b.*\bmistake\b",
    ]

    return any(
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        for pattern in patterns
    )

def latest_tool_batch(state: AdvisorState) -> list[ToolMessage]:
    """Return the most recent run of ToolMessages, oldest first."""
    batch: list[ToolMessage] = []
    for message in reversed(state.get("messages", [])):
        if not isinstance(message, ToolMessage):
            break
        batch.append(message)
    batch.reverse()
    return batch


# HANDBOOK IDENTITY
def metadata_handbook_key(
    meta: dict | None,
) -> tuple[str, int, str] | None:
    """
    Return the identity of the handbook required by metadata.
    """

    if not meta:
        return None

    degree_code = meta.get("degree_code")
    year = meta.get("year")
    campus = meta.get("campus")

    if not degree_code or not year or not campus:
        return None

    try:
        year_int = int(year)

    except (TypeError, ValueError):
        return None

    return (
        str(degree_code),
        year_int,
        str(campus),
    )


def state_handbook_key(
    state: AdvisorState,
) -> tuple[str, int, str] | None:
    """
    Return the identity of the handbook currently stored in state.
    """

    if not state.get("handbook_valid"):
        return None

    degree_code = state.get("handbook_degree_code")
    year = state.get("handbook_year")
    campus = state.get("handbook_campus")

    if not degree_code or not year or not campus:
        return None

    try:
        year_int = int(year)

    except (TypeError, ValueError):
        return None

    return (
        str(degree_code),
        year_int,
        str(campus),
    )


def handbook_matches_current_meta(
    state: AdvisorState,
) -> bool:
    """
    HARD INVARIANT:

    The handbook can only be used if its identity exactly
    matches the current metadata.
    """

    required = metadata_handbook_key(state.get("meta"))

    existing = state_handbook_key(state)

    return (
        required is not None
        and existing is not None
        and required == existing
        and bool(state.get("handbook"))
    )


# METADATA CONFIRMATION HELPERS
def _message_text(
    message: BaseMessage,
) -> str:
    """
    Return plain text from a LangChain message.

    Used only to verify that confirmation values were explicitly
    stated by the student.
    """

    content = getattr(
        message,
        "content",
        "",
    )

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []

        for block in content:
            if isinstance(block, dict):
                value = block.get("text")

                if isinstance(value, str):
                    parts.append(value)

        return "\n".join(parts)

    return str(content)


def _student_conversation_text(
    state: "AdvisorState",
) -> str:
    """
    Return text from student-authored messages only.
    """

    parts: list[str] = []

    for message in state.get("messages", []):
        if isinstance(message, HumanMessage):
            value = _message_text(message).strip()

            if value:
                parts.append(value)

    return "\n".join(parts)


def _value_explicitly_stated_by_student(
    value,
    student_text: str,
) -> bool:
    """
    Check whether a proposed metadata value appears explicitly
    in student-authored text.

    This deliberately avoids semantic matching so the LLM cannot
    silently substitute a canonical label for the student's words.
    """

    if value is None:
        return False

    candidate = str(value).strip()

    if not candidate:
        return False

    normalized_candidate = re.sub(r"\s+", " ", candidate.casefold())

    normalized_text = re.sub(r"\s+", " ", student_text.casefold())

    return normalized_candidate in normalized_text


def _extract_explicit_major_hint(
    student_text: str,
    known_values: list[str],
) -> str | None:
    """
    Recover the student's own major wording when the confirmation
    tool returned a different/canonicalized major name.

    The extraction is conservative:
      1. Prefer text explicitly introduced as a major.
      2. Otherwise, when the same message clearly contains all
         known enrolment fields, accept one remaining short
         comma/semicolon/newline segment as the student's wording.

    No handbook major is invented here.
    """

    if not student_text.strip():
        return None

    labeled = re.search(
        r"\b(?:major|specialisation|specialization)\b"
        r"\s*(?:is|=|:|-)?\s*"
        r"([A-Za-z0-9][A-Za-z0-9 &'()/.-]{1,80})",
        student_text,
        flags=re.IGNORECASE,
    )

    if labeled:
        candidate = labeled.group(1).strip(
            " \t\r\n,;."
        )

        if candidate:
            return candidate

    if not all(
        _value_explicitly_stated_by_student(value, student_text)
        for value in known_values
        if value is not None
    ):
        return None

    segments = [
        part.strip()
        for part in re.split(
            r"[,;|\n]+",
            student_text,
        )
        if part.strip()
    ]

    if len(segments) < 4:
        return None

    known_lower = {
        str(value).strip().casefold()
        for value in known_values
        if value is not None
    }

    remaining: list[str] = []

    for segment in segments:
        cleaned = re.sub(
            r"^\s*(?:course|degree|year|commencement year|campus|major)\s*"
            r"(?:code|is|=|:)?\s*",
            "",
            segment,
            flags=re.IGNORECASE,
        ).strip()

        if cleaned.casefold() in known_lower:
            continue

        if len(cleaned.split()) <= 8:
            remaining.append(cleaned)

    if len(remaining) == 1:
        return remaining[0]

    return None


def sanitize_confirmed_metadata(
    prior_meta: dict | None,
    candidate_meta: dict,
    state: "AdvisorState",
) -> dict:
    """
    Prevent the confirmation LLM from creating metadata that the
    student did not actually state.

    Existing parsed metadata may be preserved. New values must be
    explicitly present in student-authored text.

    Major handling is intentionally special:
      - exact student wording is accepted;
      - a canonicalized major not present in student text is rejected;
      - a conservative raw major hint may be retained;
      - no handbook-derived major name is invented.
    """

    prior = dict(prior_meta or {})
    candidate = dict(candidate_meta or {})
    student_text = _student_conversation_text(state)

    sanitized = dict(prior)

    for field in (
        "degree_code",
        "year",
        "campus",
        "session",
        "elective_limit",
        "interests",
    ):
        value = candidate.get(field)

        if value in (None, ""):
            continue

        if field in {
            "degree_code",
            "year",
            "campus",
            "session",
        }:
            if (
                field in prior
                and str(prior.get(field)).strip() == str(value).strip()
            ):
                sanitized[field] = value

            elif _value_explicitly_stated_by_student(
                value,
                student_text,
            ):
                sanitized[field] = value

            else:
                print(
                    "CONFIRMATION DROPPED NON-EXPLICIT",
                    field,
                    repr(value),
                )
        else:
            sanitized[field] = value

    candidate_major = candidate.get("major")

    if candidate_major not in (None, ""):
        candidate_major = str(candidate_major).strip()

        if _value_explicitly_stated_by_student(candidate_major, student_text):
            sanitized["major"] = candidate_major

        elif prior.get("major"):
            print("CONFIRMATION DROPPED CANONICALIZED MAJOR:", repr(candidate_major))

        else:
            major_hint = _extract_explicit_major_hint(
                student_text,
                [
                    candidate.get("degree_code")
                    or prior.get("degree_code"),
                    candidate.get("year")
                    or prior.get("year"),
                    candidate.get("campus")
                    or prior.get("campus"),
                ],
            )

            if major_hint:
                sanitized["major"] = major_hint

                print("CONFIRMATION RETAINED STUDENT MAJOR WORDING:", repr(major_hint))

            else:
                sanitized.pop("major", None)

                print("CONFIRMATION DROPPED UNVERIFIED MAJOR:", repr(candidate_major))

    return sanitized


# METADATA
def validate_metadata(
    meta: dict | None,
) -> list[str]:
    """
    Return required metadata fields that are missing.

    Missing information is never inferred.
    """

    if not meta:
        return [
            "degree_code",
            "year",
            "campus",
        ]

    missing: list[str] = []

    if not meta.get("degree_code"):
        missing.append("degree_code")

    if not meta.get("year"):
        missing.append("year")

    if not meta.get("campus"):
        missing.append("campus")

    return missing


def apply_confirm_metadata(
    prior_meta: dict | None,
    new_meta: dict,
) -> dict:
    """
    Apply a confirmed metadata update.

    Candidate metadata has already been sanitized against the
    student's own messages before reaching this function.

    Any generated planning information is invalidated whenever
    metadata is confirmed.

    The handbook is invalidated when its identity changes.
    """

    missing = validate_metadata(new_meta)

    if missing:
        print("CONFIRMATION REJECTED - missing:", missing)

        return {
            "meta_confirmed": False,
            "planning_requested": False,
        }

    old_key = metadata_handbook_key(prior_meta)

    new_key = metadata_handbook_key(new_meta)

    handbook_changed = old_key != new_key

    updates: dict = {
        "meta": new_meta,
        "meta_confirmed": True,
        "planning_requested": True,
        "conversation_mode": "planning",
        "elective_preference": None,

        # Invalidate generated planning data.
        "electives": None,
        "remaining_subjects": None,
        "plan": None,

        "remaining_feedback": None,
        "plan_feedback": None,

        "stage1_retry_count": 0,
        "stage2_retry_count": 0,
        "stage2_tool_loop_count": 0,
    }

    if handbook_changed:
        print("HANDBOOK INVALIDATED")
        print("OLD:", old_key)
        print("NEW:", new_key)

        updates.update({
            "handbook": None,
            "handbook_degree_code": None,
            "handbook_year": None,
            "handbook_campus": None,
            "handbook_valid": False,
        })

    return updates


def apply_plan_change_request(
    prior_meta: dict | None,
    request: dict,
) -> dict:
    """
    Deterministically apply a plan-change tool request and reset
    generated planning state.
    """

    change_type = request.get("change_type")

    allowed_types = {
        "major",
        "elective_preference",
        "course",
        "campus",
        "commencement_year",
        "session",
        "general_revision",
    }

    if change_type not in allowed_types:
        print(
            "PLAN CHANGE REJECTED: unknown change_type",
            change_type,
        )
        return {}

    meta = dict(prior_meta or {})

    if change_type == "major":
        value = request.get("major")

        if not value or not str(value).strip():
            print("PLAN CHANGE REJECTED: major missing")
            return {}

        meta["major"] = str(value).strip()

    elif change_type == "elective_preference":
        value = request.get("elective_preference")

        if not value or not str(value).strip():
            print(
                "PLAN CHANGE REJECTED: elective preference missing",
            )
            return {}

        print(
            "PLAN CHANGE APPLIED: elective_preference",
            value,
        )

        return {
            "planning_requested": True,
            "conversation_mode": "planning",
            "elective_preference": str(value).strip(),
            "electives": None,
            "remaining_subjects": None,
            "remaining_feedback": None,
            "plan": None,
            "plan_feedback": None,
            "stage1_retry_count": 0,
            "stage2_retry_count": 0,
            "stage2_tool_loop_count": 0,
        }

    elif change_type == "course":
        value = request.get("course")

        if not value or not str(value).strip():
            print("PLAN CHANGE REJECTED: course missing")
            return {}

        meta["degree_code"] = str(value).strip()

    elif change_type == "campus":
        value = request.get("campus")

        if not value or not str(value).strip():
            print("PLAN CHANGE REJECTED: campus missing")
            return {}

        meta["campus"] = str(value).strip()

    elif change_type == "commencement_year":
        value = request.get("commencement_year")

        if value is None:
            print(
                "PLAN CHANGE REJECTED: commencement year missing",
            )
            return {}

        try:
            meta["year"] = int(value)
        except (TypeError, ValueError):
            print(
                "PLAN CHANGE REJECTED: invalid commencement year",
                repr(value),
            )
            return {}

    elif change_type == "session":
        value = request.get("session")

        if not value or not str(value).strip():
            print("PLAN CHANGE REJECTED: session missing")
            return {}

        meta["session"] = str(value).strip()

    missing = validate_metadata(meta)

    if missing:
        print(
            "PLAN CHANGE REJECTED - missing:",
            missing,
        )
        return {
            "planning_requested": False,
            "meta_confirmed": False,
        }

    old_key = metadata_handbook_key(prior_meta)
    new_key = metadata_handbook_key(meta)

    updates = {
        "meta": meta,
        "meta_confirmed": True,
        "planning_requested": True,
        "conversation_mode": "planning",
        "elective_preference": None,
        "electives": None,
        "remaining_subjects": None,
        "remaining_feedback": None,
        "plan": None,
        "plan_feedback": None,
        "stage1_retry_count": 0,
        "stage2_retry_count": 0,
        "stage2_tool_loop_count": 0,
    }

    print(
        "PLAN CHANGE APPLIED:",
        change_type,
        meta,
    )

    if old_key != new_key:
        print(
            "HANDBOOK INVALIDATED BY PLAN CHANGE",
            old_key,
            "->",
            new_key,
        )
        updates.update({
            "handbook": None,
            "handbook_degree_code": None,
            "handbook_year": None,
            "handbook_campus": None,
            "handbook_valid": False,
        })

    return updates



# All-clear state written whenever the handbook cannot be trusted.
HANDBOOK_CLEARED: dict = {
    "handbook": None,
    "handbook_degree_code": None,
    "handbook_year": None,
    "handbook_campus": None,
    "handbook_valid": False,
}

# Planning artefacts that every (re)start of planning wipes.
PLANNING_RESET: dict = {
    "electives": None,
    "remaining_subjects": None,
    "remaining_feedback": None,
    "stage1_retry_count": 0,
    "plan": None,
    "plan_feedback": None,
    "stage2_retry_count": 0,
    "stage2_tool_loop_count": 0,
}
