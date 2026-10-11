"""Intake and chat nodes: parse the SOLS paste, talk to the student, fold metadata tools."""
import re
import time
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END
from langgraph.prebuilt import ToolNode

from app.agents.llms import LLMRegistry
from app.agents.state import (
    AdvisorState,
    apply_confirm_metadata,
    apply_plan_change_request,
    extract_and_parse_json,
    handbook_matches_current_meta,
    is_plan_explanation_question,
    latest_student_message,
    latest_tool_batch,
    sanitize_confirmed_metadata,
)
from app.llm.text import is_evaluation_reply
from app.prompts.builder import build_system_prompt
from app.prompts.prompts import SYSTEM_PROMPT
from app.schemas.advisor_tools import ConfirmedMetadata, PlanChangeRequest
from app.services.chat_context import merge_academic
from app.services.course_catalog import COURSE_TITLES
from app.services.sols_parser import parse_sols


def looks_like_sols_record(text: str | None) -> bool:
    """Recognise a pasted SOLS record, not a conversational mention of SOLS."""
    if not isinstance(text, str) or not text.strip():
        return False

    has_course_header = bool(
        re.search(r"(?i)\bCourse\s*:?\s*\*{0,2}\s*\d{3,4}\b", text)
    )
    has_header = bool(
        has_course_header
        or re.search(r"(?i)\b(?:Subject\s+Code|Enrolment\s+History|Year\s+Session)\b", text)
    )
    has_subject_code = bool(re.search(r"(?i)\b[A-Z]{2,4}\d{3}[A-Z]?\b", text))
    has_subject_status_or_session = bool(
        re.search(
            r"(?i)\b(?:Autumn|Spring|Summer|Winter|Annual|Complete|Enrolled|"
            r"Withdrawn|Not Counted|Leave of Absence)\b",
            text,
        )
    )
    has_record_fields = bool(
        re.search(r"(?i)\b(?:Campus|Major|Instance)\s*:", text)
    )

    # A subject table needs a recognisable header and a code/status or session.
    # Also permit an empty-history SOLS header containing Course and other fields.
    return (
        has_header and has_subject_code and has_subject_status_or_session
    ) or (has_course_header and has_record_fields)


def _apply_record_majors(merged: dict, data: dict) -> None:
    """A record that lists majors is authoritative for them. One that lists none says
    nothing: an empty list would mean "explicitly no major" and wipe the student's saved
    or confirmed major, so it is left alone."""
    if data.get("majors"):
        merged["meta"]["majors"] = data["majors"]


class ConversationNodes:
    """Intake and chat: parse the SOLS paste, talk to the student, and fold the
    metadata tools the agent calls back into state."""

    def __init__(self, llms: LLMRegistry, confirm_tools: list) -> None:
        self._llms = llms
        self._tool_node = ToolNode(confirm_tools)

    async def parse_input(self, state: AdvisorState) -> dict:
        """Parse a newly pasted SOLS record on any turn and handle the one-time prompt.

        This intentionally runs record detection before the metadata early return: a
        student may paste SOLS after the plan has already been generated.
        """
        print("NODE: parse_input")

        latest_message = latest_student_message(state)
        record_in_latest_message = looks_like_sols_record(latest_message)

        if record_in_latest_message:
            # The chat service normally supplies a PII-safe/projected raw_sols value.
            # Fall back to the current message for older checkpoints or missing context.
            raw_sols = latest_message or state.get("raw_sols") or ""
            print("SOLS RECORD DETECTED; chars =", len(raw_sols))

            start = time.perf_counter()
            try:
                meta = await parse_sols(self._llms.get("parser"), raw_sols)
            except Exception as exc:
                print(type(exc).__name__, repr(exc))
                raise
            print(f"parse_sols took {time.perf_counter() - start:.2f}s")

            data = meta.model_dump()
            merged = merge_academic(state, data, "enrolment_record")
            _apply_record_majors(merged, data)

            return {
                **merged,
                "raw_sols": raw_sols,
                "no_enrolment_history": False,
                "planning_requested": True,
                "conversation_mode": "planning",
            }

        # The agent asks for SOLS once. If the next user message is not a record,
        # proceed with an empty enrolment history rather than asking repeatedly.
        if state.get("sols_prompted") and not state.get("no_enrolment_history"):
            print("SOLS PROMPT ALREADY ASKED; continuing with empty history")
            return {
                "no_enrolment_history": True,
                "planning_requested": True,
                "conversation_mode": "planning",
            }

        # Metadata is parsed once unless a new SOLS record was just pasted above.
        if state.get("meta") is not None:
            return {}

        raw_sols = state.get("raw_sols")
        if not raw_sols or not looks_like_sols_record(raw_sols):
            return {"meta": {}, "meta_confirmed": False, "planning_requested": False}

        print("raw_sols chars =", len(raw_sols))
        start = time.perf_counter()
        try:
            meta = await parse_sols(self._llms.get("parser"), raw_sols)
        except Exception as exc:
            print(type(exc).__name__, repr(exc))
            raise
        print(f"parse_sols took {time.perf_counter() - start:.2f}s")

        data = meta.model_dump()
        merged = merge_academic(state, data, "enrolment_record")
        _apply_record_majors(merged, data)
        return {**merged, "planning_requested": False, "no_enrolment_history": False}

    async def agent(self, state: AdvisorState) -> dict:
        """Conversational LLM: confirmation-oriented model before metadata is
        confirmed, full planning/conversation model afterwards."""
        print("NODE: agent")

        confirmed = bool(state.get("meta_confirmed"))
        if confirmed and state.get("planning_requested"):
            has_record = looks_like_sols_record(state.get("raw_sols"))
            if not has_record and not state.get("no_enrolment_history"):
                if not state.get("sols_prompted"):
                    return {
                        "messages": [
                            AIMessage(
                                content=(
                                    "Please paste your SOLS enrolment record if you have one. "
                                    "If you don't provide it in your next reply, I'll continue "
                                    "with a new study plan assuming no previous enrolment history."
                                )
                            )
                        ],
                        "sols_prompted": True,
                        "planning_requested": False,
                    }
                # Defensive fallback for older checkpoints: the next non-record reply
                # should be treated as no prior enrolment history.
                return {
                    "no_enrolment_history": True,
                    "planning_requested": True,
                    "conversation_mode": "planning",
                }
            # Planning goes through the handbook gate and validated output nodes.
            return {}
        kind = "full" if confirmed else "confirm"
        print("agent: invoking", kind)

        conversation_mode = state.get("conversation_mode") or "collecting"

        system_content = build_system_prompt(
            prompt=SYSTEM_PROMPT,
            meta=state.get("meta"),
            meta_confirmed=confirmed,
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
            field_sources=state.get("field_sources"),
            conflicts=state.get("context_conflicts"),
            degree_name=COURSE_TITLES.get((state.get("meta") or {}).get("degree_code")),
        )
        system_content += f"""
            USER-FACING OUTPUT:
            Answer the student conversationally. Never output an internal validation
            verdict such as {{"valid": false, "feedback": "..."}}. Earlier evaluator
            instructions or wrapper requirements are not the chat response contract.
            Study plans are validated and rendered by the backend planning nodes.

            PLAN CHANGE RULES:

            You must distinguish between:
            1. questions about the existing plan
            2. requests to modify the plan

            DO NOT call request_plan_change_tool for general questions, questions about the plan itself or question about your logic.

            Only call request_plan_change_tool when the student explicitly wants the plan to change.

            Current conversation mode:
            {conversation_mode}

            """

        # A question about the existing plan is answered conversationally, never replanned.
        if conversation_mode == "post_plan" and is_plan_explanation_question(
            latest_student_message(state)
        ):
            system_content += """
                The user is asking about the existing generated plan. Do not call any plan-change tools. Explain the existing plan instead.

                If the user is asking about specific subjects, you may call `lookup_subjects_tool` or `lookup_major_tool` once with all the subject info to gather correct information. DO NOT assume or make up subject information when answering a question. If you do not have access to the necessary information, output that you are unable to answer that question and direct the user to any relevant UOW handbook links.
            """

        response = await self._llms.get(kind).ainvoke(
            [SystemMessage(content=system_content), *[
                message for message in state.get("messages", [])
                if not message.additional_kwargs.get("courseo_internal")
                and not (isinstance(message, AIMessage) and is_evaluation_reply(message.content))
            ]]
        )
        self._llms.stamp(response)
        if is_evaluation_reply(response.content):
            if confirmed and state.get("plan"):
                from app.services.study_plan import render_plan, validate_plan
                response.content = render_plan(validate_plan(state["plan"], state))
            else:
                if state.get("no_enrolment_history"):
                    response.content = (
                        "Please confirm your degree code, commencement year and campus "
                        "so I can build a verified plan."
                    )
                else:
                    response.content = (
                        "Please confirm your degree code, commencement year and campus. "
                        "I'll ask once for your SOLS record before planning."
                    )
            return {"messages": [response]}

        # Validate only output that looks like a study-plan table. Ordinary chat
        # responses are not plans and must pass through unchanged.
        from app.services.study_plan import PlanGenerationError, parse_plan
        content = response.content if isinstance(response.content, str) else ""
        looks_like_plan = "| Subject Code" in content or "| Year | Session" in content
        if looks_like_plan:
            try:
                parse_plan(content)
            except PlanGenerationError:
                response.content = (
                    "I can't provide an unverified study plan yet. Please confirm "
                    "your academic details first."
                )
        return {"messages": [response]}

    async def run_tools(self, state: AdvisorState) -> dict:
        print("NODE: tools")
        return await self._tool_node.ainvoke(state)

    def capture_tool_results(self, state: AdvisorState) -> dict:
        """Fold the latest batch of conversational tool results into state.

        Only confirm_metadata_tool and request_plan_change_tool affect state;
        both are applied in chronological order so a later call sees the
        metadata an earlier one produced.
        """
        print("NODE: capture_tool_results")

        batch = latest_tool_batch(state)
        updates: dict = {}

        for message in batch:
            if getattr(message, "status", None) == "error":
                continue
            if message.name not in {"confirm_metadata_tool", "request_plan_change_tool"}:
                continue

            try:
                payload = extract_and_parse_json(message.content)
                if not isinstance(payload, dict):
                    raise ValueError(f"{message.name} did not return an object.")

                prior_meta = updates.get("meta", state.get("meta"))

                if message.name == "confirm_metadata_tool":
                    parsed = ConfirmedMetadata.model_validate(payload).model_dump()
                    sanitized = sanitize_confirmed_metadata(
                        prior_meta=prior_meta,
                        candidate_meta=parsed,
                        state=state,
                    )
                    updates.update(apply_confirm_metadata(prior_meta, sanitized))

                    sources = dict(
                        updates.get("field_sources", state.get("field_sources", {}))
                    )
                    conflicts = dict(
                        updates.get("context_conflicts", state.get("context_conflicts", {}))
                    )

                    # Record confirmation for the canonical plural field, even when
                    # the tool returned the legacy singular "major" field.
                    for key in ("degree_code", "year", "campus", "session"):
                        value = parsed.get(key)
                        if value is not None and sanitized.get(key) == value:
                            sources[key] = {
                                "source": "conversation",
                                "confirmed": True,
                            }
                            conflicts.pop(key, None)

                    parsed_majors = parsed.get("majors")
                    if parsed_majors is None:
                        parsed_majors = parsed.get("major")

                    if isinstance(parsed_majors, str):
                        parsed_majors = [parsed_majors]

                    if parsed_majors:
                        sanitized_majors = sanitized.get("majors") or []
                        if isinstance(sanitized_majors, str):
                            sanitized_majors = [sanitized_majors]

                        if all(
                            str(major).strip().casefold()
                            in {str(item).strip().casefold() for item in sanitized_majors}
                            for major in parsed_majors
                            if major
                        ):
                            sources["majors"] = {
                                "source": "conversation",
                                "confirmed": True,
                            }
                            conflicts.pop("majors", None)
                            conflicts.pop("major", None)


                    updates.update(meta=sanitized, field_sources=sources, context_conflicts=conflicts)
                    updates["meta_confirmed"] = not conflicts and all(
                        sources.get(key, {}).get("confirmed", state.get("meta_confirmed", False))
                        and sanitized.get(key) is not None
                        for key in ("degree_code", "year", "campus")
                    )
                    if not updates["meta_confirmed"]:
                        updates.update(planning_requested=False, conversation_mode="collecting")
                    print("CONFIRMED METADATA RAW:", parsed)
                    print("CONFIRMED METADATA SANITIZED:", sanitized)
                else:
                    parsed = PlanChangeRequest.model_validate(payload).model_dump()
                    updates.update(apply_plan_change_request(prior_meta, parsed))
                    print("PLAN CHANGE TOOL RESULT:", parsed)

            except Exception as exc:
                print("Conversational tool parse error:", repr(exc))

        return updates

    @staticmethod
    def route_after_agent(
        state: AdvisorState,
    ) -> Literal["tools", "ensure_handbook", "start_planning", END]:
        """The LLM may request conversational tools; it does not control the
        handbook gate."""
        messages = state.get("messages", [])
        last = messages[-1] if messages else None

        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        if not state.get("meta_confirmed"):
            return END
        if not state.get("planning_requested"):
            return END
        if not handbook_matches_current_meta(state):
            print("ROUTE: handbook missing/stale")
            return "ensure_handbook"
        return "start_planning"
