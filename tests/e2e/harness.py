"""Drive the real advisor graph from a student record to a finished plan.

Only the chat turn that collects and confirms the student's details is
scripted; the handbook fetch, both planning stages, their tools and their
evaluators all run for real against the database and the live model.
"""
from __future__ import annotations

from app.agents.graphAPI import AdvisorGraph
from app.agents.nodes import ConversationNodes
from app.llm.config import LLMConfig
from app.services.enrolment import project
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.cases import Case


class ConfirmedStudent:
    """Stands in for the intake conversation: the details are already confirmed."""

    async def parse_input(self, state):
        return {}

    async def agent(self, state):
        return {}

    async def run_tools(self, state):
        raise AssertionError("the intake tools must not run")

    def capture_tool_results(self, state):
        raise AssertionError("the intake tools must not run")

    route_after_agent = staticmethod(ConversationNodes.route_after_agent)


async def generate_plan(case: Case, db: AsyncSession, llm_config: LLMConfig) -> str:
    """The plan text the student would be shown for this record."""
    graph = AdvisorGraph(db, None, llm_config)
    graph.conversation = ConfirmedStudent()
    final = await graph.compile().ainvoke(
        {
            "messages": [HumanMessage(content="Please generate my full study plan.")],
            "raw_sols": project(case.text),
            "meta": {
                "degree_code": case.record.course_code,
                "year": case.commencement_year,
                "campus": case.campus,
                "majors": case.majors,
            },
            "meta_confirmed": True,
            "planning_requested": True,
            "conversation_mode": "planning",
        },
        {"recursion_limit": 80},
    )
    return final.get("plan") or ""
