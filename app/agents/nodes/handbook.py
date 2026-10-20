"""Handbook gate nodes: fetch exactly the handbook the confirmed metadata identifies."""
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import (
    HANDBOOK_CLEARED,
    AdvisorState,
    handbook_matches_current_meta,
    metadata_handbook_key,
)
from app.services.handbook_service import fetch_handbook


class HandbookNodes:
    """Fetch exactly the handbook the confirmed metadata identifies."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def ensure_handbook(self, state: AdvisorState) -> dict:
        # print("NODE: ensure_handbook")

        required = metadata_handbook_key(state.get("meta"))
        if required is None:
            # print("HANDBOOK FETCH: invalid metadata")
            return {**HANDBOOK_CLEARED, "planning_requested": False}

        degree_code, year, campus = required
        # print("HANDBOOK FETCH:", degree_code, year, campus)

        try:
            content = await fetch_handbook(self._db, degree_code, year, campus)
        except Exception as exc:
            # print("HANDBOOK FETCH ERROR:", repr(exc))
            return {**HANDBOOK_CLEARED, "planning_requested": False}

        if not content or not str(content).strip():
            # print("HANDBOOK FETCH FAILED: empty")
            return {**HANDBOOK_CLEARED, "planning_requested": False}

        # print("HANDBOOK FETCH SUCCESS:", required)
        return {
            "handbook": content,
            "handbook_degree_code": degree_code,
            "handbook_year": year,
            "handbook_campus": campus,
            "handbook_valid": True,
        }

    @staticmethod
    def route_after_fetch(
        state: AdvisorState,
    ) -> Literal["start_planning", "fetch_elective_list", "populate_plan_electives", "handbook_missing"]:
        if not handbook_matches_current_meta(state):
            return "handbook_missing"

        pending = state.get("pending_elective_action")

        if pending == "populate_plan":
            return "populate_plan_electives"

        if pending == "recommend":
            return "fetch_elective_list"

        return "start_planning"

    @staticmethod
    async def handbook_missing(state: AdvisorState) -> dict:
        """Stop planning until the handbook can be obtained."""
        # print("NODE: handbook_missing")
        return {
            "planning_requested": False,
            "electives": None,
            "remaining_subjects": None,
            "plan": None,
            "remaining_feedback": None,
            "plan_feedback": None,
        }
