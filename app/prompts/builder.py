"""Assembles the advisor agent's system prompt for a given turn.

Kept separate from the graph's orchestration logic (app/agents/graph.py) so
prompt phrasing/structure can change without touching state-machine code.
"""
from app.prompts.system import SYSTEM_PROMPT


def build_system_prompt(*, meta: dict, meta_confirmed: bool, handbook: str | None, raw_sols: str) -> str:
    if meta_confirmed:
        metadata_note = (
            f"\n\nStudent metadata: degree_code={meta['degree_code']}, year={meta['year']}, "
            f"campus={meta['campus']}."
        )
        handbook_placeholder = "(not yet fetched — call fetch_handbook_tool)"
    else:
        missing = [
            field for field in ("degree_code", "year")
            if meta.get(field) is None
        ]
        known_bits = ", ".join(
            f"{field}={meta[field]}" for field in ("degree_code", "year", "campus")
            if meta.get(field) is not None
        )
        metadata_note = (
            f"\n\nCould not confidently determine the student's {' and '.join(missing)} from the SOLS record"
            f"{f' (what was extracted: {known_bits})' if known_bits else ''}. Before doing anything else, ask "
            f"the student directly for their {' and '.join(missing)}. Once you have it, call "
            "confirm_metadata_tool with the final degree_code/year/campus values. Do not fetch the handbook or "
            "attempt any audit/planning before this tool has been called."
        )
        handbook_placeholder = "(unavailable — missing student details must be confirmed first)"

    return (
        SYSTEM_PROMPT
        .replace("{{handbook}}", handbook or handbook_placeholder)
        .replace("{{sols}}", raw_sols)
        + metadata_note
    )
