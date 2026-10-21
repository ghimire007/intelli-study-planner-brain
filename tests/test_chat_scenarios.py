"""Whole-conversation scenarios through the real advisor graph, with the models scripted.

The conversation, handbook gate, Stage 1, Stage 2 and elective nodes and every
router run for real, against a real record from tests/e2e/cases. Only what would
leave the process is replaced: each model returns the replies the scenario
scripts, and the handbook fetch returns a stub. The scenarios are the paths real
chats took, so a change to routing, state or the retry limits shows up here
without spending a model call.
"""

from __future__ import annotations

import json

import pytest
from app.agents.graphAPI import AdvisorGraph
from app.agents.llms import LLMRegistry
from app.agents.nodes.conversation import MAX_TOOL_CALLS_PER_TURN
from app.agents.state import MAX_STAGE2_RETRIES
from app.services.enrolment import project
from app.services.sols_parser import extract_sols_metadata
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from tests.e2e.cases import load_cases

pytestmark = pytest.mark.smoke

CASES = {case.id: case for case in load_cases()}
RECORD_766 = "real_766_wol_1maj_16done_0enr_5d5b"
RECORD_1807 = "real_1807_wol_1maj_4done_4enr_a698"
YEAR_766 = CASES[RECORD_766].commencement_year
MAJORS_766 = CASES[RECORD_766].majors

PLAN_JSON = {
    "plan": [
        {
            "year": "2027",
            "sessions": [
                {
                    "session": "Autumn",
                    "subjects": [
                        {
                            "code": "CSIT314",
                            "name": "Software Development Methodologies",
                            "cp": 6,
                            "notes": "",
                        }
                    ],
                }
            ],
        }
    ]
}
PLAN_TEXT = f"Audit\n```json\n{json.dumps(PLAN_JSON)}\n```"


def confirm(degree: str, year: int, campus: str, majors: list[str]) -> AIMessage:
    call = {
        "name": "confirm_metadata_tool",
        "id": "call_1",
        "args": {"degree_code": degree, "year": year, "campus": campus, "majors": majors},
    }
    return AIMessage(content="", tool_calls=[call])


class ScriptedModel:
    def __init__(self, replies: list[AIMessage]) -> None:
        self.replies = list(replies)
        self.sent: list[list] = []

    async def ainvoke(self, messages):
        self.sent.append(messages)
        assert self.replies, "the graph called a model the scenario did not script"
        return self.replies.pop(0)


class ScriptedRegistry(LLMRegistry):
    def __init__(self, **scripts: list[AIMessage]) -> None:
        super().__init__(None, {})
        self.models = {kind: ScriptedModel(replies) for kind, replies in scripts.items()}

    def get(self, kind: str) -> ScriptedModel:
        return self.models[kind]

    def unused(self) -> dict[str, int]:
        return {kind: len(model.replies) for kind, model in self.models.items() if model.replies}


class Chat:
    """One chat: a graph over an in-memory checkpointer, and the turns the student takes."""

    def __init__(self, monkeypatch, handbook: str | None = "HANDBOOK") -> None:
        self.fetches: list[tuple] = []

        async def fetch_handbook(db, degree_code, year, campus):
            self.fetches.append((degree_code, year, campus))
            return handbook

        monkeypatch.setattr("app.agents.nodes.handbook.fetch_handbook", fetch_handbook)
        self.graph = AdvisorGraph(db=None, checkpointer=MemorySaver())
        self.config = {"configurable": {"thread_id": "scenario"}}
        self.compiled = None

    def script(
        self, *, conversation=None, stage1=None, stage2=None, no_tools=None
    ) -> dict[str, ScriptedRegistry]:
        self.registries = {
            "conversation": ScriptedRegistry(**(conversation or {})),
            "stage1": ScriptedRegistry(**(stage1 or {})),
            "stage2": ScriptedRegistry(**(stage2 or {})),
        }
        self.graph.conversation._llms = self.registries["conversation"]
        self.graph.stage1._llms = self.registries["stage1"]
        self.graph.stage2._llms = self.registries["stage2"]
        self.graph.stage2._no_tools_llms = self.registries["stage2"]
        self.compiled = self.graph.compile()
        return self.registries

    async def start(self, text: str, *, record: bool) -> dict:
        """Open the chat the way `start_session` does: a record, or plain words."""
        message = project(text) if record else text
        meta = extract_sols_metadata(text).model_dump() if record else None
        return await self.compiled.ainvoke(
            {
                "messages": [HumanMessage(content=message)],
                "raw_sols": message if record else "no enrolment yet",
                "meta": meta,
                "meta_confirmed": False,
                "elective_mode": "degree",
                "elective_interests": [],
                "pending_elective_action": None,
                "conversation_mode": "collecting",
                "handbook": None,
                "electives": None,
                "remaining_subjects": None,
                "electives_feedback": None,
                "remaining_feedback": None,
                "plan": None,
                "plan_feedback": None,
                "retry_count": 0,
                "stage1_retry_count": 0,
                "stage2_retry_count": 0,
                "stage2_tool_loop_count": 0,
                "tool_calls_this_turn": 0,
                "planning_requested": record,
                "current_stage": None,
            },
            self.config,
        )

    async def say(self, text: str) -> dict:
        """A later turn: only the new message, on the saved state."""
        return await self.compiled.ainvoke(
            {
                "messages": [HumanMessage(content=text)],
                "tool_calls_this_turn": 0,
                "stage2_tool_loop_count": 0,
            },
            self.config,
        )


def last_reply(state: dict) -> str:
    return next(
        m.content for m in reversed(state["messages"]) if isinstance(m, AIMessage) and m.content
    )


CORE_REPLY = AIMessage(content=json.dumps({"core": ["CSIT314"]}))
MAJOR_OK = AIMessage(
    content=json.dumps({"valid": True, "reason": "listed in the handbook", "invalid_majors": []})
)
CORE_OK = AIMessage(content=json.dumps({"remaining_valid": True}))
PLAN_OK = AIMessage(content=json.dumps({"valid": True}))
INTERESTS = AIMessage(content=json.dumps({"interests": ["security"]}))
PLAN_BAD = AIMessage(
    content=json.dumps({"valid": False, "feedback": "CSIT314 is in the wrong session."})
)


def full_planning_scripts(*, plan_verdicts=(PLAN_OK,), plans=(AIMessage(content=PLAN_TEXT),)):
    return {
        "conversation": {"confirm": [confirm("766", YEAR_766, "Wollongong", MAJORS_766)]},
        "stage1": {"full": [CORE_REPLY], "parser": [MAJOR_OK, CORE_OK]},
        "stage2": {"full": list(plans), "parser": list(plan_verdicts)},
    }


async def test_paste_confirm_plan_reaches_post_plan_and_fetches_the_handbook_once(
    monkeypatch,
) -> None:
    chat = Chat(monkeypatch)
    registries = chat.script(**full_planning_scripts())
    state = await chat.start(CASES[RECORD_766].text, record=True)

    assert state["conversation_mode"] == "post_plan"
    assert state["meta_confirmed"] is True
    assert state["meta"]["degree_code"] == "766"
    assert state["plan"] == PLAN_TEXT
    assert "passed the evaluation checks" in last_reply(state)
    assert chat.fetches == [("766", YEAR_766, "Wollongong")]
    assert all(not left for left in registries["stage1"].unused().values())


@pytest.mark.parametrize("case_id", [RECORD_766, RECORD_1807, "real_766_wol_0maj_4done_4enr_d07c"])
async def test_every_degree_in_the_chats_plans_end_to_end(monkeypatch, case_id) -> None:
    case = CASES[case_id]
    degree, year, campus = case.record.course_code, case.commencement_year, case.campus
    chat = Chat(monkeypatch)
    scripts = full_planning_scripts()
    scripts["conversation"] = {"confirm": [confirm(degree, year, campus, case.majors)]}
    chat.script(**scripts)
    state = await chat.start(case.text, record=True)

    assert state["conversation_mode"] == "post_plan"
    assert (state["meta"]["degree_code"], state["meta"]["year"], state["meta"]["campus"]) == (
        degree,
        year,
        campus,
    )
    assert chat.fetches == [(degree, year, campus)]


async def test_electives_after_a_plan_update_it_without_refetching_the_handbook(
    monkeypatch,
) -> None:
    chat = Chat(monkeypatch)
    chat.script(**full_planning_scripts())
    await chat.start(CASES[RECORD_766].text, record=True)

    updated = AIMessage(content=PLAN_TEXT.replace("CSIT314", "CSCI262"))
    chat.script(
        conversation={"full": [AIMessage(content="I will look at electives.")]},
        stage1={"parser": [INTERESTS], "full": [updated]},
    )
    state = await chat.say("please recommend some security electives")

    assert state["plan"] == updated.content
    assert state["conversation_mode"] == "post_plan"
    assert state["pending_elective_action"] is None
    assert chat.fetches == [("766", YEAR_766, "Wollongong")]


async def test_changing_major_after_a_plan_replans_and_keeps_the_handbook(monkeypatch) -> None:
    chat = Chat(monkeypatch)
    chat.script(**full_planning_scripts())
    await chat.start(CASES[RECORD_766].text, record=True)

    second = AIMessage(content=PLAN_TEXT.replace("CSIT314", "CSIT321"))
    chat.script(
        conversation={
            "full": [
                confirm("766", YEAR_766, "Wollongong", ["Cyber Security"]),
                AIMessage(content="Re-planning."),
            ]
        },
        stage1={"full": [CORE_REPLY], "parser": [MAJOR_OK, CORE_OK]},
        stage2={"full": [second], "parser": [PLAN_OK]},
    )
    state = await chat.say("my major is Cyber Security")

    assert state["meta"]["majors"] == ["Cyber Security"]
    assert state["plan"] == second.content
    assert chat.fetches == [("766", YEAR_766, "Wollongong")]


async def test_tool_budget_spent_answers_with_the_limit_message_and_calls_no_model(
    monkeypatch,
) -> None:
    chat = Chat(monkeypatch)
    chat.script(**full_planning_scripts())
    await chat.start(CASES[RECORD_766].text, record=True)

    chat.script()  # no replies scripted: any model call fails the test
    state = await chat.compiled.ainvoke(
        {
            "messages": [HumanMessage(content="what is CSCI262 about?")],
            "tool_calls_this_turn": MAX_TOOL_CALLS_PER_TURN,
        },
        chat.config,
    )

    assert "tool-call limit" in last_reply(state)


async def test_greeting_with_no_record_asks_for_details_and_plans_nothing(monkeypatch) -> None:
    chat = Chat(monkeypatch)
    chat.script(
        conversation={"confirm": [AIMessage(content="Hello! Which degree, year and campus?")]}
    )
    state = await chat.start("Hello", record=False)

    assert state["meta_confirmed"] is False
    assert state["plan"] is None
    assert last_reply(state) == "Hello! Which degree, year and campus?"
    assert chat.fetches == []


async def test_details_only_goes_straight_to_a_plan_without_a_record(monkeypatch) -> None:
    chat = Chat(monkeypatch)
    scripts = full_planning_scripts()
    scripts["conversation"] = {"confirm": [confirm("766", 2026, "Wollongong", [])]}
    chat.script(**scripts)
    state = await chat.start("766, wollongong, 2026", record=False)

    assert state["meta_confirmed"] is True
    assert state["conversation_mode"] == "post_plan"
    assert chat.fetches == [("766", 2026, "Wollongong")]


async def test_missing_handbook_stops_planning_before_any_stage_runs(monkeypatch) -> None:
    chat = Chat(monkeypatch, handbook=None)
    registries = chat.script(**full_planning_scripts())
    state = await chat.start(CASES[RECORD_766].text, record=True)

    assert state["plan"] is None
    assert state["planning_requested"] is False
    assert registries["stage1"].unused() == {"full": 1, "parser": 2}
    assert registries["stage2"].unused() == {"full": 1, "parser": 1}


async def test_failing_audit_rewrites_the_plan_at_most_the_retry_limit(monkeypatch) -> None:
    chat = Chat(monkeypatch)
    plans = [AIMessage(content=PLAN_TEXT) for _ in range(MAX_STAGE2_RETRIES + 2)]
    registries = chat.script(
        **full_planning_scripts(plan_verdicts=[PLAN_BAD] * (MAX_STAGE2_RETRIES + 2), plans=plans)
    )
    state = await chat.start(CASES[RECORD_766].text, record=True)

    written = len(plans) - len(registries["stage2"].models["full"].replies)
    assert written == MAX_STAGE2_RETRIES
    assert "currently contains issues" in last_reply(state)
    assert state["conversation_mode"] == "post_plan"
