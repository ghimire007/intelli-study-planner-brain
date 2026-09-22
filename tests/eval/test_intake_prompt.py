"""Unit tests for intake / unconfirmed metadata prompt assembly."""
from __future__ import annotations

from app.prompts.builder import build_system_prompt


class TestIntakeQuestion:
    def test_unconfirmed_prompt_allows_contextual_questions(self) -> None:
        """General questions should reach the advisor without a fixed intake response."""
        prompt = build_system_prompt(
            meta={"degree_code": None, "year": 2024, "campus": "Wollongong"},
            meta_confirmed=False,
            handbook=None,
            raw_sols="Year\tSession\tSubject Code\n2024\tAutumn\tCSIT110",
        )
        assert "actual message" in prompt
        assert "exactly one question" not in prompt
        assert "confirm_metadata_tool" in prompt
        assert "Do not assume a degree" in prompt

    def test_confirmed_prompt_includes_major(self) -> None:
        """Confirmed meta should surface major in the metadata note."""
        prompt = build_system_prompt(
            meta={
                "degree_code": "1807",
                "year": 2024,
                "campus": "Wollongong",
                "major": "Web Design and Development (MAJ40246)",
            },
            meta_confirmed=True,
            handbook="# 1807 handbook",
            raw_sols="sols",
        )
        assert "degree_code=1807" in prompt
        assert "Web Design and Development (MAJ40246)" in prompt
        assert "courses/2026/1807" in prompt
