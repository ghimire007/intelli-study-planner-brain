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
    _message_text,
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


class ConversationNodes:
    """Intake and chat: parse the SOLS paste, talk to the student, and fold the
    metadata tools the agent calls back into state."""

    @staticmethod
    def route_after_tool_results(
        state: AdvisorState,
    ) -> Literal["agent", "ensure_handbook", "__end__"]:
        """Route confirmed metadata into the application workflow.

        Do not invoke the LLM again just to decide what to do after
        metadata has been confirmed.
        """
        batch = latest_tool_batch(state)

        called_metadata_confirmation = any(
            message.name == "confirm_metadata_tool"
            for message in batch
        )

        if (
            called_metadata_confirmation
            and state.get("meta_confirmed")
            and (
                state.get("planning_requested")
                or state.get("pending_elective_action") is not None
            )
            and not handbook_matches_current_meta(state)
        ):
            print("ROUTE: metadata confirmed; fetching handbook directly")
            return "ensure_handbook"

        # Other tool results, such as answers to subject questions,
        # should return to the agent so it can respond to the student.
        return "agent"

    @staticmethod
    def user_requested_electives(state: AdvisorState) -> bool:
        """Detect explicit requests for elective recommendations or selection."""
        message = latest_student_message(state).strip().lower()

        patterns = (
            r"\belectives?\b",
            r"\belective subjects?\b",
            r"\brecommend .{0,40}subjects?\b",
            r"\bsuggest .{0,40}subjects?\b",
        )

        return any(re.search(pattern, message) for pattern in patterns)

    @staticmethod
    def requested_elective_action(
        state: AdvisorState,
    ) -> Literal["recommend", "populate_plan"] | None:
        if not ConversationNodes.user_requested_electives(state):
            return None

        if state.get("plan"):
            return "populate_plan"

        return "recommend"

    def __init__(self, llms: LLMRegistry, tools_by_kind: dict) -> None:
        self._llms = llms
        self._tool_nodes = {
            kind: ToolNode(tools)
            for kind, tools in tools_by_kind.items()
        }

    # async def parse_input(self, state: AdvisorState) -> dict:
    #     print("NODE: parse_input")

    #     if state.get("meta") is not None:
    #         return {}

    #     raw_sols = state.get("raw_sols")
    #     print("raw_sols chars =", len(raw_sols or ""))

    #     start = time.perf_counter()
    #     try:
    #         meta = await parse_sols_metadata(self._llms.get("parser"), raw_sols)
    #     except Exception as exc:
    #         print(type(exc).__name__, repr(exc))
    #         raise
    #     print(f"parse_sols_metadata took {time.perf_counter() - start:.2f}s")

    #     return {
    #         "meta": meta.model_dump(),
    #         "meta_confirmed": False,
    #         "planning_requested": False,
    #     }

    async def agent(self, state: AdvisorState) -> dict:
        """Conversational LLM: confirmation-oriented model before metadata is
        confirmed, full planning/conversation model afterwards."""
        print("NODE: agent")
        # print("current plan: ", state.get("plan"))

        pending_action = state.get("pending_elective_action")

        if pending_action is None:
            pending_action = self.requested_elective_action(state)

        confirmed = bool(state.get("meta_confirmed"))
        conversation_mode = state.get("conversation_mode") or "collecting"

        if not confirmed:
            kind = "confirm"
        elif (
            conversation_mode == "post_plan"
            and is_plan_explanation_question(latest_student_message(state))
        ):
            kind = "qa"
        else:
            kind = "full"
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
            ELECTIVE REQUEST RULES:
            - A request to recommend electives is not a plan-change request.
            - Do not call request_plan_change_tool merely because the student asks for elective recommendations.
            - Use the dedicated elective workflow for elective recommendations.
            - Only call request_plan_change_tool to change saved preferences when the student explicitly asks to change those preferences.
            - If changing elective interests, elective_interests must be a list of strings. Never submit null for this field.
            - Handbook fetching is handled by ensure_handbook.
            - Elective retrieval is handled by fetch_elective_list.
            - If pending_elective_action is set and metadata is confirmed, do not make additional tool calls. Let the application workflow handle the request.

            PLAN CHANGE RULES:

            You must distinguish between:
            1. questions about the existing plan
            2. requests to modify the plan

            Call request_plan_change_tool only when the student explicitly requests a change to their study plan, such as changing their major, changing elective preferences, moving subjects between sessions, or revising the plan.

            Do NOT call request_plan_change_tool for informational questions about the student's existing enrolment history or current plan.
            Answer informational questions using the available enrolment history and plan state.

            A question about the plan is not a request to change the plan. Do not interpret general_revision as permission to regenerate the plan unless the student explicitly requests a revision.

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

        # Older checkpoints can contain evaluator JSON. Keep it out of the
        # conversational prompt while retaining every tool call and its result.
        messages = [
            message for message in state.get("messages", [])
            if not (
                isinstance(message, AIMessage)
                and not message.tool_calls
                and is_evaluation_reply(message.content)
            )
        ]
        prompt = [SystemMessage(content=system_content), *messages]
        model = self._llms.get(kind)
        response = await model.ainvoke(prompt)
        print("AGENT RESPONSE TYPE:", type(response).__name__)
        print("AGENT TOOL CALLS:", getattr(response, "tool_calls", []))
        print("AGENT RESPONSE TEXT:", _message_text(response)[:500])

        if not response.tool_calls and is_evaluation_reply(response.content):
            # Retry only accidental verdicts; normal chat and tool routing stay intact.
            response = await model.ainvoke([
                *prompt,
                SystemMessage(content=(
                    "Answer the student's latest message conversationally. "
                    "Do not return an internal evaluator verdict with valid/feedback fields. "
                    "Use the available tools if needed."
                )),
            ])
            if not response.tool_calls and is_evaluation_reply(response.content):
                response.content = "I couldn't produce a chat reply. Please try your message again."

        updates = {
            "messages": [response],
            "active_tool_kind": kind,
        }

        if pending_action is not None:
            updates["pending_elective_action"] = pending_action

        return updates



    async def run_tools(self, state: AdvisorState) -> dict:
        print("NODE: tools")

        kind = state.get("active_tool_kind", "confirm")
        tool_node = self._tool_nodes[kind]

        return await tool_node.ainvoke(state)

    def capture_tool_results(self, state: AdvisorState) -> dict:
        """Fold conversational tool results into state."""
        print("NODE: capture_tool_results")

        batch = latest_tool_batch(state)
        updates: dict = {}

        lookup_results = list(state.get("elective_lookup_results") or [])
        lookup_codes = {
            str(code).strip().upper()
            for code in (state.get("elective_lookup_codes") or [])
        }

        print("TOOL RESULT:", batch)

        for message in batch:
            try:
                parsed = extract_and_parse_json(message.content)

                if message.name == "lookup_electives_tool":
                    # Support both the current {"query": ..., "subjects": [...]} format
                    # and the older list format.
                    if isinstance(parsed, dict):
                        subjects = parsed.get("subjects", [])
                    elif isinstance(parsed, list):
                        subjects = parsed
                    else:
                        print(
                            "LOOKUP RESULT IGNORED: expected JSON object or list; "
                            f"got {type(parsed).__name__}"
                        )
                        continue

                    if not isinstance(subjects, list):
                        print("LOOKUP RESULT IGNORED: 'subjects' is not a list")
                        continue

                    captured_this_call = []

                    for item in subjects:
                        if not isinstance(item, dict):
                            continue

                        # Current lookup results wrap the detailed subject in "subject".
                        # Also support results where the subject fields are at the top level.
                        subject = item.get("subject")
                        if not isinstance(subject, dict):
                            subject = item

                        code = str(
                            subject.get("code") or item.get("code") or ""
                        ).strip().upper()

                        if not code or code in lookup_codes:
                            continue

                        # Copy the detailed subject without modifying the tool result.
                        normalized_subject = {
                            **subject,
                            "code": code,
                        }

                        # Keep the relevance score if the outer result provides one.
                        if "score" in item:
                            normalized_subject.setdefault("score", item["score"])

                        lookup_codes.add(code)
                        lookup_results.append(normalized_subject)
                        captured_this_call.append(code)

                    print(
                        "CAPTURED ELECTIVE LOOKUPS:",
                        sorted(lookup_codes),
                    )
                    print(
                        "CAPTURED IN THIS CALL:",
                        captured_this_call,
                    )
                    continue

                if message.name not in {
                    "confirm_metadata_tool",
                    "request_plan_change_tool",
                }:
                    continue

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
                        apply_confirm_metadata(prior_meta, sanitized)
                    )
                    print("CONFIRMED METADATA RAW:", parsed)
                    print("CONFIRMED METADATA SANITIZED:", sanitized)

                else:
                    updates.update(
                        apply_plan_change_request(prior_meta, parsed)
                    )
                    print("PLAN CHANGE TOOL RESULT:", parsed)

            except Exception as exc:
                print(
                    f"Conversational tool parse error ({message.name}):",
                    repr(exc),
                )

        # Only update these keys if the batch included a lookup result.
        if any(m.name == "lookup_electives_tool" for m in batch):
            updates["elective_lookup_results"] = lookup_results
            updates["elective_lookup_codes"] = sorted(lookup_codes)

        return updates

    @staticmethod
    def route_after_agent(
        state: AdvisorState,
    ) -> Literal["tools", "ensure_handbook", "fetch_elective_list", "populate_plan_electives", "start_planning", "__end__"]:
        """The LLM may request conversational tools; it does not control the
        handbook gate."""
        messages = state.get("messages", [])
        last = messages[-1] if messages else None

        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"

        if not state.get("meta_confirmed"):
            return END

        pending = state.get("pending_elective_action")

        if pending is not None:
            if not handbook_matches_current_meta(state):
                print("ROUTE: handbook required for elective request")
                return "ensure_handbook"

            if pending == "populate_plan":
                return "populate_plan_electives"

            if pending == "recommend":
                return "fetch_elective_list"


        if not state.get("planning_requested"):
            return END

        if not handbook_matches_current_meta(state):
            print("ROUTE: handbook missing/stale")
            return "ensure_handbook"

        return "start_planning"
