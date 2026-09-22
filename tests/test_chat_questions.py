import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents import graph as graph_module
from app.services import agent_chat_service as service_module
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

pytestmark = pytest.mark.smoke


@pytest.mark.parametrize("question", ["Create a study plan for me.", "Can I study game development?", "Hello!"])
async def test_question_reaches_advisor_model_without_record_parser(monkeypatch, question):
    model = MagicMock()
    model.bind_tools.return_value = model
    model.ainvoke = AsyncMock(return_value=AIMessage(content="A response from the model"))
    monkeypatch.setattr(graph_module, "make_chat_model", lambda config: model)
    parser = AsyncMock(side_effect=AssertionError("A question must not enter the SOLS parser"))
    monkeypatch.setattr(graph_module, "parse_sols", parser)
    graph = graph_module.build_advisor_graph(MagicMock(), InMemorySaver(), SimpleNamespace())
    state = await graph.ainvoke({"messages": [HumanMessage(content=question)], "raw_sols": "", "meta": None, "meta_confirmed": False, "handbook": None}, {"configurable": {"thread_id": str(uuid.uuid4())}})
    assert state["messages"][-1].content == "A response from the model"
    model.ainvoke.assert_awaited_once()
    assert model.ainvoke.call_args.args[0][-1].content == question
    parser.assert_not_awaited()


async def test_start_session_passes_question_to_graph(monkeypatch):
    service = object.__new__(service_module.AgentChatService)
    service._db = MagicMock()
    service._db.commit = AsyncMock()
    service._user = SimpleNamespace(id=uuid.uuid4())
    config = SimpleNamespace(provider=SimpleNamespace(value="gemini"), model="test-model", credential_id=None)
    service._resolver = SimpleNamespace(resolve=AsyncMock(return_value=config))
    service._invoke = AsyncMock()
    graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(values={"meta": {}})))
    monkeypatch.setattr(service_module, "build_advisor_graph", lambda *args: graph)
    monkeypatch.setattr(service_module, "get_checkpointer", lambda: None)
    monkeypatch.setattr(service_module, "latest_reply", AsyncMock(return_value="model reply"))
    session, reply = await service.start_session("Hello", input_type="question")
    payload = service._invoke.call_args.args[2]
    assert payload["raw_sols"] == ""
    assert payload["messages"][0].content == "Hello"
    assert session.user_id == service._user.id
    assert reply == "model reply"
