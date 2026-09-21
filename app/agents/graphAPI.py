import json
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.skills import build_skills
from app.llm.config import LLMConfig
from app.llm.factory import make_chat_model
from app.prompts.builder import build_system_prompt
from app.services.sols_parser import parse_sols

from app.schemas.elective_ranking import ElectivePriorityInput
from app.services.elective_ranking import get_elective_priorities

from app.prompts.prompts import SYSTEM_PROMPT, ELECTIVE_GENERATION_PROMPT, SUBJECT_GENERATION_PROMPT, EVAL_SUBJECTS_ELECTIVES, MAKE_PLAN, EVAL_PLAN, SYSTEM_PROMPT_V1

import re

def extract_and_parse_json(raw_input):
    """
    Extracts raw JSON structure from stringified, double-escaped, 
    or Markdown-fenced LLM/tool outputs.
    """
    if isinstance(raw_input, list) and raw_input:
        # Handle LangChain / Tool result text wrappers
        first = raw_input[0]

        if isinstance(first, dict) and "text" in first:
            raw_input = first["text"]

    if not isinstance(raw_input, str):
        return raw_input

    # Strip Markdown code fences (e.g., ```json ... ```)
    cleaned = re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', raw_input).strip()
    
    # Unescape non-breaking spaces and double-escaped characters
    cleaned = cleaned.replace('\xa0', ' ').replace('\\n', '\n')

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        return cleaned
        # raise ValueError(f"Failed to parse clean JSON from model output: {e}\nRaw: {cleaned}")


## graph state
class AdvisorState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    raw_sols: str | None
    # plain dict (SOLSMeta.model_dump()), not the pydantic model itself — the
    # checkpointer's msgpack serializer only supports plain JSON-ish types and
    # warns (soon: errors) on arbitrary custom classes.
    meta: dict | None
    meta_confirmed: bool
    handbook: str | None
    electives: str | None
    remaining_subjects: str | None

    #feedback for checks and re-runs
    electives_feedback: str | None
    remaining_feedback: str | None
    plan: str | None
    plan_feedback: str | None

    retry_count: int | None
    stage1_retry_count: int | None
    planning_requested: bool | None

    current_stage: int | None

# input

# prompt chaining 

## check have all needed info - year, degree, major, enrolment, campus, elective preference
def apply_confirm_metadata(prior_meta: dict | None, new_meta: dict) -> dict:
    """Apply confirmed meta; clear handbook when degree/year/campus change.

    Mid-chat degree (or year/campus) switches must invalidate the cached
    handbook so the next turn re-fetches rules for the new program.
    Major may be stored on meta but does not by itself clear the handbook.
    """
    updates: dict = {
        "meta": new_meta, 
        "meta_confirmed": True, 
        "planning_requested": True,
        # Clear previous generation state for a fresh run
        "electives": None,
        "remaining_subjects": None,
        "plan": None,
        "plan_feedback": None,
        "electives_feedback": None,
        "remaining_feedback": None,
        "retry_count": 0,
        "stage1_retry_count": 0,
        "current_stage": None,
    }

    old = prior_meta or {}
    if (
        old.get("degree_code") != new_meta.get("degree_code")
        or old.get("year") != new_meta.get("year")
        or old.get("campus") != new_meta.get("campus")
    ):
        updates["handbook"] = None
    return updates


def fold_tool_results(state: AdvisorState, batch: list[ToolMessage]) -> dict:
    """Fold a chronological tool-result batch into AdvisorState updates.

    Confirm/switch runs before fetch in the same turn so a cleared handbook
    can be replaced by a freshly fetched one without being wiped again.
    """
    updates: dict = {}
    for message in batch:
        if message.name == "confirm_metadata_tool":
            prior = updates.get("meta", state.get("meta"))
            updates.update(apply_confirm_metadata(prior, json.loads(message.content)))
        elif message.name == "fetch_handbook_tool":
            updates["handbook"] = message.content
    return updates

# build graph
def build_advisor_graph(
    db: AsyncSession,
    checkpointer: BaseCheckpointSaver,
    llm_config: LLMConfig | None = None,
):
    """Compile the advisor StateGraph, bound to a DB session for its skills.

    `checkpointer` persists AdvisorState per thread_id, so callers only ever
    need to supply the *new* message(s) for a turn — not the full history.

    `llm_config` carries the student's own decrypted API key. It is held in this
    closure for the life of the request and deliberately never written into
    AdvisorState: the checkpointer msgpacks state into Postgres after every step,
    so a key placed there would be persisted in the clear. Pass None for
    read-only work (history, state inspection) — no model is then constructed.
    """
    skills = build_skills(db)
    models: dict[str, BaseChatModel] = {}

    def llm(kind: str) -> BaseChatModel:
        """Build a chat model on first use, so a read-only graph needs no key."""
        if kind not in models:
            if llm_config is None:
                raise RuntimeError(
                    "This graph was built without an LLM config — it can read "
                    "checkpointed state but cannot call a model"
                )
            base = make_chat_model(llm_config)

            model_to_retry = base if kind == "parser" else base.bind_tools(skills[kind])

            models[kind] = model_to_retry.with_retry(
                wait_exponential_jitter=True, # Calculates exponential delays with jitter
                stop_after_attempt=1,         # Retry up to 1 times per LLM call
            )

        return models[kind]

    async def parse_input(state: AdvisorState) -> dict:
        if state.get("meta") is not None:
            return {}

        raw_sols = state.get("raw_sols")
    
        if not raw_sols or raw_sols == "no enrolment yet":
            print("parse_input - No enrolment record provided, skipping parser.")
            return {"meta": None, "meta_confirmed": False, "planning_requested": False}

        meta = await parse_sols(llm("parser"), state["raw_sols"])
        data = meta.model_dump()
        # Never auto-confirm: the agent must ask the student (one question) and
        # call confirm_metadata_tool, even if the parser extracted candidate values.
        print("parse_input - meta:", meta)
        return {"meta": data, "meta_confirmed": False, "planning_requested": True}

    async def agent(state: AdvisorState) -> dict:
        confirmed = state.get("meta_confirmed", False)
        agent_llm = llm("full") if confirmed else llm("confirm")

        system_content = build_system_prompt(
            prompt=SYSTEM_PROMPT,
            meta=state.get("meta"),
            meta_confirmed=confirmed,
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )

        messages = [SystemMessage(content=system_content)] + state.get("messages", [])
        response = await agent_llm.ainvoke(messages)
        
        return {"messages": [response], "current_stage": None}
    

    def capture_tool_results(state: AdvisorState) -> dict:
        """Update AdvisorState with the latest tool results.

        Processes tools in chronological order so a confirm/switch that
        clears ``handbook`` can be followed by a fresh ``fetch_handbook_tool``
        in the same turn without the clear wiping the new cache.
        """
        batch: list[ToolMessage] = []
        for message in reversed(state.get("messages")):
            if not isinstance(message, ToolMessage):
                break  # only the most recent batch of tool results
            batch.append(message)
        batch.reverse()
        return fold_tool_results(state, batch)

    ## parallelisation
    def route_after_agent(state: AdvisorState) -> str:
        messages = state.get("messages", [])
        last = messages[-1] if messages else None

        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"

        # Trigger planning flow if metadata is confirmed and planning is requested
        if state.get("meta_confirmed") and state.get("planning_requested"):
            return "start_planning"

        return END

    async def start_planning(state: AdvisorState) -> dict:
        """Consume the planning_requested flag so agent doesn't re-trigger Stage 1."""
        return {"planning_requested": False, "current_stage": 1}

    ### elective list
    async def fetch_elective_list(state: AdvisorState) -> dict:
        prompt = build_system_prompt(
            prompt=ELECTIVE_GENERATION_PROMPT,
            meta=state.get("meta"),
            meta_confirmed=state.get("meta_confirmed", False),
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )
        if state.get("electives_feedback"):
            prompt += f"\nCORRECT THE FOLLOWING ISSUES FROM PREVIOUS PASS:\n{state.get('electives_feedback')}"

        system_msg = SystemMessage(content="You are an academic data processing assistant. Use tools if necessary to find electives.")
        
        # Send system message + prompt + any prior conversation/tool history
        messages = (
            [system_msg] 
            + state.get("messages", []) 
            + [HumanMessage(content=prompt)]
        )

        res = await llm("full").ainvoke(messages)

        # If the model requests a tool call, yield the AIMessage so the graph routes to `tools`
        if res.tool_calls:
            return {"messages": [res]}

        parsed = extract_and_parse_json(res.content)
        str_content = json.dumps(parsed) if isinstance(parsed, (dict, list)) else str(parsed)
        return {"electives": str_content, "electives_feedback": ""}
            
    def route_stage1_tools(state: AdvisorState) -> str:
        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            return "stage1_tools"
        return "join_stage1"

    ### stage 1 review && list of must include subjects
    async def stage1_review_must_includes(state: AdvisorState) -> dict:
        """Parallel Branch B: Extracts remaining mandatory degree subjects."""
        feedback = state.get("remaining_feedback")
        prompt = build_system_prompt(
            prompt=SUBJECT_GENERATION_PROMPT,
            meta=state.get("meta"),
            meta_confirmed=state.get("meta_confirmed", False),
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )
        if feedback:
            prompt += f"\nCORRECT THE FOLLOWING ISSUES FROM PREVIOUS PASS:\n{feedback}"

        res = await llm("full").ainvoke([
            SystemMessage(content="You are an academic course planning assistant."),
            HumanMessage(content=prompt)
        ])

        print("stage1_review_must_includes: ", str(extract_and_parse_json(res.content)))
        parsed = extract_and_parse_json(res.content)
        str_content = json.dumps(parsed) if isinstance(parsed, (dict, list)) else str(parsed)
        return {"remaining_subjects": str_content, "remaining_feedback": ""}

    def join_stage1(state: AdvisorState) -> dict:
        return {"current_stage": 1}

## eval both lists (musts + electives)
    async def eval_stage1_lists(state: AdvisorState) -> dict:
        """Evaluates both electives and core subjects against handbook accuracy."""
        print(
            "EVAL INPUT:",
            state.get("electives"),
            state.get("remaining_subjects"),
            state.get("stage1_retry_count")
        )

        eval_prompt = build_system_prompt(
            prompt=EVAL_SUBJECTS_ELECTIVES,
            meta=state.get("meta"),
            meta_confirmed=state.get("meta_confirmed", False),
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        ).replace("{{electives}}", state.get('electives') or "")\
        .replace("{{remaining_subjects}}", state.get('remaining_subjects') or "")

        res = await llm("parser").ainvoke([
            SystemMessage(content="You are an academic auditor checking course list accuracy. Return ONLY JSON."),
            HumanMessage(content=eval_prompt)
        ])

        current_retry = state.get("stage1_retry_count") or 0

        try:
            data = extract_and_parse_json(res.content)

            electives_valid = data.get("electives_valid", False) if isinstance(data, dict) else False
            remaining_valid = data.get("remaining_valid", False) if isinstance(data, dict) else False

            return {
                "electives_feedback": "" if electives_valid else data.get("electives_feedback", "Invalid electives."),
                "remaining_feedback": "" if remaining_valid else data.get("remaining_feedback", "Invalid core subjects."),
                "stage1_retry_count": current_retry + 1
            }
        except Exception as e:
            # print("EVAL EXCEPTION:", type(e).__name__)
            # print("ERROR:", str(e))
            # print("CONTENT:", repr(res.content))
            
            # Fallback if parsing fails
            print("eval_stage1_lists - exception:", e)
            return {
                "electives_feedback": "Failed to parse validation output.",
                "remaining_feedback": "Failed to parse validation output.",
                "stage1_retry_count": current_retry + 1
            }

    

    def route_stage1_eval(state: AdvisorState) -> list[str] | str:
        """Routes back to invalid branches in parallel or advances to stage 2."""
        retries = state.get("stage1_retry_count") or 0
        has_electives_error = bool(state.get("electives_feedback"))
        has_remaining_error = bool(state.get("remaining_feedback"))

        # Proceed if valid or max retries reached
        print('route stage 1')
        if (not has_electives_error and not has_remaining_error) or retries >= 2:
            print("Stage 1 retry limit reached or valid. Advancing to Stage 2 with fallback.")
            return "stage2_make_plan"

        # Dynamic parallel fan-out based on failures
        routes = []
        if has_electives_error:
            routes.append("fetch_elective_list")
        if has_remaining_error:
            routes.append("stage1_review_must_includes")

        return routes if routes else "stage2_make_plan"
    
## evaluator optimiser pattern 
### stage 2 make the plan
    async def stage2_make_plan(state: AdvisorState) -> dict:
        """Generates or updates the degree completion plan based on feedback."""
        feedback = state.get("plan_feedback")
        # messages = state.get("messages", [])

        base_system_prompt = build_system_prompt(
            prompt=SYSTEM_PROMPT_V1,
            meta=state.get("meta"),
            meta_confirmed=state.get("meta_confirmed", False),
            handbook=state.get("handbook"),
            raw_sols=state.get("raw_sols"),
        )

        if feedback:
            base_system_prompt += f"\n\nAddress this previous evaluation feedback:\n{feedback}"

        content_prompt = (
            f"Must-include core subjects: {state.get('remaining_subjects')}\n"
            f"Elective choices: {state.get('electives')}\n"
            f"Metadata: {state.get('meta')}"
        )

        invoke_messages = (
            [SystemMessage(content=base_system_prompt)] 
            + state.get("messages", []) 
            + [HumanMessage(content=content_prompt)]
        )
        # invoke_messages = [
        #     SystemMessage(content=base_system_prompt),
        #     HumanMessage(content=content_prompt),
        # ]
        res = await llm("full").ainvoke(invoke_messages)
    
        # Always append the AI response to message history
        updated_state = {
            "messages": [res],  # Reducer will append this cleanly
            "current_stage": 2
        }

        print("STAGE2 RETRY:", state.get("retry_count"))
        print("PLAN FEEDBACK:", state.get("plan_feedback"))
        
        # ONLY extract and populate plan if the model outputted content (no tool calls)
        if res.content and not res.tool_calls:
            print("PLAN: ", res.content)
            if isinstance(res.content, list):
                updated_state["plan"] = res.content[0].get("text", "")
            else:
                updated_state["plan"] = res.content
            # updated_state["plan"] = res.content
            
        return updated_state


    def route_stage2_tools(state: AdvisorState) -> str:
        """Routes stage2_make_plan to 'tools' if tool calls exist, else to 'evaluate_stage2'."""
        messages = state.get("messages", [])
        if not messages:
            return "evaluate_stage2"
        
        last_message = messages[-1]
        # Check if the AI message contains tool calls
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "stage2_tools"
        
        return "evaluate_stage2"

### evaluator of stage 2 - correct session, name, cp total etc - feedback and back to stage 2 if needed
    async def evaluate_stage2(state: AdvisorState) -> dict:
        # evaluate_stage2
        # print(
        #     "EVAL",
        #     "retry=", retries,
        #     "feedback=", data.get("feedback"),
        #     "valid=", data.get("valid")
        # )

        # # route_evaluation
        # print(
        #     "ROUTE",
        #     "retry=", state.get("retry_count"),
        #     "feedback=", state.get("plan_feedback")
        # )

        # # stage2_make_plan
        # print(
        #     "MAKE_PLAN",
        #     "retry=", state.get("retry_count"),
        #     "feedback=", state.get("plan_feedback")
        # )

        # # route_after_tool_capture
        # print(
        #     "TOOL_CAPTURE",
        #     "stage=", state.get("current_stage"),
        #     "retry=", state.get("retry_count")
        # )

        """Evaluates session correctness, credit point totals, and prerequisite order."""
        retries = state.get("retry_count") or 0
            
        eval_prompt = EVAL_PLAN.replace("{{PLAN}}", state.get('plan') or "")
        res = await llm("parser").ainvoke([
            SystemMessage(content="You are an auditor checking a generated study plans subject accuracy and ensuring correct placement. You also confirm that a response has all required elements (Audit & Rule Verification section, Study plan table, CP summary and a raw, valid JSON block)."),
            HumanMessage(content=eval_prompt)
        ])
        try:
            content = res.content[0]["text"] if isinstance(res.content, list) else res.content
            data = extract_and_parse_json(content.strip())

            # data = content.strip()
            # data = extract_and_parse_json(data)
            print("EVALUATE!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n", data)

            if data.get("valid"):
                print("evaluate_stage2 - valid")
                return {"plan_feedback": None, "planning_requested": False, "retry_count": 0}
            
            print("evaluate_stage2 - not valid")
            return {
                "plan_feedback": data.get("feedback", "Invalid plan."),
                "retry_count": retries + 1
            }
        except Exception as e:
            print("evaluate_stage2 - exception:", e)

            return {"plan_feedback": "Failed to parse evaluation output.", 
                    "retry_count": retries + 1}

    def route_evaluation(state: AdvisorState) -> str:
        print(f"DEBUG: Stage 2 Eval Retry Count: {state.get('retry_count')}, Feedback: {state.get('plan_feedback')}")
        """Routes back to plan generator if invalid, or formats output if valid."""
    
        retries = state.get("retry_count") or 0
        feedback = state.get("plan_feedback")

        # print(
        #     f"DEBUG: retries={retries}, "
        #     f"feedback={feedback}"
        # )

        # success or retry limit reached
        if not feedback or retries > 1:
            print('give the output')
            return "format_output"

        return "stage2_make_plan"

# output
    async def format_output(state: AdvisorState) -> dict:
        """Appends the finalized plan to message state for output display."""
        # print("DEBUG format_output - state keys present:", state.keys())
        # print("DEBUG format_output - raw plan value:", repr(state.get("plan")))
        
        plan_content = state.get("plan")
        if not plan_content:
            plan_content = "Unable to complete plan generation. Please review degree metadata."

        # print("hi")
        # plan_clean = (state.get("plan"))
        # print("CLEAN PLAN:", plan_clean)
        final_msg = AIMessage(content=f"{plan_content}")
        return {
            "messages": [final_msg], 
            "planning_requested": False,
            "current_stage": None
        }

    # def route_after_tool_capture(state: AdvisorState) -> str:
    #     # If currently in stage 2 execution, loop back to stage 2
    #     stage = state.get("current_stage")
    #     if stage == 2:
    #         return "stage2_make_plan"
    #     return "agent"


    # build workflow
    graph = StateGraph(AdvisorState)

    # add nodes
    graph.add_node("parse_input", parse_input)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(skills["full"]))
    graph.add_node("capture_tool_results", capture_tool_results)

    graph.add_node("start_planning", start_planning)
    graph.add_node("stage1_tools", ToolNode(skills["electives"]))
    graph.add_node("capture_stage1_tool_results", capture_tool_results)

    # stage 1 Parallel
    graph.add_node("fetch_elective_list", fetch_elective_list)
    graph.add_node("stage1_review_must_includes", stage1_review_must_includes)
    graph.add_node("join_stage1", join_stage1)
    graph.add_node("eval_stage1_lists", eval_stage1_lists)

    # stage 2 Evaluator-Optimizer Nodes
    graph.add_node("stage2_make_plan", stage2_make_plan)
    graph.add_node("stage2_tools", ToolNode(skills["full"]))
    graph.add_node("capture_stage2_tool_results", capture_tool_results)
    graph.add_node("evaluate_stage2", evaluate_stage2)
    graph.add_node("format_output", format_output)

    # edges & Conditional Connections
    graph.set_entry_point("parse_input")
    graph.add_edge("parse_input", "agent")

    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "tools": "tools",
            "start_planning": "start_planning",
            END: END,
        },
    )

    graph.add_edge("tools", "capture_tool_results")
    graph.add_edge("capture_tool_results", "agent")

    # Parallel Fan-Out from start_planning
    graph.add_edge("start_planning", "fetch_elective_list")
    graph.add_edge("start_planning", "stage1_review_must_includes")

    # Stage 1 Parallel Fan-In Barrier
    graph.add_conditional_edges(
        "fetch_elective_list",
        route_stage1_tools,
        {
            "stage1_tools": "stage1_tools",
            "join_stage1": "join_stage1"
        }
    )
    # graph.add_edge("fetch_elective_list", "join_stage1")
    graph.add_edge("stage1_tools", "capture_stage1_tool_results")
    graph.add_edge("capture_stage1_tool_results", "fetch_elective_list")
    # graph.add_edge("fetch_elective_list", "join_stage1")
    graph.add_edge("stage1_review_must_includes", "join_stage1")
    graph.add_edge("join_stage1", "eval_stage1_lists")

    # Gate Evaluation from Stage 1 into Stage 2
    graph.add_conditional_edges(
        "eval_stage1_lists",
        route_stage1_eval,
        {
            "fetch_elective_list": "fetch_elective_list",
            "stage1_review_must_includes": "stage1_review_must_includes",
            "stage2_make_plan": "stage2_make_plan",
        },
    )

    # Evaluator-Optimizer Loop
    graph.add_conditional_edges(
        "stage2_make_plan",
        route_stage2_tools,
        {
            "stage2_tools": "stage2_tools",                  # Executing tools requested in Stage 2
            "evaluate_stage2": "evaluate_stage2" # Proceeding to eval when finished
        },
    )
    graph.add_edge("stage2_tools", "capture_stage2_tool_results")
    graph.add_edge("capture_stage2_tool_results", "stage2_make_plan")

    graph.add_conditional_edges(
        "evaluate_stage2",
        route_evaluation,
        {
            "stage2_make_plan": "stage2_make_plan",
            "format_output": "format_output",
        },
    )

    graph.add_edge("format_output", END)

    return graph.compile(checkpointer=checkpointer)

