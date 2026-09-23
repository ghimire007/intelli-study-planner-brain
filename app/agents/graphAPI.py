import json
import re
from typing import Annotated, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.skills import build_skills, fetch_handbook
from app.llm.config import LLMConfig
from app.llm.factory import make_chat_model
from app.prompts.builder import build_system_prompt
from app.prompts.prompts import (
    EVAL_PLAN,
    EVAL_SUBJECTS_ELECTIVES,
    SUBJECT_GENERATION_PROMPT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_V1,
)
from app.schemas.elective_ranking import ElectivePriorityInput
from app.services.elective_ranking import flatten_ranked_electives, get_elective_priorities
from app.services.enrolment import UnreadableRecord, parse_enrolment
from app.services.sols_parser import parse_sols

# CONSTANTS for max retries/loops to keep the model requests per minute < 15 for free API key tiers
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


# GRAPH
def build_advisor_graph(
    db: AsyncSession,
    checkpointer: BaseCheckpointSaver,
    llm_config: LLMConfig | None = None,
):
    """
    Build the advisor graph.
    """

    skills = build_skills(db)

    conversation_confirm_tools = [*skills["confirm"]]
    conversation_full_tools = [*skills["full"]]

    # LLM CACHE
    models: dict[str, BaseChatModel] = {}

    def llm(
        kind: str,
    ) -> BaseChatModel:
        """
        Lazily construct LLMs.

        Models:
            parser
            confirm
            full

        `full` is used for tool-capable conversation/planning.
        """

        if kind not in models:
            if llm_config is None:
                raise RuntimeError("Graph was created without an LLM config.")

            base = make_chat_model(llm_config)

            if kind == "parser":
                model = base

            elif kind == "confirm":
                model = base.bind_tools(conversation_confirm_tools)
                return model

            elif kind == "full":
                model = base.bind_tools(conversation_full_tools)

            else:
                model = base.bind_tools(skills[kind])

            # allow retry
            models[kind] = model.with_retry(
                wait_exponential_jitter=True,
                stop_after_attempt=2,
            )

        return models[kind]

    # INPUT PARSER
    async def parse_input(state):
        print("NODE: parse_input")

        if state.get("meta") is not None:
            return {}

        raw_sols = state.get("raw_sols")

        print("raw_sols chars =", len(raw_sols or ""))

        start = time.perf_counter()

        llm("parser")

        print(
            f"llm() took "
            f"{time.perf_counter() - start:.2f}s"
        )

        start = time.perf_counter()

        try:
            meta = await parse_sols(
                llm("parser"),
                raw_sols,
            )

        except Exception as e:
            print(type(e).__name__)
            print(repr(e))
            raise

        print(
            f"parse_sols took "
            f"{time.perf_counter() - start:.2f}s"
        )

        return {
            "meta": meta.model_dump(),
            "meta_confirmed": False,
            "planning_requested": False,
        }

    # CONVERSATIONAL AGENT
    import time

    async def agent(state: AdvisorState) -> dict:
        """
        Conversational LLM.

        Before metadata confirmation: confirmation-oriented model.

        After metadata confirmation: full planning/conversation model.
        """
        print("NODE: agent")

        model = llm(
            "full" if state.get("meta_confirmed") else "confirm"
        )

        print(
            "agent: invoking",
            "full" if state.get("meta_confirmed") else "confirm"
        )

        confirmed = bool(state.get("meta_confirmed"))
        # either getting info or replying to a question/input
        conversation_mode = (state.get("conversation_mode") or "collecting")

        system_content = build_system_prompt(
            prompt=SYSTEM_PROMPT,
            meta=state.get("meta"),
            meta_confirmed=confirmed,
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )

        system_content += """
            PLAN CHANGE RULES:

            You must distinguish between:
            1. questions about the existing plan
            2. requests to modify the plan

            DO NOT call request_plan_change_tool for general questions, questions about the plan itself or question about your logic.

            Only call request_plan_change_tool when the student explicitly wants the plan to change.

            Current conversation mode:
            {conversation_mode}

            """.format(
                conversation_mode=conversation_mode
            )


        messages = [SystemMessage(content=system_content), *state.get("messages", [])]

        latest = latest_student_message(state)

        # if the question is determined to be just asking an explaination and not to replan the plan (yet), only answer converstionally
        if (state.get("conversation_mode") == "post_plan" and is_plan_explanation_question(latest)):
            system_content += """
                The user is asking about the existing generated plan. Do not call any plan-change tools. Explain the existing plan instead.
            """

        response = await model.ainvoke(messages)

        # print("agent: response =", repr(response))
        # print("agent: tool calls =", response.tool_calls)
        # print("agent: content =", repr(response.content))

        # print("agent: response tool calls =", getattr(response, "tool_calls", None))
        # print("agent: response content length =", len(response.content or ""))

        # print(
        #     f"agent: LLM finished in {time.perf_counter() - start:.2f}s"
        # )

        # print("agent: system prompt chars =", len(system_content))
        # print(
        #     "agent: message chars =",
        #     sum(len(str(m.content)) for m in state.get("messages", []))
        # )

        return {
            "messages": [response],
        }

    # CONVERSATIONAL TOOL RESULT CAPTURE
    def capture_tool_results(
        state: AdvisorState,
    ) -> dict:
        """
        Capture only conversational tool results that affect
        advisor state.

        At present this primarily handles metadata confirmation.
        """
        print("NODE: capture_tool_results")

        messages = state.get("messages", [])

        batch: list[ToolMessage] = []

        for message in reversed(messages):
            if not isinstance(message, ToolMessage):
                break

            batch.append(message)

        batch.reverse()

        updates: dict = {}

        for message in batch:
            if message.name not in {"confirm_metadata_tool", "request_plan_change_tool"}:
                continue

            try:
                content = message.content

                parsed = extract_and_parse_json(content)

                if not isinstance(parsed, dict):
                    raise ValueError(
                        f"{message.name} did not return an object."
                    )

                prior_meta = updates.get("meta", state.get("meta"))

                if message.name == "confirm_metadata_tool":
                    sanitized = sanitize_confirmed_metadata(
                        prior_meta=prior_meta,
                        candidate_meta=parsed,
                        state=state,
                    )

                    updates.update(
                        apply_confirm_metadata(
                            prior_meta,
                            sanitized,
                        )
                    )

                    print("CONFIRMED METADATA RAW:", parsed)
                    print("CONFIRMED METADATA SANITIZED:", sanitized)

                else:
                    updates.update(
                        apply_plan_change_request(
                            prior_meta,
                            parsed,
                        )
                    )

                    print("PLAN CHANGE TOOL RESULT:", parsed)

            except Exception as exc:
                print("Conversational tool parse error:", repr(exc))

        return updates

    # AFTER AGENT
    def route_after_agent(
        state: AdvisorState,
    ) -> Literal[
        "tools",
        "ensure_handbook",
        "start_planning",
        END,
    ]:
        """
        The LLM may request conversational tools.

        The LLM does NOT control the handbook gate.
        """

        messages = state.get("messages", [])

        last = (messages[-1] if messages else None)

        if (isinstance(last, AIMessage) and last.tool_calls):
            return "tools"

        if not state.get("meta_confirmed"):
            return END

        if not state.get("planning_requested"):
            return END

        if not handbook_matches_current_meta(state):
            print("ROUTE: handbook missing/stale")
            return "ensure_handbook"

        return "start_planning"

    # HANDBOOK FETCH
    async def ensure_handbook(
        state: AdvisorState,
    ) -> dict:
        """
        Fetch exactly the handbook required by metadata.
        """
        print("NODE: ensure_handbook")

        meta = state.get("meta")

        required = metadata_handbook_key(meta)

        if required is None:
            print("HANDBOOK FETCH: invalid metadata",)

            return {
                "handbook": None,
                "handbook_degree_code": None,
                "handbook_year": None,
                "handbook_campus": None,
                "handbook_valid": False,
                "planning_requested": False,
            }

        degree_code, year, campus = required

        print("HANDBOOK FETCH:", degree_code, year, campus)

        try:
            content = await fetch_handbook(
                db,
                degree_code,
                year,
                campus,
            )

        except Exception as exc:
            print("HANDBOOK FETCH ERROR:", repr(exc))

            return {
                "handbook": None,
                "handbook_degree_code": None,
                "handbook_year": None,
                "handbook_campus": None,
                "handbook_valid": False,
                "planning_requested": False,
            }

        if (not content or not str(content).strip()):
            print("HANDBOOK FETCH FAILED: empty")

            return {
                "handbook": None,
                "handbook_degree_code": None,
                "handbook_year": None,
                "handbook_campus": None,
                "handbook_valid": False,
                "planning_requested": False,
            }

        print("HANDBOOK FETCH SUCCESS:", required)

        return {
            "handbook": content,
            "handbook_degree_code": degree_code,
            "handbook_year": year,
            "handbook_campus": campus,
            "handbook_valid": True,
        }

    # HANDBOOK ROUTER
    def route_after_handbook_fetch(
        state: AdvisorState,
    ) -> Literal[
        "start_planning",
        "handbook_missing",
    ]:
        if handbook_matches_current_meta(state):
            return "start_planning"

        return "handbook_missing"

    # HANDBOOK FAILURE
    async def handbook_missing(
        state: AdvisorState,
    ) -> dict:
        """
        Stop planning until the handbook can be obtained.
        """
        print("NODE: handbook_missing")

        print("HANDBOOK MISSING: stopping planning")

        return {
            "planning_requested": False,

            "electives": None,
            "remaining_subjects": None,
            "plan": None,

            "remaining_feedback": None,
            "plan_feedback": None,
        }

    # START PLANNING
    async def start_planning(
        state: AdvisorState,
    ) -> dict:
        """
        Consume planning_requested exactly once.
        """
        print("NODE: start_planning")

        if not handbook_matches_current_meta(state):
            print("START PLANNING BLOCKED: handbook invalid")

            return {
                "planning_requested": False,
            }

        return {
            "planning_requested": False,
            "conversation_mode": "planning",

            # Reset Stage 1 execution state.
            "electives": None,
            "remaining_subjects": None,

            "remaining_feedback": None,
            "stage1_retry_count": 0,

            # Reset Stage 2 execution state.
            "plan": None,
            "plan_feedback": None,
            "stage2_retry_count": 0,
            "stage2_tool_loop_count": 0,
        }

    # STAGE 1 - ELECTIVES
    async def fetch_elective_list(
        state: AdvisorState,
    ) -> dict:
        """
        Generate elective candidates.

        No parallel execution.
        """
        print("NODE: fetch_elective_list")

        if not handbook_matches_current_meta(state):
            print("STAGE 1 ELECTIVES BLOCKED: handbook invalid")
            return {}

        content = (stage1_electives_from_advisor_state(state))

        return {
            "electives": content,
        }

    # STAGE 1 - REQUIRED SUBJECTS
    async def stage1_review_must_includes(
        state: AdvisorState,
    ) -> dict:
        """
        Generate required/core subjects after the deterministic
        elective list has been produced.
        """
        print("NODE: stage1_review_must_includes")

        if not handbook_matches_current_meta(state):
            print("STAGE 1 REQUIRED SUBJECTS BLOCKED")
            return {}

        feedback = state.get("remaining_feedback")

        prompt = build_system_prompt(
            prompt=SUBJECT_GENERATION_PROMPT,
            meta=state.get("meta"),
            meta_confirmed=state.get(
                "meta_confirmed",
                False,
            ),
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )

        if feedback:
            prompt += (
                "\n\nCORRECT THE FOLLOWING "
                "ISSUES FROM PREVIOUS PASS:\n"
                f"{feedback}"
            )

        response = await llm(
            "full",
        ).ainvoke([
            SystemMessage(content=("You are an academic course planning assistant. Return the required/core subjects as JSON. Do not call tools.")),
            HumanMessage(content=prompt)
        ])

        parsed = extract_and_parse_json(response.content)

        if isinstance(parsed, (dict, list)):
            content = json.dumps(parsed)

        elif isinstance(parsed, str):
            content = parsed

        else:
            content = json.dumps(parsed)

        return {
            "remaining_subjects": content,
            "remaining_feedback": None,
        }

    # REQUIRED SUBJECT EVALUATION
    async def evaluate_required_subjects(
        state: AdvisorState,
    ) -> dict:
        """
        Evaluate only the required/core-subject list.
        The elective list is deterministic and is not LLM-evaluated.
        """
        print("NODE: evaluate_required_subjects")

        if not handbook_matches_current_meta(state):
            return {"remaining_feedback": "Required handbook is unavailable."}

        current_retry = state.get("stage1_retry_count", 0)

        eval_prompt = build_system_prompt(
            prompt=EVAL_SUBJECTS_ELECTIVES,
            meta=state.get("meta"),
            meta_confirmed=state.get(
                "meta_confirmed",
                False,
            ),
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )

        eval_prompt = (
            eval_prompt
            .replace(
                "{{electives}}",
                state.get("electives") or "",
            )
            .replace(
                "{{remaining_subjects}}",
                state.get("remaining_subjects") or "",
            )
        )

        response = await llm(
            "parser",
        ).ainvoke([
            SystemMessage(content=("You are an academic auditor checking course list accuracy. Evaluate ONLY the required/core subjects. Do not evaluate, validate, or score the elective list; electives come from a deterministic non-LLM service. Return ONLY JSON.")),
            HumanMessage(content=eval_prompt)
        ])

        try:
            data = extract_and_parse_json(response.content)

            if not isinstance(data, dict):
                raise ValueError(
                    "Stage 1 evaluator did not "
                    "return an object."
                )

            remaining_valid = bool(data.get("remaining_valid"))

            remaining_feedback = (
                None
                if remaining_valid
                else data.get("remaining_feedback", "Invalid core subjects."))

            return {
                "remaining_feedback": remaining_feedback,
                "stage1_retry_count": current_retry + 1,
            }

        except Exception as exc:
            print("REQUIRED SUBJECT EVAL ERROR:", repr(exc))

            return {
                "remaining_feedback": "Failed to parse validation output.",
                "stage1_retry_count": current_retry + 1,
            }

    # STAGE 1 FINAL ROUTER
    def route_stage1_evaluation(
        state: AdvisorState,
    ) -> Literal[
        "stage1_review_must_includes",
        "stage2_make_plan",
    ]:
        """
        Final Stage 1 decision.

        The deterministic elective list and LLM-generated
        required/core subject list have both been produced.
        """

        remaining_feedback = state.get("remaining_feedback",)

        retries = state.get("stage1_retry_count", 0)

        # Required/core subjects are the only LLM-evaluated
        # Stage 1 output.
        if not remaining_feedback:
            return "stage2_make_plan"

        # Retry limit reached.
        if retries >= MAX_STAGE1_RETRIES:
            print("STAGE 1 retry limit reached")
            return "stage2_make_plan"

        return "stage1_review_must_includes"

    # STAGE 2 PLAN GENERATION
    async def stage2_make_plan(
        state: AdvisorState,
    ) -> dict:
        """
        Generate the study plan.

        This node may request planning tools.
        """
        print("NODE: stage2_make_plan")

        if not handbook_matches_current_meta(state):
            print("STAGE 2 BLOCKED: handbook invalid")

            return {
                "planning_requested": False,
                "plan": None,
            }

        feedback = state.get("plan_feedback")

        base_prompt = build_system_prompt(
            prompt=SYSTEM_PROMPT_V1,
            meta=state.get("meta"),
            meta_confirmed=state.get("meta_confirmed", False),
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )

        if feedback:
            base_prompt += (f"\n\nAddress this previous evaluation feedback: {feedback}")

        content_prompt = (
            "Authoritative metadata:\n"
            f"{state.get('meta')}\n\n"

            "Authoritative handbook:\n"
            f"{state.get('handbook')}\n\n"

            "Current SOLS:\n"
            f"{state.get('raw_sols')}\n\n"

            "Required/core subjects:\n"
            f"{state.get('remaining_subjects')}\n\n"

            "Elective choices:\n"
            f"{state.get('electives')}\n"
        )

        messages = [
            SystemMessage(content=base_prompt),
            *state.get("messages", []),
            HumanMessage(content=content_prompt),
        ]

        response = await llm("full").ainvoke(messages)

        updated: dict = {
            "messages": [response],
        }

        # Reset tool-loop state when a new generation completes without tools.
        if not response.tool_calls:
            updated["stage2_tool_loop_count"] = 0

        text_plan = ""

        if isinstance(response.content, str):
            text_plan = response.content.strip()

        elif isinstance(response.content, list):
            text_blocks = []

            for block in response.content:
                if not isinstance(block, dict):
                    continue

                if block.get("type") != "text":
                    continue

                text = block.get("text")

                if isinstance(text, str):
                    text_blocks.append(text)

            text_plan = "\n".join(text_blocks).strip()

        if (text_plan and not response.tool_calls):
            updated["plan"] = text_plan

        return updated

    # STAGE 2 TOOL RESULT CAPTURE
    def capture_stage2_tool_results(
        state: AdvisorState,
    ) -> dict:
        """
        Stage 2 tool results are primarily retained in the
        message history.

        This node increments the bounded tool-loop counter.

        It deliberately does NOT run metadata confirmation
        logic.
        """
        print("NODE: capture_stage2_tool_results")

        count = state.get("stage2_tool_loop_count", 0)

        return {
            "stage2_tool_loop_count": count + 1,
        }

    # STAGE 2 ROUTER
    def route_after_stage2_make_plan(
        state: AdvisorState,
    ) -> Literal[
        "stage2_tools",
        "evaluate_stage2",
    ]:
        messages = state.get("messages", [])

        last = messages[-1] if messages else None

        if (isinstance(last, AIMessage) and last.tool_calls):
            tool_loops = state.get("stage2_tool_loop_count", 0)

            if tool_loops >= MAX_STAGE2_TOOL_LOOPS:
                print("STAGE 2 tool-loop limit reached")

                return "evaluate_stage2"

            return "stage2_tools"

        return "evaluate_stage2"


    # STAGE 2 EVALUATION
    async def evaluate_stage2(
        state: AdvisorState,
    ) -> dict:
        """
        Evaluate the generated plan against the authoritative
        context.

        The evaluator receives:
            - metadata
            - handbook
            - SOLS
            - required subjects
            - electives
            - generated plan
        """
        print("NODE: evaluate_stage2")

        retries = state.get("stage2_retry_count", 0)

        plan = state.get("plan")

        if not plan:
            return {
                "plan_feedback": "No plan was generated.",
                "stage2_retry_count": retries + 1,
            }

        eval_prompt = (EVAL_PLAN
            .replace("{{PLAN}}", plan)
        )

        eval_prompt += (
            "\n\nAUTHORITATIVE METADATA:\n"
            f"{state.get('meta')}\n\n"

            "AUTHORITATIVE HANDBOOK:\n"
            f"{state.get('handbook')}\n\n"

            "CURRENT SOLS:\n"
            f"{state.get('raw_sols')}\n\n"

            "REQUIRED/CORE SUBJECTS:\n"
            f"{state.get('remaining_subjects')}\n\n"

            "ELECTIVE OPTIONS:\n"
            f"{state.get('electives')}\n"
        )

        response = await llm("parser").ainvoke([
            SystemMessage(content=(
                "You are an academic auditor checking a generated study plan against authoritative source data. "
                "Check subject accuracy, placement, session correctness, credit-point totals, prerequisites, and required output sections. "
                "Return ONLY JSON."
            )),
            HumanMessage(content=eval_prompt),
        ])

        try:
            data = extract_and_parse_json(response.content)

            if not isinstance(data, dict):
                raise ValueError(
                    "Stage 2 evaluator returned "
                    "invalid JSON."
                )

            if data.get("valid"):
                return {
                    "plan_feedback": None,
                    "stage2_retry_count": 0,
                }

            return {
                "plan_feedback": data.get("feedback", "Invalid plan."),
                "stage2_retry_count": retries + 1,
            }

        except Exception as e:
            print("STAGE 2 EVAL ERROR:", repr(e))

            return {
                "plan_feedback": "Failed to parse evaluation output.",
                "stage2_retry_count": retries + 1,
            }

    # STAGE 2 EVALUATION ROUTER
    def route_stage2_evaluation(
        state: AdvisorState,
    ) -> Literal[
        "stage2_make_plan",
        "format_output",
    ]:
        retries = state.get("stage2_retry_count", 0)

        feedback = state.get("plan_feedback")

        # Valid.
        if not feedback:
            return "format_output"

        # Retry exhausted.
        if retries >= MAX_STAGE2_RETRIES:
            print("STAGE 2 retry limit reached")

            return "format_output"

        return "stage2_make_plan"

    # FINAL OUTPUT
    async def format_output(
        state: AdvisorState,
    ) -> dict:
        """
        Produce final output.

        If validation failed after the allowed retries, the
        latest generated plan is still returned rather than
        silently discarding it.
        """
        print("NODE: format_output")

        plan = state.get("plan")

        if not plan:
            plan = (
                "Unable to complete plan generation. Please provide or confirm the required degree information."
            )

        return {
            "messages": [AIMessage(content=plan)],
            "planning_requested": False,
            "conversation_mode": "post_plan"
        }

# ------------------------------------------------------------------------------

    # Build state graph
    graph = StateGraph(AdvisorState)

    # graph nodes
    # Conversational / metadata phase nodes + tool - get all info from user
    graph.add_node("parse_input", parse_input)
    graph.add_node("agent", agent)

    confirm_tool_node = ToolNode(conversation_confirm_tools)

    async def run_confirm_tools(
        state: AdvisorState,
    ) -> dict:
        print("NODE: tools")
        return await confirm_tool_node.ainvoke(state)

    graph.add_node("tools", run_confirm_tools)
    graph.add_node("capture_tool_results", capture_tool_results)

    # Handbook phase nodes
    graph.add_node("ensure_handbook", ensure_handbook)
    graph.add_node("handbook_missing", handbook_missing)

    # Stage 1 nodes
    graph.add_node("start_planning", start_planning)
    graph.add_node("fetch_elective_list", fetch_elective_list)
    graph.add_node("stage1_review_must_includes", stage1_review_must_includes)
    graph.add_node("evaluate_required_subjects", evaluate_required_subjects)

    # Stage 2 nodes + tool
    graph.add_node("stage2_make_plan", stage2_make_plan)

    stage2_tool_node = ToolNode(skills["full"])

    async def run_stage2_tools(
        state: AdvisorState,
    ) -> dict:
        print("NODE: stage2_tools")
        return await stage2_tool_node.ainvoke(state)

    graph.add_node("stage2_tools", run_stage2_tools)
    graph.add_node("capture_stage2_tool_results", capture_stage2_tool_results)
    graph.add_node("evaluate_stage2", evaluate_stage2)

    # Final output node
    graph.add_node("format_output", format_output)


    # Graph edges

    # entry edge = start node
    graph.add_edge(START, "parse_input")          # from user input get any given metadata (commencement year, degree, major, campus, enrolment)
    graph.add_edge("parse_input", "agent")        # give the information to the agent

    # the agent then determines what needs to be done
    # either:
    # 1. use tools to wait for a used tool to return request
    # 2. get the handbook from the user info
    # 3. start planning the study plan with the user info and handbook
    # 4. end the graph execution due to lack of info or if a plan is not requested. This will then output the agent response. aka asking for more info
    graph.add_conditional_edges(
        "agent", route_after_agent,
        {
            "tools": "tools",
            "ensure_handbook": "ensure_handbook",
            "start_planning": "start_planning",
            END: END,
        },
    )

    # Conversational tools goes to capture results goes to agent
    graph.add_edge("tools", "capture_tool_results")
    graph.add_edge("capture_tool_results", "agent")

    # get the handbook. Either:
    # 1. handbook exists for given student data so go to start planning
    # 2. OR handbook does not exist
    graph.add_conditional_edges(
        "ensure_handbook", route_after_handbook_fetch,
        {
            "start_planning": "start_planning",
            "handbook_missing": "handbook_missing",
        },
    )

    # if handbook does not exist, exit and inform the user
    graph.add_edge("handbook_missing", END)

    # Start planning goes to get electives
    graph.add_edge("start_planning", "fetch_elective_list")

    # once we have electives go get the needed subjects from the handbook (core and/or major/s)
    graph.add_edge("fetch_elective_list", "stage1_review_must_includes")

    # review the found core and major/s subjects
    graph.add_edge("stage1_review_must_includes", "evaluate_required_subjects")

    # check the result of the evaluation of the needed subjects. Either:
    # 1. The evaluation found an issue, so go back to stage1_review_must_includes and pass the feedback into the prompt
    # 2. OR the evaluation passes, so go on to stage2 to start making the plan
    graph.add_conditional_edges(
        "evaluate_required_subjects", route_stage1_evaluation,
        {
            "stage1_review_must_includes": "stage1_review_must_includes",
            "stage2_make_plan": "stage2_make_plan",
        },
    )

    # during making a plan either:
    # 1. the LLM needs to make a tool call, in which case go to stage2_tools
    # 2. OR the plan has been successfully made, so go to the evaluation node
    graph.add_conditional_edges(
        "stage2_make_plan", route_after_stage2_make_plan,
        {
            "stage2_tools": "stage2_tools",
            "evaluate_stage2": "evaluate_stage2",
        },
    )

    # from stage2_tools, get the tool results
    graph.add_edge("stage2_tools","capture_stage2_tool_results")
    # give the tool results back to stage2_make_plan to use to make the plan
    graph.add_edge("capture_stage2_tool_results", "stage2_make_plan")

    # evaluation of stage2 will either:
    # 1. find that the plan is missing some information or is incorrect, so go back to stage2_make_plan while passing in the feedback of issues
    # 2. OR the evaluation will pass, so go to output the plan
    graph.add_conditional_edges(
        "evaluate_stage2", route_stage2_evaluation,
        {
            "stage2_make_plan": "stage2_make_plan",
            "format_output": "format_output"
        },
    )

    # Final output of plan, the graph workflow then ends.
    graph.add_edge("format_output", END,)

    # compile the graph
    return graph.compile(checkpointer=checkpointer)
