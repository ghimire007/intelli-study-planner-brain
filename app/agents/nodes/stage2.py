"""Stage 2 nodes: generate the study plan, evaluate it, emit the final message."""
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import ToolNode

from app.agents.llms import LLMRegistry
from app.agents.state import (
    MAX_STAGE2_RETRIES,
    MAX_STAGE2_TOOL_LOOPS,
    AdvisorState,
    _message_text,
    extract_and_parse_json,
    handbook_matches_current_meta,
)
from app.prompts.builder import build_system_prompt
from app.prompts.prompts import EVAL_PLAN, SYSTEM_PROMPT_V1


class Stage2Nodes:
    """Stage 2: generate the study plan (with planning tools), evaluate it,
    and emit the final message."""

    def __init__(self, llms: LLMRegistry, planning_tools: list) -> None:
        self._llms = llms
        self._tool_node = ToolNode(planning_tools)

    async def make_plan(self, state: AdvisorState) -> dict:
        print("NODE: stage2_make_plan")

        if not handbook_matches_current_meta(state):
            print("STAGE 2 BLOCKED: handbook invalid")
            return {"planning_requested": False, "plan": None}

        base_prompt = build_system_prompt(
            prompt=SYSTEM_PROMPT_V1,
            meta=state.get("meta"),
            meta_confirmed=state.get("meta_confirmed", False),
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )
        feedback = state.get("plan_feedback")
        if feedback:
            base_prompt += f"\n\nAddress this previous evaluation feedback: {feedback}"

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

        response = await self._llms.get("full").ainvoke([
            SystemMessage(content=base_prompt),
            *state.get("messages", []),
            HumanMessage(content=content_prompt),
        ])

        updated: dict = {"messages": [response]}

        if not response.tool_calls:
            # A generation that finished without tools closes the tool loop.
            updated["stage2_tool_loop_count"] = 0
            text_plan = _message_text(response).strip()
            if text_plan:
                updated["plan"] = text_plan

        return updated

    async def run_tools(self, state: AdvisorState) -> dict:
        print("NODE: stage2_tools")
        return await self._tool_node.ainvoke(state)

    @staticmethod
    def capture_tool_results(state: AdvisorState) -> dict:
        """Stage 2 tool results stay in the message history; this only bounds
        the tool loop. It deliberately runs no metadata-confirmation logic."""
        print("NODE: capture_stage2_tool_results")
        return {"stage2_tool_loop_count": state.get("stage2_tool_loop_count", 0) + 1}

    @staticmethod
    def route_after_make_plan(state: AdvisorState) -> Literal["stage2_tools", "evaluate_stage2"]:
        messages = state.get("messages", [])
        last = messages[-1] if messages else None

        if isinstance(last, AIMessage) and last.tool_calls:
            if state.get("stage2_tool_loop_count", 0) >= MAX_STAGE2_TOOL_LOOPS:
                print("STAGE 2 tool-loop limit reached")
                return "evaluate_stage2"
            return "stage2_tools"
        return "evaluate_stage2"

    async def evaluate(self, state: AdvisorState) -> dict:
        """Evaluate the generated plan against metadata, handbook, SOLS,
        required subjects and electives."""
        print("NODE: evaluate_stage2")

        retries = state.get("stage2_retry_count", 0)
        plan = state.get("plan")

        if not plan:
            return {"plan_feedback": "No plan was generated.", "stage2_retry_count": retries + 1}

        eval_prompt = EVAL_PLAN.replace("{{PLAN}}", plan) + (
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

        response = await self._llms.get("parser").ainvoke([
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
                raise ValueError("Stage 2 evaluator returned invalid JSON.")
            if data.get("valid"):
                return {"plan_feedback": None, "stage2_retry_count": 0}
            feedback = data.get("feedback", "Invalid plan.")
        except Exception as exc:
            print("STAGE 2 EVAL ERROR:", repr(exc))
            feedback = "Failed to parse evaluation output."

        return {"plan_feedback": feedback, "stage2_retry_count": retries + 1}

    @staticmethod
    def route_evaluation(state: AdvisorState) -> Literal["stage2_make_plan", "format_output"]:
        if not state.get("plan_feedback"):
            return "format_output"
        if state.get("stage2_retry_count", 0) >= MAX_STAGE2_RETRIES:
            print("STAGE 2 retry limit reached")
            return "format_output"
        return "stage2_make_plan"

    @staticmethod
    async def format_output(state: AdvisorState) -> dict:
        """Emit the plan. After exhausted retries the latest plan is still
        returned rather than silently discarded."""
        print("NODE: format_output")

        plan = state.get("plan") or (
            "Unable to complete plan generation. "
            "Please provide or confirm the required degree information."
        )
        return {
            "messages": [AIMessage(content=plan)],
            "planning_requested": False,
            "conversation_mode": "post_plan",
        }
