import json
import re


def as_text(content: str | list) -> str:
    """ChatGoogleGenerativeAI.content is str | list[str | dict] — flatten to text."""
    if isinstance(content, str):
        return content
    return "".join(
        block if isinstance(block, str) else block.get("text", "")
        for block in content
    )


def is_evaluation_reply(content: str | list) -> bool:
    """Match a standalone evaluator verdict, leaving plans and prose untouched."""
    text = as_text(content).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    try:
        value = json.loads(fenced.group(1) if fenced else text)
    except (ValueError, TypeError):
        return False
    return (
        isinstance(value, dict)
        and set(value) == {"valid", "feedback"}
        and isinstance(value["valid"], bool)
        and isinstance(value["feedback"], str)
    )
