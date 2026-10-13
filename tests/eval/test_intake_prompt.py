"""Unit tests for intake / unconfirmed metadata prompt assembly."""
from __future__ import annotations

from app.prompts.builder import INTAKE_QUESTION, build_system_prompt


class TestIntakeQuestion:
    def test_unconfirmed_prompt_requires_single_intake_question(self) -> None:
        """When meta is unconfirmed, the prompt must force the one intake question."""
        prompt = build_system_prompt(
            meta={"degree_code": None, "year": 2024, "campus": "Wollongong"},
            meta_confirmed=False,
            handbook=None,
            raw_sols="Year\tSession\tSubject Code\n2024\tAutumn\tCSIT110",
        )
        assert INTAKE_QUESTION in prompt
        assert "exactly one question" in prompt
        assert "confirm_metadata_tool" in prompt
        assert "do not assume course 766" in prompt.lower() or "Do not assume 766" in prompt

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
