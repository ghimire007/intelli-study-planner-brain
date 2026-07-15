def as_text(content: str | list) -> str:
    """ChatGoogleGenerativeAI.content is str | list[str | dict] — flatten to text."""
    if isinstance(content, str):
        return content
    return "".join(
        block if isinstance(block, str) else block.get("text", "")
        for block in content
    )
