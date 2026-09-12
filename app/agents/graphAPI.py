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

from app.prompts.prompts import SYSTEM_PROMPT, ELECTIVE_GENERATION_PROMPT, SUBJECT_GENERATION_PROMPT, EVAL_SUBJECTS_ELECTIVES 

## graph state
class AdvisorState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    raw_sols: str
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

# input

# prompt chaining 

## check have all needed info - year, degree, major, enrolment, campus, elective preference
def apply_confirm_metadata(prior_meta: dict | None, new_meta: dict) -> dict:
    """Apply confirmed meta; clear handbook when degree/year/campus change.

    Mid-chat degree (or year/campus) switches must invalidate the cached
    handbook so the next turn re-fetches rules for the new program.
    Major may be stored on meta but does not by itself clear the handbook.
    """
    updates: dict = {"meta": new_meta, "meta_confirmed": True}
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
            models[kind] = base if kind == "parser" else base.bind_tools(skills[kind])
        return models[kind]

    async def parse_input(state: AdvisorState) -> dict:
        if state.get("meta") is not None:
            return {}
        meta = await parse_sols(llm("parser"), state["raw_sols"])
        data = meta.model_dump()
        # Never auto-confirm: the agent must ask the student (one question) and
        # call confirm_metadata_tool, even if the parser extracted candidate values.
        return {"meta": data, "meta_confirmed": False}

    async def agent(state: AdvisorState) -> dict:
        confirmed = state.get("meta_confirmed", False)
        agent_llm = llm("full") if confirmed else llm("confirm")

        system_content = build_system_prompt(
            prompt=SYSTEM_PROMPT,
            meta=state["meta"],
            meta_confirmed=confirmed,
            handbook=state.get("handbook"),
            raw_sols=state["raw_sols"],
        )
        response = await agent_llm.ainvoke(
            [SystemMessage(content=system_content), *state["messages"]]
        )
        return {"messages": [response]}

    def should_continue(state: AdvisorState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    def capture_tool_results(state: AdvisorState) -> dict:
        """Update AdvisorState with the latest tool results.

        Processes tools in chronological order so a confirm/switch that
        clears ``handbook`` can be followed by a fresh ``fetch_handbook_tool``
        in the same turn without the clear wiping the new cache.
        """
        batch: list[ToolMessage] = []
        for message in reversed(state["messages"]):
            if not isinstance(message, ToolMessage):
                break  # only the most recent batch of tool results
            batch.append(message)
        batch.reverse()
        return fold_tool_results(state, batch)

    ## parallelisation
    def route_after_agent(state: AdvisorState) -> str:
            last = state["messages"][-1]
            if isinstance(last, AIMessage) and last.tool_calls:
                return "tools"
            
            if state.get("meta_confirmed") and not (state.get("electives") and state.get("remaining_subjects")):
                return ["fetch_elective_list", "stage1_review_must_includes"]
            return END

    ### elective list
    async def fetch_elective_list(state: AdvisorState) -> dict:
            """Parallel Branch A: Determines available/preferred electives."""
            feedback = state.get("electives_feedback")
            prompt = build_system_prompt(
                prompt=ELECTIVE_GENERATION_PROMPT,
                meta=state["meta"],
                meta_confirmed=state.get("meta_confirmed", False),
                handbook=state.get("handbook"),
                raw_sols=state["raw_sols"],
            )
            if feedback:
                prompt += f"\nCORRECT THE FOLLOWING ISSUES FROM PREVIOUS PASS:\n{feedback}"

            res = await llm("full").ainvoke([
                SystemMessage(content="You are an academic data processing assistant."),
                HumanMessage(content=prompt)
            ])
            # Return updated list and clear error feedback
            return {"electives": str(res.content), "electives_feedback": None}


    ### stage 1 review && list of must include subjects
    async def stage1_review_must_includes(state: AdvisorState) -> dict:
        """Parallel Branch B: Extracts remaining mandatory degree subjects."""
        feedback = state.get("remaining_feedback")
        prompt = build_system_prompt(
            prompt=SUBJECT_GENERATION_PROMPT,
            meta=state["meta"],
            meta_confirmed=state.get("meta_confirmed", False),
            handbook=state.get("handbook"),
            raw_sols=state["raw_sols"],
        )
        if feedback:
            prompt += f"\nCORRECT THE FOLLOWING ISSUES FROM PREVIOUS PASS:\n{feedback}"

        res = await llm("full").ainvoke([
            SystemMessage(content="You are an academic course planning assistant."),
            HumanMessage(content=prompt)
        ])
        # Return updated list and clear error feedback
        return {"remaining_subjects": str(res.content), "remaining_feedback": None}


## eval both lists (musts + electives)
    async def eval_stage1_lists(state: AdvisorState) -> dict:
        """Evaluates both electives and core subjects against handbook accuracy."""
        eval_prompt = build_system_prompt(
            prompt=EVAL_SUBJECTS_ELECTIVES,
            meta=state["meta"],
            meta_confirmed=state.get("meta_confirmed", False),
            handbook=state.get("handbook"),
            raw_sols=state["raw_sols"],
        ).replace("{{electives}}", state.get('electives'))\
        .replace("{{remaining_subjects}}", state.get('remaining_subjects'))

        res = await llm("parser").ainvoke([
            SystemMessage(content="You are an academic auditor checking course list accuracy. Return ONLY JSON."),
            HumanMessage(content=eval_prompt)
        ])
        try:
            data = json.loads(res.content)
            return {
                "electives_feedback": None if data.get("electives_valid") else data.get("electives_feedback", "Invalid electives found."),
                "remaining_feedback": None if data.get("remaining_valid") else data.get("remaining_feedback", "Invalid core subjects found."),
            }
        except Exception:
            # Fallback if parsing fails
            return {
                "electives_feedback": "Failed to validate electives syntax against handbook.",
                "remaining_feedback": "Failed to validate core subjects syntax against handbook.",
            }

    def route_stage1_eval(state: AdvisorState) -> list[str] | str:
        """Routes back to invalid branches (in parallel if both fail) or advances to stage 2."""
        has_electives_error = bool(state.get("electives_feedback"))
        has_remaining_error = bool(state.get("remaining_feedback"))

        if not has_electives_error and not has_remaining_error:
            return "stage2_make_plan"

        rerun_branches = []
        if has_electives_error:
            rerun_branches.append("fetch_elective_list")
        if has_remaining_error:
            rerun_branches.append("stage1_review_must_includes")

        return rerun_branches

## evaluator optimiser pattern 
### stage 2 make the plan
    async def stage2_make_plan(state: AdvisorState) -> dict:
        """Generates or updates the degree completion plan based on feedback."""
        feedback = state.get("plan_feedback")
        system_msg = (
            "You are an academic course planning optimizer. Draft a session-by-session degree completion plan."
        )
        if feedback:
            system_msg += f"\n\nAddress this previous evaluation feedback:\n{feedback}"

        content_prompt = (
            f"Must-include core subjects: {state.get('remaining_subjects')}\n"
            f"Elective choices: {state.get('electives')}\n"
            f"Metadata: {state.get('meta')}"
        )

        res = await llm("full").ainvoke(
            [SystemMessage(content=system_msg), HumanMessage(content=content_prompt)]
        )
        return {"plan": str(res.content)}

### evaluator of stage 2 - correct session, name, cp total etc - feedback and back to stage 2 if needed
    async def evaluate_stage2(state: AdvisorState) -> dict:
        """Evaluates session correctness, credit point totals, and prerequisite order."""
        retries = state.get("retry_count") or 0
        if retries >= 3:
            # Stop looping after 3 attempts; accept the plan or fall back
            return {"plan_feedback": None, "retry_count": 0}
    
        eval_prompt = (
            "Evaluate this academic plan for correct session offerings, total credit points, and prerequisites.\n"
            "Respond ONLY in JSON format: {\"valid\": true/false, \"feedback\": \"reasoning if invalid\"}\n\n"
            f"Plan: {state.get('plan')}"
        )
        res = await llm("parser").ainvoke([
            SystemMessage(content="You are an academic auditor checking course list accuracy."),
            HumanMessage(content=eval_prompt)
        ])
        try:
            data = json.loads(res.content)
            if data.get("valid"):
                return {"plan_feedback": None, "retry_count": 0}
            return {
                "plan_feedback": data.get("feedback", "Invalid plan."),
                "retry_count": retries + 1
            }
        except Exception:
            return {"plan_feedback": "Failed to parse evaluation output."}

    def route_evaluation(state: AdvisorState) -> str:
        print(f"DEBUG: Stage 2 Eval Retry Count: {state.get('retry_count')}, Feedback: {state.get('plan_feedback')}")
        """Routes back to plan generator if invalid, or formats output if valid."""
        if state.get("plan_feedback") is None:
            return "format_output"
        return "stage2_make_plan"

# output
    async def format_output(state: AdvisorState) -> dict:
        """Appends the finalized plan to message state for output display."""
        final_msg = AIMessage(content=f"Here is your optimized academic completion plan:\n\n{state.get('plan')}")
        return {"messages": [final_msg]}



    # build workflow
    graph = StateGraph(AdvisorState)

    # add nodes
    graph.add_node("parse_input", parse_input)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(skills["full"]))
    graph.add_node("capture_tool_results", capture_tool_results)

    # stage 1 Parallel
    graph.add_node("fetch_elective_list", fetch_elective_list)
    graph.add_node("stage1_review_must_includes", stage1_review_must_includes)
    graph.add_node("eval_stage1_lists", eval_stage1_lists)

    # stage 2 Evaluator-Optimizer Nodes
    graph.add_node("stage2_make_plan", stage2_make_plan)
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
            "fetch_elective_list": "fetch_elective_list",
            "stage1_review_must_includes": "stage1_review_must_includes",
            END: END,
        },
    )

    graph.add_edge("tools", "capture_tool_results")
    graph.add_edge("capture_tool_results", "agent")

    graph.add_edge("fetch_elective_list", "eval_stage1_lists")
    graph.add_edge("stage1_review_must_includes", "eval_stage1_lists")

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
    graph.add_edge("stage2_make_plan", "evaluate_stage2")
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

