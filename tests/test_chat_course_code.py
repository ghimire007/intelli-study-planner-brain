"""Course numbers come from confirmed chat metadata and survive history reloads."""
import json
import uuid
from collections import deque
from unittest.mock import AsyncMock

import httpx
import pytest
from app.agents.nodes.conversation import ConversationNodes
from app.agents.state import AdvisorState
from app.api.deps import get_current_user
from app.core.database import get_db
from app.llm.config import LLMConfig
from app.llm.registry import Provider
from app.main import app
from app.models.auth import User
from app.models.session import ChatSession
from app.services import agent_chat_service
from app.services.course_code import course_code_stated_by_student
from app.services.sols_parser import extract_sols_metadata
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.smoke
META = {"degree_code": "1807", "year": 2024, "campus": "Wollongong"}
INTAKE = "What is your commencement year, campus and degree (course code)?"
RECORD = (
    "**Course:** 1807\n**Campus:** Wollongong\n\n"
    "| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |\n"
    "|---|---|---|---|---|---|---|---|\n"
    "| 2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 75 | D | Complete |"
)


@pytest.fixture
async def chat_client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.create)
        await conn.run_sync(ChatSession.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        # An account value must never supply a new conversation's course code.
        user = User(email="student@example.com", password_hash="unused", degree_code="766")
        db.add(user)
        await db.commit()

    saver = MemorySaver()
    turns = deque()

    def conversation(state):
        turn = turns.popleft() if turns else {}
        updates = {}
        if "candidate" in turn:
            tool = ToolMessage(content=json.dumps(turn["candidate"]),
                               name=turn.get("tool", "confirm_metadata_tool"), tool_call_id="confirm")
            updates = ConversationNodes(None, {}).capture_tool_results({
                **state, "messages": [*state["messages"], tool],
            })
        return {**updates, "messages": [AIMessage(content=turn.get("reply", INTAKE))]}

    def build_graph(*args, **kwargs):
        graph = StateGraph(AdvisorState)
        graph.add_node("conversation", conversation)
        graph.add_edge(START, "conversation")
        graph.add_edge("conversation", END)
        return graph.compile(checkpointer=saver)

    monkeypatch.setattr(agent_chat_service, "build_advisor_graph", build_graph)
    monkeypatch.setattr(agent_chat_service, "get_checkpointer", lambda: saver)
    resolver = AsyncMock(return_value=LLMConfig(
        provider=Provider.GEMINI, model="gemini-test", api_key="unused", credential_id=None,
    ))
    monkeypatch.setattr(agent_chat_service.CredentialResolver, "resolve", resolver)

    async def database():
        # Each HTTP request gets a fresh SQLAlchemy session.
        async with sessions() as db:
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client, sessions, turns, resolver
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        await engine.dispose()


async def start(client, message="Hello", **extra):
    response = await client.post("/api/v1/chat", json={"message": message, **extra})
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


async def send(client, session_id, message):
    response = await client.post(f"/api/v1/chat/{session_id}", json={"message": message})
    assert response.status_code == 200, response.text


async def history(client, session_id):
    response = await client.get(f"/api/v1/chat/{session_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_unknown_code_ignores_account_and_request_profile(chat_client):
    client, sessions, _, _ = chat_client
    session_id = await start(client, context={"profile": {"degree_code": "999"}})
    assert (await history(client, session_id))["degree_code"] == "UNKNOWN"
    async with sessions() as db:
        assert (await db.get(ChatSession, uuid.UUID(session_id))).degree_code == "UNKNOWN"


async def test_context_record_is_used_without_losing_the_request(chat_client):
    client, _, _, _ = chat_client
    context = {"profile": {}, "enrolment_record": RECORD}
    session_id = await start(client, "Create a study plan for me.", context=context)
    saved = await history(client, session_id)
    student_messages = [m["content"] for m in saved["messages"] if m["role"] == "user"]
    assert any("**Course:** 1807" in message and "CSIT110" in message for message in student_messages)
    assert student_messages[-1] == "Create a study plan for me."
    # Repeated context must not replace the record or regenerate a saved plan.
    response = await client.post(f"/api/v1/chat/{session_id}", json={
        "message": "Why did you choose those subjects?", "context": context,
    })
    assert response.status_code == 200
    saved = await history(client, session_id)
    assert sum("**Course:** 1807" in m["content"] for m in saved["messages"]) == 1


async def test_context_record_reaches_an_existing_chat(chat_client):
    client, _, _, _ = chat_client
    session_id = await start(client)
    response = await client.post(f"/api/v1/chat/{session_id}", json={
        "message": "Create a study plan for me.",
        "context": {"profile": {}, "enrolment_record": RECORD},
    })
    assert response.status_code == 200
    saved = await history(client, session_id)
    assert any("**Course:** 1807" in m["content"] for m in saved["messages"])


async def test_confirmation_survives_later_turns_and_new_database_sessions(chat_client):
    client, sessions, turns, resolver = chat_client
    session_id = await start(client)
    turns.append({"candidate": META, "reply": "Your course is confirmed."})
    await send(client, session_id, "2024, Wollongong, 1807")
    assert (await history(client, session_id))["degree_code"] == "1807"
    async with sessions() as db:
        assert (await db.get(ChatSession, uuid.UUID(session_id))).degree_code == "1807"

    await send(client, session_id, "Thanks! Tell me about electives.")
    # A new record resets meta_confirmed while the advisor asks for confirmation.
    await send(client, session_id, RECORD.replace("1807", "769"))
    resolver.reset_mock()
    saved = await history(client, session_id)
    assert saved["degree_code"] == "1807"
    assert any(m["content"] == "Your course is confirmed." for m in saved["messages"])
    resolver.assert_not_awaited()  # History does not require an AI key.

    # A separate chat starts unknown and cannot overwrite the first chat's code.
    other_id = await start(client)
    assert (await history(client, other_id))["degree_code"] == "UNKNOWN"
    assert (await history(client, session_id))["degree_code"] == "1807"


async def test_parsed_course_remains_unknown_until_student_confirms(chat_client):
    client, _, turns, _ = chat_client
    session_id = await start(client, RECORD)
    assert (await history(client, session_id))["degree_code"] == "UNKNOWN"
    turns.append({"candidate": META})
    await send(client, session_id, "Yes, those details are correct.")
    assert (await history(client, session_id))["degree_code"] == "1807"


async def test_history_recovers_confirmed_code_for_existing_session(chat_client):
    client, sessions, turns, _ = chat_client
    turns.append({"candidate": META})
    session_id = await start(client, "My course number is 1807, 2024, Wollongong")
    # Simulate a row written before confirmed metadata was synced on continuation.
    async with sessions() as db:
        session = await db.get(ChatSession, uuid.UUID(session_id))
        session.degree_code = "UNKNOWN"
        await db.commit()
    assert (await history(client, session_id))["degree_code"] == "1807"
    async with sessions() as db:
        assert (await db.get(ChatSession, uuid.UUID(session_id))).degree_code == "1807"


@pytest.mark.parametrize(("message", "candidate"), [
    ("My student ID is 9180723, 2024, Wollongong", "1807"),
    ("Student ID: 1807\n2024, Wollongong", "1807"),
    ("I took CSIT110 in 2024 at Wollongong", "110"),
    ("2024, Wollongong, I don't know my course number", "2024"),
    ("My course code is CSIT110, 2024, Wollongong", "CSIT110"),
])
@pytest.mark.parametrize("first_turn", [False, True])
async def test_unrelated_numbers_cannot_be_confirmed(chat_client, message, candidate, first_turn):
    client, _, turns, _ = chat_client
    turn = {"candidate": {**META, "degree_code": candidate}}
    if first_turn:
        turns.append(turn)
        session_id = await start(client, message)
    else:
        session_id = await start(client)
        turns.append(turn)
        await send(client, session_id, message)
    assert (await history(client, session_id))["degree_code"] == "UNKNOWN"


@pytest.mark.parametrize("tool", ["confirm_metadata_tool", "request_plan_change_tool"])
async def test_confirmed_course_changes_need_student_evidence(chat_client, tool):
    client, _, turns, _ = chat_client
    turns.append({"candidate": META})
    session_id = await start(client, "Course: 1807, 2024, Wollongong")
    candidate = ({**META, "degree_code": "769"} if tool == "confirm_metadata_tool"
                 else {"change_type": "course", "course": "769"})
    turns.append({"candidate": candidate, "tool": tool})
    await send(client, session_id, "My student ID is 9769123")
    assert (await history(client, session_id))["degree_code"] == "1807"
    turns.append({"candidate": candidate, "tool": tool})
    await send(client, session_id, "Please switch to course 769.")
    assert (await history(client, session_id))["degree_code"] == "769"


@pytest.mark.parametrize("text", [
    "Course: 1807", "**Course:** 1807 Bachelor of Computer Science",
    "My course number is 1807.", "My degree code is 1807", "degree 1807",
])
def test_explicit_course_numbers(text):
    assert course_code_stated_by_student("1807", [HumanMessage(content=text)])


def test_assistant_suggestion_is_not_student_confirmation():
    assert not course_code_stated_by_student("1807", [
        AIMessage(content="Your course might be 1807. Is that correct?"),
        HumanMessage(content="I don't know."),
    ])


@pytest.mark.parametrize("text", [
    "Student ID: 9180723", "Subject Code: CSIT110", "Course: CSIT110",
    "Course: 1807A", "Course: 1807123", "Course: 1807.5",
])
def test_sols_parser_rejects_unrelated_or_partial_numbers(text):
    assert extract_sols_metadata(text).degree_code is None


def test_record_year_comes_from_subject_rows_and_explicit_year_takes_precedence():
    parsed = extract_sols_metadata("Effective Date: 01 January 2020\n" + RECORD)
    assert parsed.year == 2024
    assert parsed.campus == "Wollongong"
    parsed = extract_sols_metadata("Commencement Year: 2023\n" + RECORD)
    assert parsed.year == 2023
