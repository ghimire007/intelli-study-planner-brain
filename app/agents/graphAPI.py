"""
Advisor LangGraph: wires the node groups in app/agents/nodes/ into a StateGraph.

ConversationNodes:
START -> agent
agent -> tools -> capture_tool_results -> agent | ensure_handbook | END
agent -> ensure_handbook | fetch_elective_list | populate_plan_electives | start_planning | END

HandbookNodes:
ensure_handbook -> start_planning | fetch_elective_list | populate_plan_electives | handbook_missing
handbook_missing -> END

Stage1Nodes:
start_planning -> stage1_review_must_includes -> eval_stage1_lists
eval_stage1_lists -> stage1_review_must_includes (retry) | stage2_make_plan
fetch_elective_list -> END
populate_plan_electives -> END

Stage2Nodes:
stage2_make_plan -> stage2_tools | evaluate_stage2
stage2_tools -> capture_stage2_tool_results -> stage2_make_plan
evaluate_stage2 -> stage2_make_plan (retry) | format_output
format_output -> END

Elective retrieval and plan updates are request-driven paths that terminate after returning their results. They do not automatically continue into Stage 2. 
Initial plan generation follows the separate Stage 1 core-subject generation and evaluation path.

State and shared helpers live in app/agents/state.py.
"""
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llms import LLMRegistry
from app.agents.nodes import ConversationNodes, HandbookNodes, Stage1Nodes, Stage2Nodes
from app.agents.skills import build_skills
from app.agents.state import AdvisorState
from app.llm.config import LLMConfig


class AdvisorGraph:
    """Assemble the advisor StateGraph from its node groups.

    Node groups are public attributes so tests can swap one for a stand-in
    before calling build(); the wiring is the only thing build() adds.
    """

    def __init__(
        self,
        db: AsyncSession,
        checkpointer: BaseCheckpointSaver | None,
        llm_config: LLMConfig | None = None,
    ) -> None:
        skills = build_skills(db)

        conversation_tools = {
            "confirm": skills["confirm"],
            "full": [
                tool
                for tool in skills["full"]
                if tool.name in {
                    "lookup_subjects_tool",
                    "lookup_electives_tool",
                    "lookup_uow_policy_tool",
                    "request_plan_change_tool",
                }
            ],
            "qa": [
                tool
                for tool in skills["full"]
                if tool.name in {
                    "lookup_subjects_tool",
                    "lookup_electives_tool",
                    "lookup_major_tool",
                    "lookup_uow_policy_tool",
                }
            ],
        }

        llms = LLMRegistry(llm_config, conversation_tools)
        stage1_tools = [
            tool
            for tool in skills["full"]
            if tool.name in {
                "lookup_uow_policy_tool",
            }
        ]

        stage1_llms = LLMRegistry(
            llm_config,
            {
                "confirm": skills["confirm"],
                "full": stage1_tools,
            },
        )

        stage2_llms = LLMRegistry(
            llm_config,
            {
                "confirm": skills["confirm"],
                "full": skills["full"],
            },
        )

        stage2_no_tools_llms = LLMRegistry(
            llm_config,
            {
                "confirm": skills["confirm"],
                "full": [],
            },
        )

        self._checkpointer = checkpointer
        self.conversation = ConversationNodes(
            llms,
            conversation_tools,
        )
        self.handbook = HandbookNodes(db)
        self.stage1 = Stage1Nodes(llms)
        self.stage2 = Stage2Nodes(stage2_llms, skills["full"], no_tools_llms=stage2_no_tools_llms)

    def build(self) -> StateGraph:
        graph = StateGraph(AdvisorState)
        conversation, handbook, stage1, stage2 = (
            self.conversation, self.handbook, self.stage1, self.stage2,
        )

        # Conversational / metadata phase: collect and confirm student details.
        # graph.add_node("parse_input", conversation.parse_input)
        graph.add_node("agent", conversation.agent)
        graph.add_node("tools", conversation.run_tools)
        graph.add_node("capture_tool_results", conversation.capture_tool_results)

        # Handbook phase.
        graph.add_node("ensure_handbook", handbook.ensure_handbook)
        graph.add_node("handbook_missing", handbook.handbook_missing)

        # Stage 1: two parallel branches meeting at a deferred join.
        graph.add_node("start_planning", stage1.start_planning)
        graph.add_node("fetch_elective_list", stage1.fetch_elective_list)
        graph.add_node("populate_plan_electives", stage1.populate_plan_electives)
        graph.add_node("stage1_review_must_includes", stage1.generate_core_subjects)
        graph.add_node("eval_stage1_lists", stage1.evaluate)

        # Stage 2.
        graph.add_node("stage2_make_plan", stage2.make_plan)
        graph.add_node("stage2_tools", stage2.run_tools)
        graph.add_node("capture_stage2_tool_results", stage2.capture_tool_results)
        graph.add_node("evaluate_stage2", stage2.evaluate)
        graph.add_node("format_output", stage2.format_output)

        # Parse whatever metadata the paste carries, then let the agent decide:
        # call a tool, fetch the handbook, start planning, recommend electives or end the turn
        # (which surfaces the agent's question to the student).
        # graph.add_edge(START, "parse_input")
        graph.add_edge(START, "agent")
        graph.add_conditional_edges(
            "agent",
            conversation.route_after_agent,
            {
                "tools": "tools",
                "ensure_handbook": "ensure_handbook",
                "fetch_elective_list": "fetch_elective_list",
                "populate_plan_electives": "populate_plan_electives",
                "start_planning": "start_planning",
                END: END,
            },
        )
        graph.add_edge("tools", "capture_tool_results")
        graph.add_conditional_edges(
            "capture_tool_results",
            conversation.route_after_tool_results,
            {
                "agent": "agent",
                "ensure_handbook": "ensure_handbook",
                END: END,
            },
        )

        # Handbook gate: planning only proceeds with the matching handbook.
        graph.add_conditional_edges(
            "ensure_handbook", handbook.route_after_fetch,
            {
                "start_planning": "start_planning",
                "fetch_elective_list": "fetch_elective_list",
                "populate_plan_electives": "populate_plan_electives",
                "handbook_missing": "handbook_missing",
            },
        )
        graph.add_edge("handbook_missing", END)

        # Electives are fetched only when requested by the agent.
        graph.add_edge("fetch_elective_list", END)
        # update the plan with the electives if a plan exists
        graph.add_edge("populate_plan_electives", END)

        # Stage 1: generate and evaluate the core subjects sequentially.
        graph.add_conditional_edges(
            "start_planning",
            stage1.route_after_start_planning,
            {
                "stage1_review_must_includes": "stage1_review_must_includes",
                "__end__": END,
            },
        )
        graph.add_edge("stage1_review_must_includes", "eval_stage1_lists")

        # A failed evaluation reruns only the core branch, which meets the
        # join again on its own.
        graph.add_conditional_edges(
            "eval_stage1_lists", stage1.route_stage1_eval,
            {
                "stage1_review_must_includes": "stage1_review_must_includes",
                "stage2_make_plan": "stage2_make_plan",
            },
        )

        # Stage 2: plan, loop through tools as needed, evaluate, retry or emit.
        graph.add_conditional_edges(
            "stage2_make_plan",
            stage2.route_after_make_plan,
            {
                "stage2_tools": "stage2_tools",
                "evaluate_stage2": "evaluate_stage2",
                "format_output": "format_output",
            },
        )
        graph.add_edge("stage2_tools", "capture_stage2_tool_results")
        graph.add_conditional_edges(
            "capture_stage2_tool_results",
            stage2.route_after_tool_results,
            {
                "stage2_make_plan": "stage2_make_plan",
                "format_output": "format_output",
            },
        )
        graph.add_conditional_edges(
            "evaluate_stage2", stage2.route_evaluation,
            {"stage2_make_plan": "stage2_make_plan", "format_output": "format_output"},
        )
        graph.add_edge("format_output", END)

        return graph

    def compile(self) -> CompiledStateGraph:
        return self.build().compile(checkpointer=self._checkpointer)


def build_advisor_graph(
    db: AsyncSession,
    checkpointer: BaseCheckpointSaver,
    llm_config: LLMConfig | None = None,
) -> CompiledStateGraph:
    """Compile the advisor graph bound to this request's DB session and key."""
    return AdvisorGraph(db, checkpointer, llm_config).compile()
