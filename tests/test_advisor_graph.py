"""Wiring of the advisor StateGraph around Stage 1's parallel branches.

The real Stage1Nodes routers, join and start_planning run. Only the nodes that
would call a model or a tool are replaced, so no database, checkpointer or LLM
is needed.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from app.agents.graphAPI import AdvisorGraph
from app.agents.llms import LLMRegistry
from app.agents.nodes.stage1 import Stage1Nodes
from langgraph.graph import END

pytestmark = pytest.mark.smoke

BRANCH_SECONDS = 0.15
META = {"degree_code": "766", "year": 2024, "campus": "Wollongong", "session": "Spring"}
HANDBOOK_OK = {
    "meta": META,
    "meta_confirmed": True,
    "handbook": "HANDBOOK",
    "handbook_degree_code": "766",
    "handbook_year": 2024,
    "handbook_campus": "Wollongong",
    "handbook_valid": True,
}


class FakeConversation:
    async def parse_input(self, state):
        return {}

    async def agent(self, state):
        return {}

    async def run_tools(self, state):
        raise AssertionError("tools must not run")

    def capture_tool_results(self, state):
        raise AssertionError("capture_tool_results must not run")

    @staticmethod
    def route_after_agent(state):
        return "start_planning"


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
    """Real start_planning, join and routers; scripted branches and verdicts.

    verdicts: one core_ok flag per evaluation.
    """

    def __init__(self, verdicts: list[bool] | None = None):
        super().__init__(LLMRegistry(None, {}))
        self.calls: list[str] = []
        self.spans: dict[str, tuple[float, float]] = {}
        self._verdicts = list(verdicts or [True])

    async def _branch(self, name: str) -> None:
        self.calls.append(name)
        started = time.perf_counter()
        await asyncio.sleep(BRANCH_SECONDS)
        self.spans.setdefault(name, (started, time.perf_counter()))

    async def fetch_elective_list(self, state):
        await self._branch("electives")
        return {"electives": json.dumps({"subjects": ["CSIT314"]})}

    async def generate_core_subjects(self, state):
        await self._branch("core")
        return {"remaining_subjects": "{}", "remaining_feedback": None}

    def join(self, state):
        self.calls.append("join")
        return {}

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


async def test_branches_overlap_and_join_once() -> None:
    stage1 = ScriptedStage1()
    out = await _run(stage1)

    assert out["conversation_mode"] == "post_plan"
    assert sorted(stage1.calls[:2]) == ["core", "electives"]
    assert stage1.calls[2:] == ["join", "eval", "plan"]

    electives_start, _ = stage1.spans["electives"]
    _, core_end = stage1.spans["core"]
    assert electives_start < core_end - BRANCH_SECONDS / 2


async def test_core_retry_does_not_rerun_electives(monkeypatch) -> None:
    stage1 = ScriptedStage1(verdicts=[False, True])
    await _run(stage1, retries=3, monkeypatch=monkeypatch)

    assert stage1.calls.count("electives") == 1
    assert stage1.calls.count("core") == 2
    # The deferred join still fires when the core branch reruns alone.
    assert stage1.calls.count("join") == 2
    assert stage1.calls[-3:] == ["join", "eval", "plan"]


async def test_final_pass_skips_the_evaluator() -> None:
    # Default budget of 2 passes: the second pass goes straight to Stage 2.
    stage1 = ScriptedStage1(verdicts=[False])
    await _run(stage1)

    assert stage1.calls.count("core") == 2
    assert stage1.calls.count("eval") == 1
    assert stage1.calls[-2:] == ["join", "plan"]


# Router and real-node checks.

def test_route_stage1_eval_targets() -> None:
    route = Stage1Nodes.route_stage1_eval
    assert route({"stage1_retry_count": 1}) == "stage2_make_plan"
    assert route({"remaining_feedback": "y", "stage1_retry_count": 1}) == "stage1_review_must_includes"
    assert route({"remaining_feedback": "y", "stage1_retry_count": 9}) == "stage2_make_plan"


def test_join_ends_when_handbook_is_invalid() -> None:
    assert Stage1Nodes.route_join_barrier({"meta": META}) == END


async def test_ranker_path_makes_no_model_call() -> None:
    """The registry has no key, so any model call would raise."""
    record = Path(__file__).resolve().parents[1] / "app" / "test_records" / "almost_graduated.md"
    out = await Stage1Nodes.fetch_elective_list(
        {**HANDBOOK_OK, "raw_sols": record.read_text(), "meta": {**META, "major": "AIBD — Artificial Intelligence and Big Data"}}
    )
    assert json.loads(out["electives"])["subjects"]


def test_stage1_nodes_and_deferred_join() -> None:
    graph = AdvisorGraph(db=None, checkpointer=None).build()
    assert {
        "fetch_elective_list", "stage1_review_must_includes", "join_stage1", "eval_stage1_lists",
    } <= set(graph.nodes)
    assert graph.nodes["join_stage1"].defer is True
    assert ("handbook_missing", END) in graph.edges
    assert ("format_output", END) in graph.edges

