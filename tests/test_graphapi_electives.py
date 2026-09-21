"""graphAPI Stage-1 electives vs the deterministic elective service."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.graphAPI import (
    extract_and_parse_json,
    sols_codes_for_ranking,
    stage1_electives_from_advisor_state,
)

pytestmark = pytest.mark.smoke

RECORD = Path(__file__).resolve().parents[1] / "app" / "test_records" / "almost_graduated.md"


def test_sols_codes_split_complete_and_enrolled() -> None:
    completed, planned = sols_codes_for_ranking(RECORD.read_text())
    assert "CSIT110" in completed
    assert "CSCI323" in planned
    assert "CSIT321" in planned
    assert "CSIT110" not in planned


def test_stage1_electives_json_is_eval_shape() -> None:
    raw = RECORD.read_text()
    payload = json.loads(
        stage1_electives_from_advisor_state(
            {
                "raw_sols": raw,
                "meta": {
                    "degree_code": "766",
                    "campus": "Wollongong",
                    "session": "Spring",
                    "major": "AIBD — Artificial Intelligence and Big Data",
                },
            }
        )
    )
    assert "subjects" in payload
    required = {
        "code",
        "title",
        "name",
        "cp",
        "credit_points",
        "campus",
        "session",
        "valid_sessions",
        "pool_id",
        "score",
        "pre-requisites",
        "co-requisites",
    }
    enrolled = set(sols_codes_for_ranking(raw)[1])
    for row in payload["subjects"]:
        assert required <= set(row)
        assert row["code"] not in enrolled
        assert row["session"] == "Spring"
        assert row["campus"] == "Wollongong"


def test_extract_and_parse_roundtrip_matches_service() -> None:
    raw_json = stage1_electives_from_advisor_state(
        {
            "raw_sols": RECORD.read_text(),
            "meta": {
                "degree_code": "766",
                "campus": "Wollongong",
                "session": "Spring",
                "major": "AIBD",
            },
        }
    )
    parsed = extract_and_parse_json(raw_json)
    assert isinstance(parsed, dict)
    assert parsed.get("subjects") is not None
