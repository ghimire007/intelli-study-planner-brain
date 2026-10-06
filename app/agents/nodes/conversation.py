"""Intake and chat nodes: parse the SOLS paste, talk to the student, fold metadata tools."""
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
from app.prompts.builder import build_system_prompt
from app.prompts.prompts import SYSTEM_PROMPT
from app.services.sols_parser import parse_sols


class ConversationNodes:
    """Intake and chat: parse the SOLS paste, talk to the student, and fold the
    metadata tools the agent calls back into state."""

    def __init__(self, llms: LLMRegistry, confirm_tools: list) -> None:
        self._llms = llms
        self._tool_node = ToolNode(confirm_tools)

    async def parse_input(self, state: AdvisorState) -> dict:
        print("NODE: parse_input")

        if state.get("meta") is not None:
            return {}

        raw_sols = state.get("raw_sols")
        print("raw_sols chars =", len(raw_sols or ""))

        start = time.perf_counter()
        try:
            meta = await parse_sols(self._llms.get("parser"), raw_sols)
        except Exception as exc:
            print(type(exc).__name__, repr(exc))
            raise
        print(f"parse_sols took {time.perf_counter() - start:.2f}s")

        return {
            "meta": meta.model_dump(),
            "meta_confirmed": False,
            "planning_requested": False,
        }

    async def agent(self, state: AdvisorState) -> dict:
        """Conversational LLM: confirmation-oriented model before metadata is
        confirmed, full planning/conversation model afterwards."""
        print("NODE: agent")

        confirmed = bool(state.get("meta_confirmed"))
        kind = "full" if confirmed else "confirm"
        print("agent: invoking", kind)

        conversation_mode = state.get("conversation_mode") or "collecting"

        system_content = build_system_prompt(
            prompt=SYSTEM_PROMPT,
            meta=state.get("meta"),
            meta_confirmed=confirmed,
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )
        system_content += f"""
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
            """

        response = await self._llms.get(kind).ainvoke(
            [SystemMessage(content=system_content), *state.get("messages", [])]
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
            if message.name not in {"confirm_metadata_tool", "request_plan_change_tool"}:
                continue

            try:
                parsed = extract_and_parse_json(message.content)
                if not isinstance(parsed, dict):
                    raise ValueError(f"{message.name} did not return an object.")

                prior_meta = updates.get("meta", state.get("meta"))

                if message.name == "confirm_metadata_tool":
                    sanitized = sanitize_confirmed_metadata(
                        prior_meta=prior_meta,
                        candidate_meta=parsed,
                        state=state,
                    )
                    updates.update(apply_confirm_metadata(prior_meta, sanitized))
                    print("CONFIRMED METADATA RAW:", parsed)
                    print("CONFIRMED METADATA SANITIZED:", sanitized)
                else:
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
