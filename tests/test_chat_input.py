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


@pytest.mark.parametrize("message", [
    "Create a study plan for me.",
    "What subjects should I take in the Autumn session this year?",
    "What should I study if I want to study game development?",
    "Am I allowed to take five subjects this semester?",
    "Course code: 766",
    "Hello!",
    "What does enrolment history mean?",
])
def test_questions_and_metadata_are_not_enrolment_records(message):
    text, is_record = prepare_first_message(message, "question")
    assert text == message
    assert not is_record


def test_question_contact_details_are_scrubbed():
    text, is_record = prepare_first_message("My email is student@example.com. Can I study part time?", "question")
    assert "student@example.com" not in text
    assert "Can I study part time?" in text
    assert not is_record
