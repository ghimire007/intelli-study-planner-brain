"""Static UOW policy reference content, stored as one markdown file per topic
under app/knowledge/. Content changes rarely and is edited by developers, so
it's kept as code (git-diffable) rather than in a DB table with an admin UI.

Adding a new topic: drop a new .md file in app/knowledge/ and add its slug +
description to TOPICS below — that's the only other place that needs updating
(agents/skills.py reads TOPICS to build the tool's parameter schema).
"""
from pathlib import Path
from typing import NamedTuple

_KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"


class Topic(NamedTuple):
    slug: str
    description: str


TOPICS: list[Topic] = [
    Topic("course_transfer", "Eligibility, WAM guidance, fees, credit, and process for changing to a different UOW course/degree"),
    Topic("campus_transfer", "Transferring to a different UOW campus while staying in the same course"),
    Topic("course_progress", "Course progress rules (passing >50% of enrolled CP), what happens if a student falls behind, and where to get academic support"),
    Topic("credit_and_rpl", "Credit for Prior Learning (CPL) — getting credit/exemptions for previous formal, informal, or non-formal study/experience"),
    Topic("leaving_uow", "Withdrawing from UOW entirely, Leave of Absence, changing full-time/part-time study load, census date liabilities, and course lapsing"),
    Topic("subject_withdrawal", "Withdrawing from an individual subject (not the whole course) — deadlines, academic/financial penalties, compassionate circumstances, fee refunds"),
]

TOPIC_SLUGS: list[str] = [t.slug for t in TOPICS]


def load_topic(topic: str) -> str:
    if topic not in TOPIC_SLUGS:
        raise ValueError(f"Unknown knowledge topic: {topic!r}. Known topics: {TOPIC_SLUGS}")
    return (_KNOWLEDGE_DIR / f"{topic}.md").read_text()
