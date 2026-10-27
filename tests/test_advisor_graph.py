"""Wiring of the advisor StateGraph around Stage 1.

The real Stage1Nodes routers, join and start_planning run. Only the nodes that
would call a model or a tool are replaced, so no database, checkpointer or LLM
is needed.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.graphAPI import AdvisorGraph
from app.agents.llms import LLMRegistry
from app.agents.nodes.stage1 import Stage1Nodes
from app.agents.nodes.stage2 import Stage2Nodes
from app.llm.config import LLMConfig
from app.llm.registry import Provider
from app.services.enrolment import project
from app.services.sols_parser import extract_sols_metadata
from app.services.study_plan_output import read_study_plan
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END

pytestmark = pytest.mark.smoke

META = {"degree_code": "766", "year": 2024, "campus": "Wollongong", "session": "Spring"}
HANDBOOK_OK = {
    "meta": META,
    "meta_confirmed": True,
    "handbook": "HANDBOOK",
    "handbook_degree_code": "766",
    "handbook_year": 2024,
    "handbook_campus": "Wollongong",
    "handbook_valid": True,
    "major_validation_passed": True,
}


class FakeConversation:
    # async def parse_input(self, state):
    #     return {}

    async def agent(self, state):
        return {}

    async def run_tools(self, state):
        raise AssertionError("tools must not run")

    def capture_tool_results(self, state):
        raise AssertionError("capture_tool_results must not run")

    @staticmethod
    def route_after_agent(state):
        return "start_planning"

    @staticmethod
    def route_after_tool_results(state):
        return END


class FakeHandbook:
    async def ensure_handbook(self, state):
        raise AssertionError("ensure_handbook must not run")

    @staticmethod
    def route_after_fetch(state):
        return "handbook_missing"

    @staticmethod
    async def handbook_missing(state):
        raise AssertionError("handbook_missing must not run")


class ScriptedStage1(Stage1Nodes):
    """Real start_planning and routers; scripted core generation and verdicts.

    verdicts: one core_ok flag per evaluation.
    """

    def __init__(self, verdicts: list[bool] | None = None):
        super().__init__(LLMRegistry(None, {}))
        self.calls: list[str] = []
        self._verdicts = list(verdicts or [True])

    async def generate_core_subjects(self, state):
        self.calls.append("core")
        return {"remaining_subjects": "{}", "remaining_feedback": None}

    async def evaluate(self, state):
        self.calls.append("eval")
        core_ok = self._verdicts.pop(0)
        return {
            "remaining_feedback": None if core_ok else "fix core",
            "stage1_retry_count": state.get("stage1_retry_count", 0) + 1,
        }


class FakeStage2:
    def __init__(self, calls: list[str]):
        self._calls = calls

    async def make_plan(self, state):
        self._calls.append("plan")
        return {"plan": "PLAN"}

    async def run_tools(self, state):
        raise AssertionError("stage2_tools must not run")

    @staticmethod
    def capture_tool_results(state):
        raise AssertionError("capture_stage2_tool_results must not run")

    @staticmethod
    def route_after_tool_results(state):
        return "format_output"

    @staticmethod
    def route_after_make_plan(state):
        return "evaluate_stage2"

    async def evaluate(self, state):
        return {"plan_feedback": None}

    @staticmethod
    def route_evaluation(state):
        return "format_output"

    @staticmethod
    async def format_output(state):
        return {"conversation_mode": "post_plan"}


async def _run(stage1: ScriptedStage1, retries: int = 2, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr("app.agents.nodes.stage1.MAX_STAGE1_RETRIES", retries)
    graph = AdvisorGraph(db=None, checkpointer=None)
    graph.conversation = FakeConversation()
    graph.handbook = FakeHandbook()
    graph.stage1 = stage1
    graph.stage2 = FakeStage2(stage1.calls)
    return await graph.compile().ainvoke({"messages": [], **HANDBOOK_OK})


async def test_stage1_runs_core_then_evaluator_then_plan() -> None:
    stage1 = ScriptedStage1()
    out = await _run(stage1)

    assert out["conversation_mode"] == "post_plan"
    assert stage1.calls == ["core", "eval", "plan"]


COMPACT_RECORD = (
    "Course:766Bachelor of Computer Science Instance:766Campus: Wollongong "
    "Delivery: On Campus Status: Transfer Major:SENGSoftware Engineering "
    "Year Session Campus/ Delivery Subject Code NomCP Mark Grade Status "
    "2025 Autumn Wollongong/ On Campus CSIT213 6 95 HD Complete "
    "2024 Autumn Wollongong/ On Campus CSIT110 6 88 HD Complete"
)


@pytest.mark.parametrize(("provider", "model"), [
    (Provider.OPENAI, "gpt-5.1"), (Provider.GEMINI, "gemini-3.5-flash"),
])
@pytest.mark.parametrize("record", [COMPACT_RECORD, (Path(__file__).resolve().parents[1]
                                                  / "app/test_records/almost_graduated.md").read_text()])
async def test_complete_record_fetches_handbook_and_plans_without_intake_model(
    monkeypatch, provider, model, record,
):
    fetch = AsyncMock(return_value="AUTHORITATIVE HANDBOOK")
    monkeypatch.setattr("app.agents.nodes.handbook.fetch_handbook", fetch)
    graph = AdvisorGraph(db=None, checkpointer=None, llm_config=LLMConfig(
        provider=provider, model=model, api_key="unused", credential_id=None,
    ))
    registry = MagicMock()
    registry.get.side_effect = AssertionError("Complete records must not call an intake model")
    graph.conversation._llms = registry
    stage1 = ScriptedStage1()
    stage1.start_planning = AsyncMock(return_value={
        "major_validation_passed": True, "planning_requested": False,
    })
    graph.stage1 = stage1
    graph.stage2 = FakeStage2(stage1.calls)
    projected = project(record)
    metadata = extract_sols_metadata(record).model_dump()
    result = await graph.compile().ainvoke({
        "messages": [HumanMessage(content=projected)],
        "raw_sols": projected, "meta": metadata,
        "meta_confirmed": False, "planning_requested": True,
    })
    assert result["plan"] == "PLAN"
    assert stage1.calls == ["core", "eval", "plan"]
    assert result["meta"]["degree_code"] == "766"
    assert result["meta"]["year"] == 2024
    assert result["meta"]["majors"] in (["Software Engineering"], ["AIBD"])
    fetch.assert_awaited_once_with(None, "766", 2024, "Wollongong")
    registry.get.assert_not_called()


async def test_missing_handbook_stops_planning_and_explains_failure(monkeypatch):
    fetch = AsyncMock(side_effect=ValueError("not seeded"))
    monkeypatch.setattr("app.agents.nodes.handbook.fetch_handbook", fetch)
    graph = AdvisorGraph(db=None, checkpointer=None)
    projected = project(COMPACT_RECORD)
    result = await graph.compile().ainvoke({
        "messages": [HumanMessage(content=projected)],
        "raw_sols": projected, "meta": extract_sols_metadata(COMPACT_RECORD).model_dump(),
        "meta_confirmed": False, "planning_requested": True,
    })
    assert result["plan"] is None
    assert "couldn't retrieve the handbook" in result["messages"][-1].content


@pytest.mark.parametrize("student_request", [
    "Can you generate the study plan for me?",
    "You should put it in the Study Plan beside me ->",
])
async def test_direct_plan_request_retries_prose_and_returns_panel_data(monkeypatch, student_request):
    monkeypatch.setattr("app.agents.nodes.handbook.fetch_handbook", AsyncMock(return_value="HANDBOOK"))
    graph = AdvisorGraph(db=None, checkpointer=None)
    # No intake model: this existing conversation already has its metadata.
    graph.conversation._llms = None
    stage1 = ScriptedStage1()
    stage1.start_planning = AsyncMock(return_value={
        "major_validation_passed": True, "planning_requested": False,
    })
    graph.stage1 = stage1
    payload = {"plan": [{"year": "2026", "sessions": [{"session": "Autumn", "subjects": [
        {"code": "CSIT314", "name": "Software Development Methodologies", "cp": 6, "notes": ""},
    ]}]}]}
    full = MagicMock()
    full.ainvoke = AsyncMock(side_effect=[
        AIMessage(content="Here is a prose list of subjects."),
        AIMessage(content=json.dumps(payload)),
    ])
    parser = MagicMock()
    parser.ainvoke = AsyncMock(return_value=AIMessage(content='{"valid": true, "feedback": ""}'))
    registry = MagicMock()
    registry.get.side_effect = lambda kind: parser if kind == "parser" else full
    graph.stage2 = Stage2Nodes(registry, [], no_tools_llms=registry)
    result = await graph.compile().ainvoke({
        **HANDBOOK_OK, "planning_requested": False, "conversation_mode": "collecting",
        "messages": [HumanMessage(content=student_request)], "raw_sols": project(COMPACT_RECORD),
    })
    assert result["conversation_mode"] == "post_plan"
    assert full.ainvoke.await_count == 2
    assert parser.ainvoke.await_count == 1
    assert "| Year | Session | Subject Code |" in result["messages"][-1].content
    assert read_study_plan(result["messages"][-1].content)[0].model_dump() == payload


async def test_core_retry_reruns_only_core(monkeypatch) -> None:
    stage1 = ScriptedStage1(verdicts=[False, True])
    await _run(stage1, retries=3, monkeypatch=monkeypatch)

    assert stage1.calls == ["core", "eval", "core", "eval", "plan"]


async def test_retry_limit_goes_to_stage2_despite_failing_verdict() -> None:
    # Default budget of 2 passes: a second failing verdict still goes to Stage 2.
    stage1 = ScriptedStage1(verdicts=[False, False])
    await _run(stage1)

    assert stage1.calls == ["core", "eval", "core", "eval", "plan"]


# Router and real-node checks.

def test_route_stage1_eval_targets() -> None:
    route = Stage1Nodes.route_stage1_eval
    assert route({"stage1_retry_count": 1}) == "stage2_make_plan"
    assert route({"remaining_feedback": "y", "stage1_retry_count": 1}) == "stage1_review_must_includes"
    assert route({"remaining_feedback": "y", "stage1_retry_count": 9}) == "stage2_make_plan"


class _ExplainerModel:
    async def ainvoke(self, messages):
        return AIMessage(content="EXPLAINED")


class _ExplainerRegistry:
    def get(self, role):
        return _ExplainerModel()


async def test_elective_list_is_ranked_from_data_and_only_explained_by_the_model() -> None:
    """The subjects come from the ranker; the model only writes the explanation."""
    record = Path(__file__).resolve().parents[1] / "app" / "test_records" / "almost_graduated.md"
    out = await Stage1Nodes(_ExplainerRegistry()).fetch_elective_list(
        {
            **HANDBOOK_OK,
            "raw_sols": record.read_text(),
            "elective_mode": "interest",
            "elective_interests": ["artificial intelligence"],
        }
    )
    assert json.loads(out["electives"])["subjects"]
    assert out["messages"][0].content == "EXPLAINED"


def test_stage1_nodes() -> None:
    graph = AdvisorGraph(db=None, checkpointer=None).build()
    assert {
        "fetch_elective_list", "populate_plan_electives", "stage1_review_must_includes", "eval_stage1_lists",
    } <= set(graph.nodes)
    assert ("handbook_missing", END) in graph.edges
    assert ("format_output", END) in graph.edges

