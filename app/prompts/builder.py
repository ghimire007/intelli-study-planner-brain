"""Assembles the advisor agent's system prompt for a given turn.

Kept separate from the graph's orchestration logic (app/agents/graph.py) so
prompt phrasing/structure can change without touching state-machine code.
"""
from app.prompts.system import SYSTEM_PROMPT

# Exact intake question when degree metadata is not yet confirmed.
INTAKE_QUESTION = (
    "What is your commencement/enrolment year, campus, degree (course code), "
    "and major (or say if you have no major)?"
)


def _course_handbook_link(degree_code: str | None) -> str:
    """Build the CourseLoop handbook anchor for the confirmed degree, if known."""
    if not degree_code:
        return (
            "the official course handbook for the student's confirmed degree_code "
            "(do not assume course 766)"
        )
    url = f"https://courses.uow.edu.au/courses/2026/{degree_code}"
    return f'<a href="{url}" target="_blank">course handbook</a>'


def build_system_prompt(*, meta: dict, meta_confirmed: bool, handbook: str | None, raw_sols: str) -> str:
    """Assemble the system prompt for this turn from handbook, SOLS, and meta state."""
    degree_code = (meta or {}).get("degree_code")

    if meta_confirmed:
        major = meta.get("major")
        major_bit = f", major={major}" if major else ", major=(not stated)"
        metadata_note = (
            f"\n\nStudent metadata: degree_code={meta['degree_code']}, year={meta['year']}, "
            f"campus={meta['campus']}{major_bit}. Advise only under this degree's handbook. "
            "If the student asks to switch degree, year, or campus, call confirm_metadata_tool "
            "with the new values (this clears the cached handbook), then call fetch_handbook_tool "
            "before advising under the new program. Never keep using a previous degree's rules "
            "after a switch. If major is missing or \"not stated\" and the plan depends on a major "
            "(or no-major path), ask for the major before finalising."
        )
        handbook_placeholder = "(not yet fetched — call fetch_handbook_tool)"
    else:
        known_bits = ", ".join(
            f"{field}={meta[field]}" for field in ("degree_code", "year", "campus")
            if meta and meta.get(field) is not None
        )
        metadata_note = (
            "\n\nStudent degree metadata is not yet confirmed"
            f"{f' (parser extracted candidates only — treat as unverified: {known_bits})' if known_bits else ''}."
            " Your entire reply this turn must be **exactly one question** — use this wording "
            f"(you may add a brief greeting before it): \"{INTAKE_QUESTION}\" "
            "Do not assume 766 or any other degree. Do not audit, plan, or call "
            "fetch_handbook_tool yet. Do not ask follow-up questions as separate turns. "
            "After the student answers, call confirm_metadata_tool with degree_code, year, "
            "campus, and major (or major=null / \"none\" if they have no major)."
        )
        handbook_placeholder = "(unavailable — missing student details must be confirmed first)"

    return (
        SYSTEM_PROMPT
        .replace("{{handbook}}", handbook or handbook_placeholder)
        .replace("{{sols}}", raw_sols)
        .replace(
            "{{course_handbook_link}}",
            _course_handbook_link(degree_code if meta_confirmed else None),
        )
        + metadata_note
    )
