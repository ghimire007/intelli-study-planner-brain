"""
Unit tests for `app.services.sols_normalizer.normalize_sols_paste`.

Two layers of coverage:

1. Pure normalizer behaviour — idempotency on Markdown, transformation of
   tab-separated blocks, preservation of empty cells, handling of mixed
   prose/blank lines, edge cases.

2. End-to-end integration with `tests/eval/parser.py` — feed the
   normalizer's output back through `parse_sols_enrolment`, the
   completion helpers, and the hallucination whitelist, and verify the
   numbers come out exactly as if the student had pasted Markdown.

The realistic fixture is the user-provided clipboard payload that
prompted this module to exist: tab-separated, "Annual" capstone,
"Wollongong/ On Campus" with the post-slash space, blank Mark/Grade
cells on Enrolled rows, "NomCP" with no space.
"""
from __future__ import annotations

import pytest

from app.services.sols_normalizer import normalize_sols_paste
from tests.eval.parser import (
    all_completed_subject_codes,
    completed_subject_codes,
    extract_subject_codes,
    parse_sols_enrolment,
    total_completed_cp,
)

# ---------------------------------------------------------------------------
# Real-world fixture: the user-reported clipboard payload
# ---------------------------------------------------------------------------

# Exact bytes a student pastes after copying the SOLS Enrolment table.
# Tabs are explicit so the fixture survives any reflow / formatting.
USER_SOLS_PASTE = (
    "Year\tSession\tCampus/ Delivery\tSubject Code\tNomCP\tMark\tGrade\tStatus\n"
    "2026\tAnnual \tWollongong/ On Campus\tCSIT321\t12\t \t \tEnrolled\n"
    "2026\tAutumn \tWollongong/ On Campus\tCSIT314\t6\t \t \tEnrolled\n"
    "2026\tAutumn \tWollongong/ On Campus\tCSIT328\t6\t \t \tEnrolled\n"
    "2026\tAutumn \tWollongong/ On Campus\tISIT307\t6\t \t \tEnrolled\n"
    "2025\tAutumn \tWollongong/ On Campus\tCSIT213\t6\t92\tHD\tComplete\n"
    "2025\tAutumn \tWollongong/ On Campus\tCSIT214\t6\t80\tD\tComplete\n"
    "2025\tAutumn \tWollongong/ On Campus\tISIT219\t6\t85\tHD\tComplete\n"
    "2025\tAutumn \tWollongong/ On Campus\tMATH255\t6\t94\tHD\tComplete\n"
    "2025\tSpring \tWollongong/ On Campus\tCSIT305\t6\t72\tC\tComplete\n"
    "2025\tSpring \tWollongong/ On Campus\tCSIT377\t6\t89\tHD\tComplete\n"
    "2025\tSpring \tWollongong/ On Campus\tISIT207\t6\t80\tD\tComplete\n"
    "2025\tSpring \tWollongong/ On Campus\tISIT224\t6\t86\tHD\tComplete\n"
    "2024\tAutumn \tWollongong/ On Campus\tCSIT110\t6\t90\tHD\tComplete\n"
    "2024\tAutumn \tWollongong/ On Campus\tCSIT114\t6\t93\tHD\tComplete\n"
    "2024\tAutumn \tWollongong/ On Campus\tCSIT115\t6\t98\tHD\tComplete\n"
    "2024\tAutumn \tWollongong/ On Campus\tCSIT123\t6\t85\tHD\tComplete\n"
    "2024\tSpring \tWollongong/ On Campus\tCSIT121\t6\t86\tHD\tComplete\n"
    "2024\tSpring \tWollongong/ On Campus\tCSIT127\t6\t83\tD\tComplete\n"
    "2024\tSpring \tWollongong/ On Campus\tCSIT128\t6\t89\tHD\tComplete\n"
    "2024\tSpring \tWollongong/ On Campus\tCSIT226\t6\t85\tHD\tComplete\n"
)


# ---------------------------------------------------------------------------
# 1. Pure normalizer behaviour
# ---------------------------------------------------------------------------


class TestNormalizerIdempotency:
    """Markdown input must pass through unchanged."""

    def test_already_markdown_table_unchanged(self) -> None:
        md = (
            "| Year | Session | Subject Code | Nom CP | Mark | Grade | Status |\n"
            "|------|---------|--------------|--------|------|-------|--------|\n"
            "| 2024 | Autumn | CSIT110 | 6 | 90 | HD | Complete |\n"
        )
        assert normalize_sols_paste(md) == md

    def test_double_normalize_is_idempotent(self) -> None:
        once = normalize_sols_paste(USER_SOLS_PASTE)
        twice = normalize_sols_paste(once)
        assert once == twice

    def test_pure_prose_unchanged(self) -> None:
        prose = (
            "# Enrolment Record\n"
            "\n"
            "**Student:** Mr James WHITFIELD (9234501)\n"
            "**Course:** 766 — Bachelor of Computer Science\n"
        )
        assert normalize_sols_paste(prose) == prose

    def test_empty_string_returns_empty(self) -> None:
        assert normalize_sols_paste("") == ""

    def test_single_line_with_tabs_below_threshold_unchanged(self) -> None:
        # A line with only 1 tab is treated as prose, not a table row.
        line = "Hello\tworld"
        assert normalize_sols_paste(line) == line


class TestNormalizerTransform:
    """Tab-separated blocks become well-formed Markdown tables."""

    def test_user_paste_produces_pipe_delimited_output(self) -> None:
        out = normalize_sols_paste(USER_SOLS_PASTE)

        # Header row exists with pipes and the right columns
        assert (
            "| Year | Session | Campus/ Delivery | Subject Code | "
            "NomCP | Mark | Grade | Status |"
        ) in out

        # A divider row was injected
        assert "|---|---|---|---|---|---|---|---|" in out

        # A representative complete-row was rewritten
        assert "| 2024 | Autumn | Wollongong/ On Campus | CSIT110 | 6 | 90 | HD | Complete |" in out

    def test_blank_mark_and_grade_cells_preserved(self) -> None:
        # The Annual CSIT321 row has blank Mark and blank Grade.
        # After normalize, those two cells must be empty (not lost / merged).
        out = normalize_sols_paste(USER_SOLS_PASTE)
        # `| 12 |  |  | Enrolled |` — two consecutive empty cells.
        assert "| 2026 | Annual | Wollongong/ On Campus | CSIT321 | 12 |  |  | Enrolled |" in out

    def test_divider_column_count_matches_header(self) -> None:
        out = normalize_sols_paste(USER_SOLS_PASTE)
        lines = out.splitlines()
        header = lines[0]
        divider = lines[1]
        assert header.count("|") == divider.count("|")

    def test_only_one_divider_inserted_per_block(self) -> None:
        # Count divider *lines* (start with `|---`), not substring occurrences —
        # `|---|---|...` contains the substring `|---|` multiple times because
        # adjacent dividers share their boundary pipes.
        out = normalize_sols_paste(USER_SOLS_PASTE)
        divider_lines = [l for l in out.splitlines() if l.startswith("|---")]
        assert len(divider_lines) == 1


class TestNormalizerBoundaries:
    """Block detection: blank lines and prose terminate a block correctly."""

    def test_blank_line_terminates_block(self) -> None:
        text = (
            "Year\tSession\tCode\n"
            "2024\tAutumn\tCSIT110\n"
            "\n"
            "Some prose that should pass through.\n"
        )
        out = normalize_sols_paste(text)
        lines = out.splitlines()
        # First three lines are header + divider + one data row
        assert lines[0].startswith("| Year ")
        assert lines[1].startswith("|---")
        assert lines[2].startswith("| 2024 ")
        # Blank line preserved
        assert lines[3] == ""
        # Prose preserved verbatim
        assert lines[4] == "Some prose that should pass through."

    def test_prose_between_two_tab_blocks_keeps_both(self) -> None:
        text = (
            "Year\tSession\tCode\n"
            "2024\tAutumn\tCSIT110\n"
            "\n"
            "## Specified Credit\n"
            "\n"
            "Course\tSubject Code\tName\tLevel\tNom CP\n"
            "ENG/3\tCSIT110\tFoundations\t1\t6\n"
        )
        out = normalize_sols_paste(text)
        # Two distinct divider *lines*, one per block (counted by line prefix
        # to avoid the shared-boundary substring overlap problem).
        divider_lines = [l for l in out.splitlines() if l.startswith("|---")]
        assert len(divider_lines) == 2
        # Prose heading still there
        assert "## Specified Credit" in out

    def test_mixed_markdown_and_tab_blocks_in_same_input(self) -> None:
        text = (
            "| Year | Session | Code |\n"
            "|------|---------|------|\n"
            "| 2024 | Autumn | CSIT110 |\n"
            "\n"
            "Year\tSession\tCode\n"
            "2025\tAutumn\tCSIT214\n"
        )
        out = normalize_sols_paste(text)
        # Original Markdown block untouched
        assert "| Year | Session | Code |\n|------|---------|------|" in out
        # Tab block converted
        assert "| 2025 | Autumn | CSIT214 |" in out


# ---------------------------------------------------------------------------
# 2. End-to-end: normalized output feeds parser + helpers cleanly
# ---------------------------------------------------------------------------


class TestNormalizedPasteFlowsThroughParser:
    """
    The whole point of the normalizer: after one call, the existing SOLS
    parsers and completion helpers must produce identical numbers to what
    they'd produce on a hand-written Markdown record.
    """

    @pytest.fixture
    def normalized(self) -> str:
        return normalize_sols_paste(USER_SOLS_PASTE)

    def test_parse_sols_enrolment_yields_all_20_rows(self, normalized: str) -> None:
        rows = parse_sols_enrolment(normalized)
        assert len(rows) == 20

    def test_first_row_is_csit321_annual_enrolled(self, normalized: str) -> None:
        rows = parse_sols_enrolment(normalized)
        first = rows[0]
        assert first.year == 2026
        assert first.session == "Annual"
        assert first.subject_code == "CSIT321"
        assert first.nom_cp == 12
        assert first.mark is None  # blank cell preserved
        assert first.grade is None
        assert first.status == "Enrolled"

    def test_completed_codes_excludes_enrolled_subjects(self, normalized: str) -> None:
        rows = parse_sols_enrolment(normalized)
        completed = completed_subject_codes(rows)
        # 4 of the 20 rows are Enrolled (2026 entries); 16 are Complete with HD/D/C grades.
        assert len(completed) == 16
        # CSIT321 is currently Enrolled, not Complete → must NOT be in the set.
        assert "CSIT321" not in completed
        # CSIT110 was completed with HD → must be in the set.
        assert "CSIT110" in completed

    def test_total_completed_cp_sums_to_96(self, normalized: str) -> None:
        # 16 Complete rows × 6 CP each = 96 CP.
        assert total_completed_cp(normalized) == 96

    def test_all_completed_codes_match_completed_codes_when_no_specified(
        self, normalized: str
    ) -> None:
        # User's paste has no Specified Credit section, so the union
        # collapses to just the history-side completions.
        rows = parse_sols_enrolment(normalized)
        assert all_completed_subject_codes(normalized) == completed_subject_codes(rows)

    def test_extract_subject_codes_finds_all_20_unique_codes(self, normalized: str) -> None:
        # 20 rows, each with a distinct code.
        codes = extract_subject_codes(normalized)
        assert len(codes) == 20
        assert "CSIT321" in codes
        assert "MATH255" in codes


class TestParserFailsWithoutNormalization:
    """
    Regression guard: without the normalizer, the existing SOLS parsers
    return nothing on the user's raw tab paste. If anyone removes the
    normalize_sols_paste() call in ChatService, these tests document why
    that's a bad idea.
    """

    def test_raw_tab_paste_yields_no_enrolment_rows(self) -> None:
        # Header is tab-separated → no `|` pipes → header anchor misses.
        assert parse_sols_enrolment(USER_SOLS_PASTE) == []

    def test_raw_tab_paste_completed_cp_is_zero(self) -> None:
        # No parsed rows → completion helpers see nothing complete.
        assert total_completed_cp(USER_SOLS_PASTE) == 0

    def test_raw_tab_paste_subject_codes_still_found(self) -> None:
        # Phase 2.1 is regex-based and format-agnostic, so codes
        # survive even on the raw paste. This is the one bit that
        # keeps working without the normalizer.
        codes = extract_subject_codes(USER_SOLS_PASTE)
        assert len(codes) == 20
