"""Stage 2 nodes: generate the study plan, evaluate it, emit the final message."""
import json
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

    def __init__(self, llms: LLMRegistry, planning_tools: list, *, no_tools_llms: LLMRegistry) -> None:
        self._llms = llms
        self._no_tools_llms = no_tools_llms
        self._tool_node = ToolNode(planning_tools)

    async def make_plan(self, state: AdvisorState) -> dict:
        # print("NODE: stage2_make_plan")

        if not handbook_matches_current_meta(state):
            # print("STAGE 2 BLOCKED: handbook invalid")
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
            "Execute SYSTEM_PROMPT_V1 in full and in the specified order. "
            "Do not skip, merge, abbreviate, or assume completion of any mandatory stage, "
            "audit section, subject evaluation, or output requirement.\n\n"

            "STAGE 1: Complete the full analysis and audit before constructing the plan. "
            "List every SOLS subject in the required immutable categories and calculate "
            "their credit points exactly. Evaluate every required subject individually. "
            "Include every required session scratchpad and explicitly assess each applicable "
            "eligibility criterion using the available evidence.\n\n"

            "STAGE 2: Construct the plan only after Stage 1 is complete. "
            "Verify every subject against authoritative handbook and lookup data. "
            "Check prerequisites against earlier sessions and corequisites against the "
            "same or earlier sessions, including applicable credit-point thresholds. "
            "Reconcile session loads, degree requirements, category allocations, and total CP.\n\n"

            "VALIDATION: Before responding, audit the entire output against every mandatory "
            "requirement in SYSTEM_PROMPT_V1. Ensure all required sections are present, "
            "all subjects have been evaluated, all calculations reconcile, and the audit, "
            "tables, summary, and JSON agree. Never claim a rule passes without supporting "
            "evidence. If required evidence is missing or ambiguous, identify the limitation "
            "rather than inventing a result.\n\n"

            "FEEDBACK: If previous evaluation feedback is provided, address every reported "
            "issue explicitly. Recheck affected subjects and all dependent session, "
            "prerequisite, corequisite, and CP calculations. Preserve unaffected valid "
            "parts of the plan. Do not ignore feedback or claim a correction without "
            "verifying it.\n\n"

            "Return the complete response in the exact format required by SYSTEM_PROMPT_V1. "
            "Do not replace required analysis with a summary."
        )


        tool_count = state.get("stage2_tool_loop_count", 0)

        if tool_count >= MAX_STAGE2_TOOL_LOOPS:
            llm = self._no_tools_llms.get("full")
            # print("STAGE 2: planning without tools")
        else:
            llm = self._llms.get("full")

        response = await llm.ainvoke([
            SystemMessage(content=base_prompt),
            *state.get("messages", []),
            HumanMessage(content=content_prompt),
        ])

        # print("AGENT RESPONSE TYPE:", type(response).__name__)
        # print("AGENT TOOL CALLS:", getattr(response, "tool_calls", []))
        # print("AGENT RESPONSE TEXT:", _message_text(response)[:500])

        updated: dict = {"messages": [response]}

        if not response.tool_calls:
            updated["stage2_tool_loop_count"] = 0
            text_plan = _message_text(response).strip()

            if text_plan:
                updated["plan"] = text_plan

        return updated

    async def run_tools(self, state: AdvisorState) -> dict:
        # print("NODE: stage2_tools")
        return await self._tool_node.ainvoke(state)

    @staticmethod
    def capture_tool_results(state: AdvisorState) -> dict:
        """Stage 2 tool results stay in the message history; this only bounds
        the tool loop. It deliberately runs no metadata-confirmation logic."""
        # print("NODE: capture_stage2_tool_results")
        return {"stage2_tool_loop_count": state.get("stage2_tool_loop_count", 0) + 1}



    @staticmethod
    def route_after_tool_results(
        state: AdvisorState,
    ) -> Literal["stage2_make_plan"]:
        count = state.get("stage2_tool_loop_count", 0)

        # print(
        #     f"STAGE 2 TOOL LOOPS: "
        #     f"{count}/{MAX_STAGE2_TOOL_LOOPS}"
        # )

        if count >= MAX_STAGE2_TOOL_LOOPS:
            print(
                "STAGE 2 tool limit reached; "
                "returning to make_plan with tools disabled"
            )

        return "stage2_make_plan"



    @staticmethod
    def route_after_make_plan(
        state: AdvisorState,
    ) -> Literal[
        "stage2_tools",
        "evaluate_stage2",
        "format_output",
    ]:
        messages = state.get("messages", [])
        last = messages[-1] if messages else None

        if isinstance(last, AIMessage) and last.tool_calls:
            if (
                state.get("stage2_tool_loop_count", 0)
                >= MAX_STAGE2_TOOL_LOOPS
            ):
                # print(
                #     "ERROR: no-tools model returned tool calls; "
                #     "cannot execute additional tools"
                # )
                return "format_output"

            return "stage2_tools"

        return "evaluate_stage2"


    async def evaluate(self, state: AdvisorState) -> dict:
        """Evaluate the generated plan against metadata, handbook, SOLS,
        required subjects and electives."""
        # print("NODE: evaluate_stage2")

        retries = state.get("stage2_retry_count", 0)
        plan = state.get("plan")

        if not plan:
            return {"plan_feedback": "No plan was generated.", "stage2_retry_count": retries + 1}

        eval_prompt = (
            EVAL_PLAN.replace("{{PLAN}}", plan)
            .replace("{{METADATA}}", json.dumps(state.get("meta", {}), indent=2))
            .replace("{{HANDBOOK}}", state.get("handbook", ""))
            .replace("{{SOLS}}", state.get("raw_sols", ""))
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
        except Exception:
            # print("STAGE 2 EVAL ERROR:", repr(exc))
            feedback = "Failed to parse evaluation output."

        return {"plan_feedback": feedback, "stage2_retry_count": retries + 1}

    @staticmethod
    def route_evaluation(state: AdvisorState) -> Literal["stage2_make_plan", "format_output"]:
        if not state.get("plan_feedback"):
            return "format_output"
        if state.get("stage2_retry_count", 0) >= MAX_STAGE2_RETRIES:
            # print("STAGE 2 retry limit reached")
            return "format_output"
        return "stage2_make_plan"


    @staticmethod
    async def format_output(state: AdvisorState) -> dict:
        """Emit final evaluation feedback before the plan's JSON Markdown."""
        # print("NODE: format_output")

        plan = state.get("plan") or (
            "Unable to complete plan generation. "
            "Please provide or confirm the required degree information."
        )

        feedback = state.get("plan_feedback")

        # Show the final evaluation feedback before the JSON Markdown.
        if feedback:
            feedback_section = (
                "**Plan feedback:**\n"
                "*Your generated plan **currently contains issues**. To ensure Courseo's compatability with free LLM key limits, the plan evaluation loop has been limited. Please ask for your plan to be fixed with the following feedback:*\n"
                f"{feedback.strip()}\n\n"
            )

        else:
            feedback_section = (
                "**Plan feedback:**\n"
                "None! Your generated plan has passed the evaluation checks and is considered valid. However, the LLM and validator can still make mistakes, so please check your plan against the official UOW handbook. Best of luck with your studies!\n\n"
            )

        # Insert feedback immediately before the JSON code fence.
        fence_index = plan.lower().find("```json")

        if fence_index != -1:
            plan = (
                plan[:fence_index]
                + feedback_section
                + plan[fence_index:]
            )
        else:
            # If there is no JSON fence, put feedback at the start.
            plan = feedback_section + plan


        # print("\n\nFinal plan:\n", plan, "\n\n")

        return {
            "messages": [AIMessage(content=plan)],
            "planning_requested": False,
            "conversation_mode": "post_plan",
        }

