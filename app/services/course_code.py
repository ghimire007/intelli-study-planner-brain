"""Validate course numbers and their evidence in the student's conversation."""
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def normalize_course_code(value: object) -> str | None:
    code = str(value).strip() if value is not None else ""
    return code if re.fullmatch(r"[0-9]{3,4}", code) else None


def course_code_stated_by_student(
    value: object, messages: list[BaseMessage], *, year: object = None
) -> bool:
    """Require a course label or an answer to the advisor's course question.

    A substring anywhere in the transcript is insufficient: student IDs,
    subject codes, years and assistant/tool suggestions are not course evidence.
    """
    code = normalize_course_code(value)
    if code is None:
        return False

    course_question = False
    for message in messages:
        text = message.text if isinstance(message, BaseMessage) else ""
        if isinstance(message, AIMessage):
            # Tool calls must not overwrite the preceding intake question.
            if text.strip():
                course_question = bool(
                    re.search(r"\b(?:course|degree)\b", text, re.IGNORECASE)
                    and re.search(r"\?|\b(?:provide|tell|confirm)\b", text, re.IGNORECASE)
                )
        elif isinstance(message, HumanMessage):
            text = text.replace("*", "")
            if re.search(
                rf"\b(?:course|degree)\s*(?:(?:code|number|no\.?)\s*)?"
                rf"(?:(?:is|was)\s*)?[:=#(\-]?\s*{code}(?!\w|\.[0-9])",
                text,
                re.IGNORECASE,
            ):
                return True
            # Intake answers may be a bare course number or a comma-separated
            # year/campus/course list. Reject labeled unrelated numbers.
            if course_question and code != str(year):
                parts = re.split(r"[,;|\n]+", text)
                if any(part.strip().rstrip(".") == code for part in parts):
                    return True
            course_question = False
    return False
