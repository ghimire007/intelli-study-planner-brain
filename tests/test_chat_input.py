import pytest

from app.schemas.chat import ChatRequest
from app.services.agent_chat_service import prepare_first_message
from app.services.enrolment import UnreadableRecord

pytestmark = pytest.mark.smoke


def test_question_can_start_without_an_enrolment_record():
    text, is_record = prepare_first_message("Hello, can you help me plan my course?", "question")
    assert text == "Hello, can you help me plan my course?"
    assert not is_record


def test_existing_record_clients_remain_strict():
    assert ChatRequest(message="hello").input_type == "enrolment"
    with pytest.raises(UnreadableRecord):
        prepare_first_message("hello", "enrolment")


def test_record_pasted_as_question_does_not_bypass_projection():
    with pytest.raises(UnreadableRecord):
        prepare_first_message("Student Name: Example Person\n| Invalid | Table |", "question")


def test_empty_question_is_rejected():
    with pytest.raises(ValueError):
        prepare_first_message("  ", "question")
