"""Both chat routes must deliver the enrolment context to the planner."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from app.api.v1.chat import _get_agent_service
from app.main import app
from app.services.agent_chat_service import _record_input
from app.services.enrolment import parse_enrolment

pytestmark = pytest.mark.smoke

RECORD = (
    "Course:766Bachelor of Computer Science Instance:766Campus: Wollongong "
    "Delivery: On Campus Status: Transfer Major:SENGSoftware Engineering "
    "Year Session Campus/ Delivery Subject Code NomCP Mark Grade Status "
    "2025 Autumn Wollongong/ On Campus CSIT213 6 95 HD Complete "
    "2024 Autumn Wollongong/ On Campus CSIT110 6 88 HD Complete"
)


@pytest.mark.parametrize("continuing", [False, True])
async def test_enrolment_context_reaches_the_service_on_both_chat_routes(continuing):
    session_id = uuid.uuid4()
    service = AsyncMock()
    reply = SimpleNamespace(id=1, role="assistant", content="Generated plan",
                            created_at=datetime.now(timezone.utc))
    service.start_session.return_value = (SimpleNamespace(id=session_id), reply)
    service.continue_session.return_value = reply
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[_get_agent_service] = lambda: service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/v1/chat/{session_id}" if continuing else "/api/v1/chat"
            response = await client.post(path, json={
                "message": "Create a study plan for me.",
                "context": {"profile": {}, "enrolment_record": RECORD},
            })
        assert response.status_code == (200 if continuing else 201), response.text
        call = service.continue_session if continuing else service.start_session
        context = call.await_args.kwargs["context"]
        source, projected = _record_input("Create a study plan for me.", context)
        parsed = parse_enrolment(projected)
        assert source == RECORD
        assert (parsed.course_code, parsed.campus, parsed.majors) == (
            "766", "Wollongong", ["Software Engineering"],
        )
        assert len(parsed.rows) == 2
        assert "95" not in projected and "88" not in projected
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
