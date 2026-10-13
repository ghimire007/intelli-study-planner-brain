import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from app.api.v1.chat import _get_agent_service
from app.main import app
from app.services.handbook_service import HandbookUnavailable

pytestmark = pytest.mark.smoke


@pytest.mark.parametrize("path", ["/api/v1/chat", f"/api/v1/chat/{uuid.uuid4()}"])
async def test_missing_handbook_is_not_a_missing_conversation(path):
    service = AsyncMock()
    service.start_session.side_effect = HandbookUnavailable("No handbook found")
    service.continue_session.side_effect = HandbookUnavailable("No handbook found")
    app.dependency_overrides[_get_agent_service] = lambda: service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(path, json={"message": "2024, Wollongong, 766"})
        assert response.status_code == 503
        assert "handbook" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


async def test_provider_model_not_found_is_not_an_unhandled_server_error():
    from app.api.v1.chat import _raise_llm_http_error
    from fastapi import HTTPException

    error = RuntimeError("Provider model not found")
    error.code = 404
    with pytest.raises(HTTPException) as caught:
        _raise_llm_http_error(error)
    assert caught.value.status_code == 422
    assert "Select an available model" in caught.value.detail


def test_provider_timeout_is_actionable_and_preserves_chat():
    from app.api.v1.chat import _raise_llm_http_error
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        _raise_llm_http_error(TimeoutError())
    assert caught.value.status_code == 504
    assert "saved chat is preserved" in caught.value.detail


async def test_handbook_ref_returns_degree_year_campus():
    service = AsyncMock()
    service.get_handbook_ref.return_value = {"degree_code": "766", "year": 2024, "campus": "Wollongong"}
    app.dependency_overrides[_get_agent_service] = lambda: service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/chat/{uuid.uuid4()}/handbook")
        assert response.status_code == 200
        assert response.json() == {"degree_code": "766", "year": 2024, "campus": "Wollongong"}
    finally:
        app.dependency_overrides.clear()


async def test_handbook_ref_unknown_session_is_404():
    from app.services.chat_context import SessionNotFound

    service = AsyncMock()
    service.get_handbook_ref.side_effect = SessionNotFound("nope")
    app.dependency_overrides[_get_agent_service] = lambda: service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/chat/{uuid.uuid4()}/handbook")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def _service_with_state(monkeypatch, values):
    from types import SimpleNamespace

    from app.agents.graphAPI import build_advisor_graph
    from app.services import agent_chat_service as module
    from langgraph.checkpoint.memory import MemorySaver

    saver = MemorySaver()
    session_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4())
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(user_id=user.id)
    monkeypatch.setattr(module, "get_checkpointer", lambda: saver)
    if values is not None:
        graph = build_advisor_graph(db, saver)
        await graph.aupdate_state({"configurable": {"thread_id": str(session_id)}}, values)
    return module.AgentChatService(db=db, user=user), session_id


async def test_handbook_ref_reads_meta_from_conversation_state(monkeypatch):
    meta = {"degree_code": "766", "year": 2024, "campus": "Wollongong"}
    service, session_id = await _service_with_state(monkeypatch, {"raw_sols": "x", "meta": meta})
    assert await service.get_handbook_ref(session_id) == meta


async def test_handbook_ref_is_null_until_details_are_known(monkeypatch):
    service, session_id = await _service_with_state(monkeypatch, {"raw_sols": "x", "meta": {}})
    assert await service.get_handbook_ref(session_id) == {"degree_code": None, "year": None, "campus": None}


async def test_handbook_ref_without_state_is_not_found(monkeypatch):
    from app.services.chat_context import SessionNotFound

    service, session_id = await _service_with_state(monkeypatch, None)
    with pytest.raises(SessionNotFound):
        await service.get_handbook_ref(session_id)
