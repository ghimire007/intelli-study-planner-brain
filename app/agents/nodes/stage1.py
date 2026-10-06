"""Stage 1 nodes: elective candidates and required/core subjects, built in parallel.

    start_planning ─┬─> fetch_elective_list ──────────┐
                    └─> stage1_review_must_includes ──┴─> join_stage1 (deferred)
    join_stage1 -> eval_stage1_lists | stage2_make_plan | END
    eval_stage1_lists -> stage1_review_must_includes (retry) | stage2_make_plan

The branches are independent: electives come from handbook data scored in
code, core subjects directly from structured handbook data. They write disjoint state keys
(`electives` vs `remaining_subjects`/`remaining_feedback`), which LangGraph
requires of nodes running in the same superstep.

join_stage1 is registered with defer=True, so it runs only once no other task
is pending. It therefore waits for both branches on the first pass and still
fires when a retry reruns the core branch alone.
"""
import asyncio
import json
from typing import Literal

from langgraph.graph import END

from app.agents.llms import LLMRegistry
from app.agents.state import (
    MAX_STAGE1_RETRIES,
    PLANNING_RESET,
    AdvisorState,
    handbook_matches_current_meta,
    stage1_electives_from_advisor_state,
)


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

        # CPU-bound ranking must not block the event loop.
        electives = await asyncio.to_thread(stage1_electives_from_advisor_state, state)
        return {"electives": electives}

    async def generate_core_subjects(self, state: AdvisorState) -> dict:
        """Use structured handbook requirements directly, without another model call."""
        from app.services.study_plan import plan_sources

        if not handbook_matches_current_meta(state):
            return {}
        catalog, rules, required, choices = plan_sources(state)
        data = {
            "required_subjects": [{"code": code, "name": catalog[code]["title"], "cp": int(catalog[code]["cp"])}
                                  for code in sorted(required) if code in catalog],
            "core_selection": sorted(rules.core_selection),
            "additional_choices": choices,
            "total_cp": rules.total_cp,
        }
        return {"remaining_subjects": json.dumps(data), "remaining_feedback": None}

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
        """Requirements were read from source data; final placements are validated in Stage 2."""
        return {"remaining_feedback": None, "stage1_retry_count": 0}

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
