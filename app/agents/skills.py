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
from app.services.knowledge_service import TOPIC_SLUGS, TOPICS, load_topic


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
        "full": [confirm_metadata_tool, lookup_uow_policy_tool, make_fetch_handbook_tool(db)],
    }
