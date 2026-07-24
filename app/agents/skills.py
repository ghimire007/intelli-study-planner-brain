"""Agent skills: thin LangChain tool adapters around services in app/services/.

This module owns no business logic itself — it only wraps existing service
functions (handbook lookup, metadata confirmation) as tools the advisor agent
can choose to invoke, and binds whatever runtime context (e.g. a DB session)
those services need.
"""
import json
from typing import Literal

from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.handbook_service import fetch_handbook
from app.services.kb_service import fetch_major, fetch_subjects
from app.services.knowledge_service import TOPIC_SLUGS, TOPICS, load_topic

# Newest handbook rows win; lookups are not tied to the student's commencement
# year (the scraper currently only loads the latest published handbook year).
_LATEST_HANDBOOK_YEAR = 9999


def make_fetch_handbook_tool(db: AsyncSession):
    """Bind a DB session to a `fetch_handbook` LangChain tool the agent can call."""

    @tool
    async def fetch_handbook_tool(degree_code: str, year: int, campus: str) -> str:
        """Fetch the official UOW course handbook markdown for a degree code/year/campus.

        Call this when you need the degree's rules, subject prerequisites, or
        session availability and don't already have the handbook content in context.
        """
        return await fetch_handbook(db, degree_code, year, campus)

    return fetch_handbook_tool


@tool
def confirm_metadata_tool(degree_code: str, year: int, campus: str) -> str:
    """Record the student's degree_code, commencement year, and campus as confirmed.

    Only call this AFTER the student has explicitly confirmed or corrected these
    three values in conversation — never on the first turn, and never guess on
    their behalf. Pass the final (possibly corrected) values. Do not call
    fetch_handbook_tool or attempt any audit/planning before this has been called.
    """
    return json.dumps({"degree_code": degree_code, "year": year, "campus": campus})


def make_lookup_subjects_tool(db: AsyncSession):
    """Bind a DB session to a batched subject-lookup LangChain tool."""

    @tool
    async def lookup_subjects_tool(codes: list[str]) -> str:
        """Look up official details for one or more UOW subject codes in a single call.

        Returns, per subject: title, credit points, prerequisites, session/campus
        availability, and the handbook URL. Batch every code you need (e.g. all
        subjects in a draft plan) into ONE call rather than calling repeatedly.
        Use this instead of guessing prerequisites or session availability.
        """
        return await fetch_subjects(db, codes, _LATEST_HANDBOOK_YEAR)

    return lookup_subjects_tool


def make_lookup_major_tool(db: AsyncSession):
    """Bind a DB session to a major-lookup LangChain tool."""

    @tool
    async def lookup_major_tool(major_code: str) -> str:
        """Look up an official UOW major (area of study) by its MAJ code, e.g. MAJ44204.

        Returns the major's title, credit points, required subjects, and handbook URL.
        Call this when the student has (or is considering) a major and you need its
        exact subject requirements.
        """
        return await fetch_major(db, major_code, _LATEST_HANDBOOK_YEAR)

    return lookup_major_tool


_topic_list = "\n".join(f"- {t.slug}: {t.description}" for t in TOPICS)


class _LookupPolicyArgs(BaseModel):
    topic: Literal[tuple(TOPIC_SLUGS)] = Field(description="Which policy topic to look up")


def _lookup_uow_policy(topic: str) -> str:
    return load_topic(topic)


lookup_uow_policy_tool = StructuredTool.from_function(
    func=_lookup_uow_policy,
    name="lookup_uow_policy_tool",
    description=(
        "Look up official UOW policy text for a specific topic. Call this whenever the "
        "student asks something one of these topics covers — never guess UOW policy "
        "yourself. Available topics:\n" + _topic_list
    ),
    args_schema=_LookupPolicyArgs,
)


def build_skills(db: AsyncSession):
    """Return the tools ("skills") available to the advisor agent, split by whether
    they require confirmed metadata. `confirm` is available before confirmation;
    `full` (superset) is available once the student has confirmed degree/year/campus.
    `lookup_uow_policy_tool` is available in both — general policy Q&A doesn't
    depend on having confirmed the student's degree/year/campus.
    """
    return {
        "confirm": [confirm_metadata_tool, lookup_uow_policy_tool],
        "full": [
            confirm_metadata_tool,
            lookup_uow_policy_tool,
            make_fetch_handbook_tool(db),
            make_lookup_subjects_tool(db),
            make_lookup_major_tool(db),
        ],
    }
