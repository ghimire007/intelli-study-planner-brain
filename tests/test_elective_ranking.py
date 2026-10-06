"""Tests for elective keyword ranking and priority resolution."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from app.agents.skills import get_elective_priorities_tool, ranked_elective_codes
from app.schemas.elective_ranking import (
    ElectivePoolPriorities,
    ElectivePriorityInput,
    ElectivePriorityResult,
    RankedElectiveOut,
)
from app.services.elective_pools import resolve_pool_candidates
from app.services.elective_ranking import (
    flatten_ranked_electives,
    get_elective_priorities,
    get_stage1_elective_list,
    keyword_overlap_score,
    rank_subjects_by_keywords,
)


def test_keyword_overlap_prefers_matching_subject() -> None:
    catalog = {
        "CSCI323": {
            "title": "Modern Artificial Intelligence",
            "description": "Advanced theories and algorithms in artificial intelligence.",
        },
        "ACCY111": {
            "title": "Accounting Fundamentals",
            "description": "Introduces accounting information in society.",
        },
    }
    ranked = rank_subjects_by_keywords(
        catalog,
        {"CSCI323", "ACCY111"},
        "artificial intelligence algorithms",
        limit=5,
    )
    assert ranked
    assert ranked[0][0] == "CSCI323"
    assert ranked[0][1] > 0


def test_keyword_overlap_score_zero_for_unrelated_query() -> None:
    subject = {"title": "Accounting", "description": "financial reports"}
    assert keyword_overlap_score(subject, "network security cryptography") == 0.0


def test_resolve_open_pool_includes_school_prefix_and_gs() -> None:
    catalog = {
        "CSIT999": {"code": "CSIT999", "tags": []},
        "ECON100": {"code": "ECON100", "tags": ["General Schedule"]},
        "CSIT110": {"code": "CSIT110", "tags": ["General Schedule"]},
    }
    pool = {
        "mode": "open",
        "prefixes": ["CSIT", "CSCI", "ISIT"],
        "include_general_schedule": True,
    }
    allowed = resolve_pool_candidates(pool, catalog, forbidden={"CSIT110"})
    assert "CSIT999" in allowed
    assert "ECON100" in allowed
    assert "CSIT110" not in allowed


def test_major_mode_returns_ranked_priorities_for_766() -> None:
    result = get_elective_priorities(
        ElectivePriorityInput(
            completed_subjects=[],
            planned_subjects=[],
            course="766",
            major="MAJ44204",
            session="Autumn",
            campus="Wollongong",
            mode="major",
            limit=10,
        )
    )
    assert result.mode == "major"
    assert len(result.pools) == 1
    # First-year Autumn: only a small elective-eligible set; ranking may be empty.
    assert result.pools[0].pool_id == "elective"


def test_agent_tool_returns_json_payload() -> None:
    payload = json.loads(
        get_elective_priorities_tool.invoke(
            {
                "course": "766",
                "campus": "Wollongong",
                "session": "Autumn",
                "mode": "interest",
                "completed_subjects": [],
                "planned_subjects": [],
                "interests": "artificial intelligence",
                "limit": 5,
            }
        )
    )
    assert payload["mode"] == "interest"
    assert "pools" in payload


def test_ranked_elective_codes_unique_in_pool_order() -> None:
    result = ElectivePriorityResult(
        mode="interest",
        pools=[
            ElectivePoolPriorities(
                pool_id="a",
                title="A",
                cp=6,
                priorities=[
                    RankedElectiveOut(code="CSCI323", title="AI", score=0.5),
                    RankedElectiveOut(code="CSIT302", title="Cyber", score=0.2),
                ],
            ),
            ElectivePoolPriorities(
                pool_id="b",
                title="B",
                cp=12,
                priorities=[
                    RankedElectiveOut(code="CSCI323", title="AI", score=0.5),
                    RankedElectiveOut(code="ISIT312", title="Web", score=0.1),
                ],
            ),
        ],
    )
    assert ranked_elective_codes(result) == ["CSCI323", "CSIT302", "ISIT312"]


async def test_lookup_ranked_electives_tool_includes_subject_cards() -> None:
    from app.agents.skills import make_lookup_ranked_electives_tool

    db = AsyncMock()
    tool = make_lookup_ranked_electives_tool(db)
    ranking = ElectivePriorityResult(
        mode="interest",
        pools=[
            ElectivePoolPriorities(
                pool_id="elective",
                title="Elective",
                cp=24,
                priorities=[
                    RankedElectiveOut(
                        code="CSCI323",
                        title="Modern Artificial Intelligence",
                        score=0.5,
                    )
                ],
            )
        ],
    )
    with (
        patch(
            "app.agents.skills.get_elective_priorities",
            return_value=ranking,
        ),
        patch(
            "app.agents.skills.fetch_subjects",
            new_callable=AsyncMock,
            return_value="# CSCI323\n\n6 CP",
        ) as fetch,
    ):
        payload = json.loads(
            await tool.ainvoke(
                {
                    "course": "766",
                    "campus": "Wollongong",
                    "session": "Autumn",
                    "mode": "interest",
                    "completed_subjects": [],
                    "planned_subjects": [],
                    "interests": "artificial intelligence",
                    "limit": 5,
                }
            )
        )
    fetch.assert_awaited_once()
    assert fetch.await_args.args[1] == ["CSCI323"]
    assert payload["mode"] == "interest"
    assert payload["pools"][0]["priorities"][0]["code"] == "CSCI323"
    assert "CSCI323" in payload["subject_cards"]
    assert payload["subjects"][0]["code"] == "CSCI323"
    assert "pre-requisites" in payload["subjects"][0]


def test_flatten_ranked_electives_unique_catalog_fields() -> None:
    ranking = ElectivePriorityResult(
        mode="interest",
        pools=[
            ElectivePoolPriorities(
                pool_id="elective",
                title="Elective",
                cp=24,
                priorities=[
                    RankedElectiveOut(code="CSCI323", title="AI", score=0.4),
                    RankedElectiveOut(code="MISSING99", title="Unknown", score=0.1),
                ],
            ),
            ElectivePoolPriorities(
                pool_id="elective_2",
                title="More",
                cp=6,
                priorities=[
                    RankedElectiveOut(code="CSCI323", title="AI", score=0.9),
                ],
            ),
        ],
    )
    catalog = {
        "CSCI323": {
            "code": "CSCI323",
            "title": "Modern Artificial Intelligence",
            "cp": "6",
            "prerequisites": ["CSCI203", "12cp at 200-level"],
            "corequisites": [],
            "offerings": [
                {"campus": "Wollongong", "session": "Autumn"},
                {"campus": "Wollongong", "session": "Spring"},
                {"campus": "Liverpool", "session": "Autumn"},
            ],
        }
    }
    result = flatten_ranked_electives(
        ranking,
        campus="Wollongong",
        session="Autumn",
        course="766",
        catalog=catalog,
    )
    dumped = result.model_dump(by_alias=True)
    codes = [row["code"] for row in dumped["subjects"]]
    assert codes == ["CSCI323", "MISSING99"]
    first = dumped["subjects"][0]
    assert first["title"] == "Modern Artificial Intelligence"
    assert first["name"] == first["title"]
    assert first["cp"] == 6
    assert first["credit_points"] == 6
    assert first["session"] == "Autumn"
    assert first["valid_sessions"] == "Autumn, Spring"
    assert first["pool_id"] == "elective"
    assert first["score"] == 0.9
    assert first["pre-requisites"] == "CSCI203; 12cp at 200-level"
    assert first["co-requisites"] == "None"
    missing = dumped["subjects"][1]
    assert missing["cp"] == 6
    assert missing["valid_sessions"] == "None"


def test_get_stage1_elective_list_shape_for_766() -> None:
    result = get_stage1_elective_list(
        ElectivePriorityInput(
            completed_subjects=[],
            planned_subjects=[],
            course="766",
            major="MAJ44204",
            session="Autumn",
            campus="Wollongong",
            mode="interest",
            interests="artificial intelligence",
            limit=5,
        )
    )
    payload = result.model_dump(by_alias=True)
    assert "subjects" in payload
    for row in payload["subjects"]:
        assert {"code", "title", "name", "cp", "credit_points", "campus", "session",
                "valid_sessions", "pool_id", "score", "pre-requisites", "co-requisites"} <= set(row)


def test_interest_mode_requires_interests_text() -> None:
    result = get_elective_priorities(
        ElectivePriorityInput(
            completed_subjects=[],
            planned_subjects=[],
            course="766",
            session="Autumn",
            campus="Wollongong",
            mode="interest",
            interests=None,
            limit=10,
        )
    )
    assert result.pools == []
