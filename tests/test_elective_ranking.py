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
    get_elective_priorities,
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
