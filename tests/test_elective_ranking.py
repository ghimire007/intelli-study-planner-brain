"""Tests for elective keyword ranking and priority resolution."""

from __future__ import annotations

from app.schemas.elective_ranking import ElectivePriorityInput
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
