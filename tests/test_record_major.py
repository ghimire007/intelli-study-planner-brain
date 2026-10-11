import json
from types import SimpleNamespace

from app.agents.nodes.conversation import ConversationNodes
from app.services.study_plan import plan_sources
from langchain_core.messages import HumanMessage

from tests.test_study_plan import example


class _Parser:
    def __init__(self, majors):
        self._reply = json.dumps({"degree_code": "1802", "year": 2024, "campus": "Wollongong", "majors": majors})

    async def ainvoke(self, _messages):
        return SimpleNamespace(content=self._reply)


def _nodes(majors):
    return ConversationNodes(SimpleNamespace(get=lambda _kind: _Parser(majors)), [])


def _state(meta_extra):
    _, state = example()
    state["meta"] = {"degree_code": "1802", "year": 2024, "campus": "Wollongong", **meta_extra}
    state["messages"] = [HumanMessage(content=state["raw_sols"])]
    state["field_sources"], state["context_observations"], state["context_conflicts"] = {}, {}, {}
    return state


async def test_record_that_lists_no_major_keeps_the_saved_major():
    state = _state({"major": "Software Engineering"})
    update = await _nodes([]).parse_input(state)

    meta = update["meta"]
    assert meta["major"] == "Software Engineering"
    assert meta.get("majors") is None  # not an explicit "no major"
    required_with_major = plan_sources({**state, "meta": meta})[2]
    required_without_major = plan_sources({**state, "meta": {**meta, "major": None}})[2]
    assert required_with_major > required_without_major  # the saved major's core subjects are required


async def test_record_that_lists_a_major_is_authoritative():
    update = await _nodes(["Software Engineering"]).parse_input(_state({"major": "Cyber Security"}))
    assert update["meta"]["majors"] == ["Software Engineering"]


async def test_a_confirmed_no_major_is_not_undone_by_a_record_that_lists_none():
    update = await _nodes([]).parse_input(_state({"majors": []}))
    assert update["meta"]["majors"] == []


async def test_first_parse_of_a_stored_record_does_not_write_an_empty_majors_list():
    state = _state({})
    state["meta"] = None
    state["messages"] = [HumanMessage(content="hello")]
    update = await _nodes([]).parse_input(state)
    assert "majors" not in update["meta"]
