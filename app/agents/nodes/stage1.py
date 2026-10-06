"""Stage 1 nodes: elective candidates and required/core subjects, built in parallel.

    start_planning ─┬─> fetch_elective_list ──────────┐
                    └─> stage1_review_must_includes ──┴─> join_stage1 (deferred)
    join_stage1 -> eval_stage1_lists | stage2_make_plan | END
    eval_stage1_lists -> stage1_review_must_includes (retry) | stage2_make_plan

The branches are independent: electives come from handbook data scored in
code, core subjects from the model. They write disjoint state keys
(`electives` vs `remaining_subjects`/`remaining_feedback`), which LangGraph
requires of nodes running in the same superstep.

join_stage1 is registered with defer=True, so it runs only once no other task
is pending. It therefore waits for both branches on the first pass and still
fires when a retry reruns the core branch alone.
"""
import asyncio
import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END

from app.agents.llms import LLMRegistry
from app.agents.state import (
    MAX_STAGE1_RETRIES,
    PLANNING_RESET,
    AdvisorState,
    extract_and_parse_json,
    handbook_matches_current_meta,
    stage1_electives_from_advisor_state,
)
from app.prompts.builder import build_system_prompt
from app.prompts.prompts import EVAL_SUBJECTS_ELECTIVES, SUBJECT_GENERATION_PROMPT


class Stage1Nodes:
    """Stage 1: elective candidates and required/core subjects."""

    def __init__(self, llms: LLMRegistry) -> None:
        self._llms = llms

    @staticmethod
    async def start_planning(state: AdvisorState) -> dict:
        """Consume planning_requested exactly once and reset planning state."""
        print("NODE: start_planning")

        if not handbook_matches_current_meta(state):
            print("START PLANNING BLOCKED: handbook invalid")
            return {"planning_requested": False}

        return {
            "planning_requested": False,
            "conversation_mode": "planning",
            **PLANNING_RESET,
        }

    @staticmethod
    async def fetch_elective_list(state: AdvisorState) -> dict:
        """Rank electives from handbook data, with no model call.

        Reads the course's scraped elective pools, subject catalog and course
        rules; drops core, major, completed and enrolled subjects and those
        with unmet prerequisites; scores the rest by keyword overlap with the
        major description or the student's interests.
        """
        print("NODE: fetch_elective_list")

        if not handbook_matches_current_meta(state):
            print("STAGE 1 ELECTIVES BLOCKED: handbook invalid")
            return {}

        # CPU-bound and synchronous: run it off the event loop so the core
        # branch's model call keeps making progress in parallel.
        electives = await asyncio.to_thread(stage1_electives_from_advisor_state, state)
        return {"electives": electives}

    async def generate_core_subjects(self, state: AdvisorState) -> dict:
        """Ask the model for the required/core subjects, folding in evaluator
        feedback on a retry."""
        print("NODE: stage1_review_must_includes")

        if not handbook_matches_current_meta(state):
            print("STAGE 1 REQUIRED SUBJECTS BLOCKED")
            return {}

        prompt = build_system_prompt(
            prompt=SUBJECT_GENERATION_PROMPT,
            meta=state.get("meta"),
            meta_confirmed=state.get("meta_confirmed", False),
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )
        feedback = state.get("remaining_feedback")
        if feedback:
            prompt += f"\n\nCORRECT THE FOLLOWING ISSUES FROM PREVIOUS PASS:\n{feedback}"

        response = await self._llms.get("full").ainvoke([
            SystemMessage(content=(
                "You are an academic course planning assistant. "
                "Return the required/core subjects as JSON. Do not call tools."
            )),
            HumanMessage(content=prompt),
        ])

        parsed = extract_and_parse_json(response.content)
        content = parsed if isinstance(parsed, str) else json.dumps(parsed)

        return {"remaining_subjects": content, "remaining_feedback": None}

    @staticmethod
    def join(state: AdvisorState) -> dict:
        """Fan-in point. Registered with defer=True, so it runs once every
        pending branch has finished."""
        print("NODE: join_stage1")
        return {}

    @staticmethod
    def route_join_barrier(
        state: AdvisorState,
    ) -> Literal["eval_stage1_lists", "stage2_make_plan", END]:
        if not handbook_matches_current_meta(state):
            print("STAGE 1 STOPPED: handbook invalid")
            return END
        # On the last allowed pass a failing verdict could not trigger another
        # retry, so evaluating would only spend a model call.
        if state.get("stage1_retry_count", 0) + 1 >= MAX_STAGE1_RETRIES:
            print("STAGE 1 final pass: skipping evaluation")
            return "stage2_make_plan"
        return "eval_stage1_lists"

    async def evaluate(self, state: AdvisorState) -> dict:
        """Evaluate only the required/core-subject list. The elective list comes
        from handbook data and is not second-guessed by a model."""
        print("NODE: eval_stage1_lists")

        retries = state.get("stage1_retry_count", 0)

        eval_prompt = build_system_prompt(
            prompt=EVAL_SUBJECTS_ELECTIVES,
            meta=state.get("meta"),
            meta_confirmed=state.get("meta_confirmed", False),
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )
        eval_prompt = (
            eval_prompt
            .replace("{{electives}}", state.get("electives") or "")
            .replace("{{remaining_subjects}}", state.get("remaining_subjects") or "")
        )

        response = await self._llms.get("parser").ainvoke([
            SystemMessage(content=(
                "You are an academic auditor checking course list accuracy. "
                "Evaluate ONLY the required/core subjects. Do not evaluate, validate, or score "
                "the elective list; electives come from a deterministic non-LLM service. "
                "Return ONLY JSON."
            )),
            HumanMessage(content=eval_prompt),
        ])

        try:
            data = extract_and_parse_json(response.content)
            if not isinstance(data, dict):
                raise ValueError("Stage 1 evaluator did not return an object.")
            feedback = (
                None
                if data.get("remaining_valid")
                else data.get("remaining_feedback") or "Invalid core subjects."
            )
        except Exception as exc:
            print("REQUIRED SUBJECT EVAL ERROR:", repr(exc))
            feedback = "Failed to parse validation output."

        return {"remaining_feedback": feedback, "stage1_retry_count": retries + 1}

    @staticmethod
    def route_stage1_eval(
        state: AdvisorState,
    ) -> Literal["stage1_review_must_includes", "stage2_make_plan"]:
        if not state.get("remaining_feedback"):
            return "stage2_make_plan"
        if state.get("stage1_retry_count", 0) >= MAX_STAGE1_RETRIES:
            print("STAGE 1 retry limit reached")
            return "stage2_make_plan"
        return "stage1_review_must_includes"
