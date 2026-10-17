"""Stage 1 nodes: elective recommendations and required/core subjects.

    Initial plan generation:
        start_planning
            |
            v
        stage1_review_must_includes
            |  Generate required/core subjects
            v
        eval_stage1_lists
            |
            v
        route_stage1_eval
            |-----------------------------|
            v                             v
        stage1_review_must_includes    stage2_make_plan
        (retry)                        (continue)

    Elective recommendations (when requested):
        agent / ensure_handbook
            |
            v
        fetch_elective_list
            |
            v
           END

    Updating electives in an existing plan (when requested):
        agent / ensure_handbook
            |
            v
        populate_plan_electives
            |
            v
           END

    fetch_elective_list obtains deterministic elective recommendations
    using the student's current request and saved ranking preferences.
    It explains the supplied results without rebuilding the study plan.

    populate_plan_electives updates elective placeholders in the existing
    plan. It ranks candidates, merges captured subject lookup results, and
    asks the model to preserve the rest of the plan while updating electives.

    Required/core subjects are generated separately by the model. Only this
    list is evaluated and retried. The evaluator does not validate or score
    the elective list, which is supplied by the deterministic ranking service.

    The elective paths terminate independently; neither automatically
    continues to stage2_make_plan. Handbook validity and routing are handled
    by the graph's ensure_handbook and route_after_fetch logic.
"""
import asyncio
import json
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END

from app.agents.llms import LLMRegistry
from app.agents.state import (
    MAX_STAGE1_RETRIES,
    PLANNING_RESET,
    AdvisorState,
    _message_text,
    extract_and_parse_json,
    handbook_matches_current_meta,
    get_ranking_preferences,
    latest_user_request,
    stage1_electives_from_advisor_state,
)
from app.prompts.builder import build_system_prompt
from app.prompts.prompts import (
    EVAL_SUBJECTS_ELECTIVES,
    POPULATE_ELECTIVES_IN_PLAN,
    SUBJECT_GENERATION_PROMPT,
)
import re

def merge_elective_candidates(
        ranked_json: str,
        lookup_results: list[dict],
    ) -> str:
        """Merge lookup results into ranked candidates, deduplicated by code."""
        try:
            payload = json.loads(ranked_json)
        except (json.JSONDecodeError, TypeError):
            payload = {}

        if not isinstance(payload, dict):
            payload = {}

        subjects = payload.setdefault("subjects", [])
        if not isinstance(subjects, list):
            subjects = []
            payload["subjects"] = subjects

        seen = {
            str(item.get("code") or "").strip().upper()
            for item in subjects
            if isinstance(item, dict)
        }

        for subject in lookup_results:
            if not isinstance(subject, dict):
                continue

            code = str(subject.get("code") or "").strip().upper()
            match = re.fullmatch(r"[A-Z]{2,6}(\d{3})[A-Z]?", code)

            if not match or int(match.group(1)[0]) not in {1, 2, 3}:
                continue

            if code in seen:
                continue

            # Do not fabricate the ranking or eligibility fields.
            # Keep the source record intact for explicit normalization/validation.
            subjects.append(subject)
            seen.add(code)

        return json.dumps(payload, ensure_ascii=False, default=str)

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

    
    async def extract_request_elective_interests(
        self,
        state: AdvisorState,
    ) -> list[str]:
        """Extract elective interests explicitly expressed in the latest message."""

        request = latest_user_request(state).strip()
        if not request:
            return []

        response = await self._llms.get("parser").ainvoke([
            SystemMessage(content=(
                "Extract topics the student explicitly wants to use "
                "to choose university electives. Return JSON only, "
                'in this format: {"interests": ["topic"]}. '
                "Only extract topics relevant to an elective request. "
                "Do not use saved preferences or infer unrelated interests. "
                "If no elective interest is explicitly requested, return "
                '{"interests": []}.'
            )),
            HumanMessage(content=request),
        ])

        parsed = extract_and_parse_json(response.content)
        if not isinstance(parsed, dict):
            return []

        interests = parsed.get("interests", [])
        if isinstance(interests, str):
            interests = [interests]

        if not isinstance(interests, list):
            return []

        return list(dict.fromkeys(
            str(item).strip()
            for item in interests
            if isinstance(item, str) and item.strip()
        ))


    
    async def fetch_elective_list(self, state: AdvisorState) -> dict:
        """Retrieve and rank electives using current or saved preferences."""
        print("NODE: fetch_elective_list")

        if not handbook_matches_current_meta(state):
            print("STAGE 1 ELECTIVES BLOCKED: handbook invalid")
            return {}

        request_interests = await self.extract_request_elective_interests(
            state
        )

        ranking_state = get_ranking_preferences(
            state,
            request_interests=request_interests,
        )

        print("CURRENT REQUEST INTERESTS:", request_interests)
        print("EFFECTIVE RANKING INTERESTS:",
              ranking_state.get("elective_interests"))

        # Run the existing ranking service without blocking the event loop.
        electives = await asyncio.to_thread(
            stage1_electives_from_advisor_state,
            ranking_state,
        )

        response = await self._llms.get("full").ainvoke([
            SystemMessage(content=(
                "You are a university course planning assistant. "
                "Explain the supplied elective recommendations clearly. "
                "Give each elective a succinct paragraph describing the "
                "subject and why it relates to the student's request. "
                "Use only the supplied results. Do not invent subjects, "
                "eligibility claims, prerequisites, or availability. "
                "If no electives are available, explain that clearly."
            )),
            HumanMessage(content=electives),
        ])

        return {
            "messages": [
                AIMessage(content=_message_text(response).strip())
            ],
            "electives": electives,
            "request_elective_interests": request_interests,
            "pending_elective_action": None,
            "electives_feedback": None,
        }



    async def populate_plan_electives(self, state: AdvisorState) -> dict:
        """Add valid elective candidates to the existing plan without rebuilding it."""
        print("NODE: populate_plan_electives")
        # print("PLANNNNNN: ", state.get('plan'))

        if not handbook_matches_current_meta(state):
            print("POPULATE ELECTIVES BLOCKED: handbook invalid")
            return {}

        current_plan = state.get("plan")
        if not current_plan:
            print("POPULATE ELECTIVES BLOCKED: no existing plan")
            return {
                "pending_elective_action": "recommend",
            }

        request_interests = await self.extract_request_elective_interests(
            state
        )

        ranking_state = get_ranking_preferences(
            state,
            request_interests=request_interests,
        )

        # print("POPULATE CURRENT REQUEST INTERESTS:", request_interests)
        # print("POPULATE EFFECTIVE INTERESTS:",
        #       ranking_state.get("elective_interests"))

        candidates = await asyncio.to_thread(
            stage1_electives_from_advisor_state,
            ranking_state,
        )

        print("\ncandidates from call: ", candidates)

        candidates = merge_elective_candidates(
            candidates,
            state.get("elective_lookup_results") or [],
        )

        print("\nelective lookup result: ", state.get("elective_lookup_codes"))

        print("\ncandidates = merged: ", candidates)

        if not candidates:
            print("POPULATE ELECTIVES: no valid elective candidates")
            return {
                "electives_feedback": (
                    "No valid elective candidates were available. "
                    "The existing plan has not been changed."
                ),
                "pending_elective_action": None,
            }

        # Preserve the current plan and give the model its exact contents.
        if isinstance(current_plan, str):
            current_plan_text = current_plan
        else:
            current_plan_text = json.dumps(
                current_plan,
                ensure_ascii=False,
                indent=2,
            )

        candidates_text = json.dumps(
            candidates,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

        # print("current plan: ", state.get("plan"))

        prompt = build_system_prompt(
            prompt=POPULATE_ELECTIVES_IN_PLAN,
            meta=state.get("meta"),
            meta_confirmed=state.get("meta_confirmed", False),
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )

        prompt += f"""

EXISTING PLAN — SOURCE OF TRUTH:
{current_plan_text}

VALID ELECTIVE CANDIDATES:
{candidates_text}
"""

        feedback = state.get("electives_feedback")
        if feedback:
            prompt += f"""

                ISSUES TO CORRECT:
                {feedback}
                """

        response = await self._llms.get("full").ainvoke([
            SystemMessage(content=(
                "You are updating an existing UOW study plan. "
                "Change eligible elective placeholders or electives that are not completed or currently enrolled only. "
                "Preserve every other part of the existing plan. "
                "Return the complete response using the output format specified in the supplied system instructions, including "
                "the audit, study-plan table, credit-point summary, and final JSON code fence. "
                "Do not call tools."
            )),
            HumanMessage(content=prompt),
        ])

        response_text = _message_text(response).strip()

        # try:
        #     updated_plan = extract_and_parse_json(response_text)

        #     if not isinstance(updated_plan, (dict, list)):
        #         raise ValueError(
        #             "Updated plan must be a JSON object or array."
        #         )

        #     updated_plan_text = json.dumps(
        #         updated_plan,
        #         ensure_ascii=False,
        #     )

        # except (ValueError, TypeError, json.JSONDecodeError) as exc:
        #     print("POPULATE ELECTIVES: invalid plan JSON:", repr(exc))
        #     return {
        #         "electives_feedback": (
        #             "The updated plan could not be parsed as valid JSON. "
        #             "The existing plan has not been changed."
        #         ),
        #         "pending_elective_action": None,
        #     }

        print("POPULATE ELECTIVES: updated plan parsed successfully")
        # print("plannnn: ", response_text)

        return {
            "plan": response_text,
            "messages": [AIMessage(content=response_text)],
            "electives_feedback": None,
            "pending_elective_action": None,
            "elective_lookup_results": [],
            "elective_lookup_codes": []
        }

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
