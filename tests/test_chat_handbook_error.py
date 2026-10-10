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
