from pydantic import BaseModel, ConfigDict


class HandbookSummaryOut(BaseModel):
    course: str
    year: int
    campus: str
    title: str


class HandbookOut(HandbookSummaryOut):
    information: str


class CourseRulesOut(BaseModel):
    course: str
    campus: str
    year: int
    total_cp: int
    max_100_level_cp: int
    capstone_code: str
    capstone_cp: int
    core_subjects: list[str]
    core_selection: list[str]
    replacement_for: dict[str, str]
    major_core: dict[str, list[str]]
    elective_pools: list[dict]


class CatalogEntryOut(BaseModel):
    """A subject or major row from the scraped knowledge base."""
    model_config = ConfigDict(from_attributes=True)

    code: str
    year: int
    title: str
    credit_points: int
    url: str
    card: str
    data: dict


class PolicyTopicOut(BaseModel):
    slug: str
    description: str


class PolicyOut(PolicyTopicOut):
    content: str
