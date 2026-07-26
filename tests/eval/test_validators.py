"""
Unit tests for the Phase 3 deterministic validators
(`tests/eval/validators.py`).

Pure-function tests — no DB, no LLM. Synthetic `ScheduledSubject` rows and
inline markdown snippets are used as inputs so each validator can be
exercised in isolation. Marked `smoke` because they run in milliseconds and
are safe to include in the default suite.
"""
from __future__ import annotations

import pytest

from tests.eval.parser import ScheduledSubject
from tests.eval.validators import (
    CAPSTONE_CODE,
    CAPSTONE_TOTAL_CP,
    DEGREE_TOTAL_CP,
    SESSION_LOAD_CP,
    SESSION_LOAD_SUBJECTS,
    ValidationError,
    run_all,
    validate_csit321_cp_and_span,
    validate_no_historical_overlap,
    validate_no_invented_codes,
    validate_session_load_cap,
    validate_total_cp,
)


pytestmark = [pytest.mark.smoke]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(
    code: str,
    *,
    year: int = 2026,
    session: str = "Autumn",
    cp: int = 6,
) -> ScheduledSubject:
    return ScheduledSubject(
        year=year,
        session=session,
        subject_code=code,
        credit_points=cp,
    )


# ===========================================================================
# 3.1 — validate_no_invented_codes
# ===========================================================================

class TestValidateNoInventedCodes:
    HANDBOOK = "Valid codes: CSIT110 CSIT114 CSIT115 CSIT121 CSIT321"
    SOLS = "Student took CSIT123 CSIT127"

    def test_passes_when_every_code_is_in_handbook(self) -> None:
        reply = "I recommend CSIT110 and CSIT114."
        errors = validate_no_invented_codes(
            reply, handbook_md=self.HANDBOOK, sols_md=self.SOLS
        )
        assert errors == []

    def test_passes_when_code_is_only_in_sols(self) -> None:
        # Specified-credit codes (CSIT123/CSIT127) exist only in SOLS but are
        # still part of the whitelist.
        reply = "You already hold credit for CSIT123."
        errors = validate_no_invented_codes(
            reply, handbook_md=self.HANDBOOK, sols_md=self.SOLS
        )
        assert errors == []

    def test_flags_a_single_hallucinated_code(self) -> None:
        reply = "Enrol in CSIT999 next semester."
        errors = validate_no_invented_codes(
            reply, handbook_md=self.HANDBOOK, sols_md=self.SOLS
        )
        assert len(errors) == 1
        assert errors[0].rule == "no_invented_codes"
        assert "CSIT999" in errors[0].detail

    def test_flags_multiple_hallucinated_codes_in_one_error(self) -> None:
        reply = "Take CSIT110, CSIT999, and MATH999."
        errors = validate_no_invented_codes(
            reply, handbook_md=self.HANDBOOK, sols_md=self.SOLS
        )
        assert len(errors) == 1
        # Both invented codes appear in the detail, sorted for stability.
        assert "CSIT999" in errors[0].detail
        assert "MATH999" in errors[0].detail

    def test_passes_on_empty_reply(self) -> None:
        # No codes generated => nothing to flag.
        errors = validate_no_invented_codes(
            "", handbook_md=self.HANDBOOK, sols_md=self.SOLS
        )
        assert errors == []


# ===========================================================================
# 3.2a — validate_total_cp
# ===========================================================================

class TestValidateTotalCP:
    def test_passes_when_total_is_exactly_144(self) -> None:
        scheduled = [_row("CSIT110", cp=6)] * 20  # 120 planned
        errors = validate_total_cp(scheduled, completed_cp=24)
        assert errors == []

    def test_fails_when_total_is_under_144(self) -> None:
        scheduled = [_row("CSIT110", cp=6)]  # 6 planned
        errors = validate_total_cp(scheduled, completed_cp=100)  # 106 total
        assert len(errors) == 1
        assert errors[0].rule == "total_cp_equals_144"
        assert "106" in errors[0].detail
        assert str(DEGREE_TOTAL_CP) in errors[0].detail

    def test_fails_when_total_is_over_144(self) -> None:
        scheduled = [_row("CSIT110", cp=6)] * 25  # 150 planned
        errors = validate_total_cp(scheduled, completed_cp=0)
        assert len(errors) == 1
        assert "150" in errors[0].detail


# ===========================================================================
# 3.2b — validate_session_load_cap
# ===========================================================================

class TestValidateSessionLoadCap:
    def test_passes_for_well_loaded_plan(self) -> None:
        scheduled = [
            _row("CSIT110", year=2026, session="Autumn"),
            _row("CSIT114", year=2026, session="Autumn"),
            _row("CSIT115", year=2026, session="Autumn"),
            _row("CSIT128", year=2026, session="Autumn"),
            _row("CSIT121", year=2026, session="Spring"),
        ]
        assert validate_session_load_cap(scheduled) == []

    def test_passes_at_exact_subject_cap(self) -> None:
        scheduled = [_row(f"CSIT11{i}", year=2026) for i in range(SESSION_LOAD_SUBJECTS)]
        assert validate_session_load_cap(scheduled) == []

    def test_fails_when_session_has_five_subjects(self) -> None:
        scheduled = [_row(f"CSIT11{i}", year=2026) for i in range(SESSION_LOAD_SUBJECTS + 1)]
        errors = validate_session_load_cap(scheduled)
        assert len(errors) == 2  # 5 subjects breaches both subject cap AND CP cap (30 > 24)
        rules = {e.rule for e in errors}
        assert "session_load_subjects" in rules
        assert "session_load_cp" in rules

    def test_fails_only_on_cp_when_subjects_ok_but_cp_high(self) -> None:
        # 4 subjects but one is a 12-CP capstone Part-1 + 3 × 6 = 30 CP.
        scheduled = [
            _row("CSIT321", year=2026, cp=12),
            _row("CSIT314", year=2026, cp=6),
            _row("CSCI316", year=2026, cp=6),
            _row("CSCI323", year=2026, cp=6),
        ]
        errors = validate_session_load_cap(scheduled)
        assert len(errors) == 1
        assert errors[0].rule == "session_load_cp"

    def test_reports_each_breaching_session_separately(self) -> None:
        scheduled = (
            [_row(f"CSIT11{i}", year=2026, session="Autumn") for i in range(5)]
            + [_row(f"CSIT12{i}", year=2026, session="Spring") for i in range(5)]
        )
        errors = validate_session_load_cap(scheduled)
        # 2 sessions × 2 breach types = 4 errors
        assert len(errors) == 4
        autumn_errors = [e for e in errors if "Autumn" in e.detail]
        spring_errors = [e for e in errors if "Spring" in e.detail]
        assert len(autumn_errors) == 2
        assert len(spring_errors) == 2

    def test_passes_at_exact_cp_cap_with_four_subjects(self) -> None:
        # 4 × 6 CP = 24 CP exactly.
        scheduled = [_row(f"CSIT11{i}", year=2026, cp=6) for i in range(4)]
        assert validate_session_load_cap(scheduled) == []


# ===========================================================================
# 3.3 — validate_csit321_cp_and_span
# ===========================================================================

class TestValidateCsit321:
    def test_passes_when_capstone_absent(self) -> None:
        # Already complete in SOLS — not in plan, no constraint to assert.
        scheduled = [_row("CSIT110"), _row("CSIT114")]
        assert validate_csit321_cp_and_span(scheduled) == []

    def test_passes_for_canonical_layout(self) -> None:
        scheduled = [
            _row(CAPSTONE_CODE, year=2028, session="Autumn", cp=6),
            _row(CAPSTONE_CODE, year=2028, session="Spring", cp=6),
        ]
        assert validate_csit321_cp_and_span(scheduled) == []

    def test_fails_when_only_one_capstone_row(self) -> None:
        scheduled = [_row(CAPSTONE_CODE, year=2028, session="Autumn", cp=12)]
        errors = validate_csit321_cp_and_span(scheduled)
        rules = {e.rule for e in errors}
        assert "csit321_two_rows" in rules

    def test_fails_when_three_capstone_rows(self) -> None:
        scheduled = [
            _row(CAPSTONE_CODE, year=2028, session="Autumn", cp=4),
            _row(CAPSTONE_CODE, year=2028, session="Spring", cp=4),
            _row(CAPSTONE_CODE, year=2028, session="Autumn", cp=4),
        ]
        errors = validate_csit321_cp_and_span(scheduled)
        rules = {e.rule for e in errors}
        assert "csit321_two_rows" in rules

    def test_passes_for_spring_then_next_year_autumn(self) -> None:
        # Spring Y (Part 1) → Autumn Y+1 (Part 2): also "consecutive sessions"
        # in the UOW academic calendar, so should validate cleanly.
        scheduled = [
            _row(CAPSTONE_CODE, year=2027, session="Spring", cp=6),
            _row(CAPSTONE_CODE, year=2028, session="Autumn", cp=6),
        ]
        assert validate_csit321_cp_and_span(scheduled) == []

    def test_fails_when_autumn_then_next_year_spring_has_a_gap(self) -> None:
        # Autumn 2028 → Spring 2029 inserts a gap (Spring 2028 and Autumn 2029
        # both sit between them) so this layout is NOT consecutive.
        scheduled = [
            _row(CAPSTONE_CODE, year=2028, session="Autumn", cp=6),
            _row(CAPSTONE_CODE, year=2029, session="Spring", cp=6),
        ]
        errors = validate_csit321_cp_and_span(scheduled)
        rules = {e.rule for e in errors}
        assert "csit321_consecutive_sessions" in rules

    def test_fails_when_parts_are_in_reverse_chronological_order(self) -> None:
        # Spring 2028 cannot precede Autumn 2027 — that would be time travel.
        scheduled = [
            _row(CAPSTONE_CODE, year=2027, session="Autumn", cp=6),
            _row(CAPSTONE_CODE, year=2025, session="Spring", cp=6),
        ]
        errors = validate_csit321_cp_and_span(scheduled)
        rules = {e.rule for e in errors}
        assert "csit321_consecutive_sessions" in rules

    def test_fails_when_both_parts_in_autumn(self) -> None:
        scheduled = [
            _row(CAPSTONE_CODE, year=2028, session="Autumn", cp=6),
            _row(CAPSTONE_CODE, year=2028, session="Autumn", cp=6),
        ]
        errors = validate_csit321_cp_and_span(scheduled)
        rules = {e.rule for e in errors}
        assert "csit321_autumn_spring" in rules

    def test_fails_when_total_cp_is_not_12(self) -> None:
        # Two rows but cp sums to 14 (LLM emitted 8+6).
        scheduled = [
            _row(CAPSTONE_CODE, year=2028, session="Autumn", cp=8),
            _row(CAPSTONE_CODE, year=2028, session="Spring", cp=6),
        ]
        errors = validate_csit321_cp_and_span(scheduled)
        rules = {e.rule for e in errors}
        assert "csit321_total_cp" in rules
        assert any(str(CAPSTONE_TOTAL_CP) in e.detail for e in errors)


# ===========================================================================
# 3.4 — validate_no_historical_overlap
# ===========================================================================

class TestValidateNoHistoricalOverlap:
    def test_passes_when_no_overlap(self) -> None:
        scheduled = [_row("CSCI235"), _row("CSIT214")]
        errors = validate_no_historical_overlap(
            scheduled, completed_codes={"CSIT110", "CSIT114"}
        )
        assert errors == []

    def test_fails_when_a_passed_subject_is_re_scheduled(self) -> None:
        scheduled = [_row("CSIT110"), _row("CSCI235")]
        errors = validate_no_historical_overlap(
            scheduled, completed_codes={"CSIT110"}
        )
        assert len(errors) == 1
        assert errors[0].rule == "no_historical_overlap"
        assert "CSIT110" in errors[0].detail

    def test_fails_with_multiple_overlaps_in_one_error(self) -> None:
        scheduled = [_row("CSIT110"), _row("CSIT114"), _row("CSCI235")]
        errors = validate_no_historical_overlap(
            scheduled, completed_codes={"CSIT110", "CSIT114"}
        )
        assert len(errors) == 1
        assert "CSIT110" in errors[0].detail
        assert "CSIT114" in errors[0].detail

    def test_passes_for_empty_plan(self) -> None:
        errors = validate_no_historical_overlap(
            [], completed_codes={"CSIT110", "CSIT114"}
        )
        assert errors == []


# ===========================================================================
# Aggregator — run_all
# ===========================================================================

class TestRunAll:
    HANDBOOK = (
        "Handbook rules. Codes: CSIT110 CSIT114 CSIT115 CSIT121 CSIT128 "
        "CSIT123 CSIT127 CSIT214 CSIT226 CSIT302 CSIT314 CSIT321 "
        "CSCI235 CSCI251 CSCI203 CSCI316 CSCI323 ISIT219 ISIT312 "
        "MATH255 MATH221 CSCI262 CSCI369 CSIT375"  # extras for elective fillers
    )

    # A near-graduating student: 5 completed history rows + 2 specified
    # credits + 12 unspecified CP = 30+12+12 = 54 completed CP. Plan must
    # add 90 CP. The plan below totals exactly 90 CP and contains the
    # canonical Autumn+Spring CSIT321 layout.
    SOLS = """
| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |
|------|---------|-----------------|--------------|--------|------|-------|--------|
| 2025 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 95 | HD | Complete |
| 2025 | Autumn | Wollongong/On Campus | CSIT114 | 6 | 72 | C | Complete |
| 2025 | Autumn | Wollongong/On Campus | CSIT115 | 6 | 80 | D | Complete |
| 2025 | Autumn | Wollongong/On Campus | CSIT128 | 6 | 65 | C | Complete |
| 2025 | Spring | Wollongong/On Campus | CSIT121 | 6 | 70 | C | Complete |

| Course | Subject Code | Name | Level | Nom CP |
|--------|--------------|------|-------|--------|
| 766 | CSIT123 | Foundations | 1 | 6 |
| 766 | CSIT127 | Networks | 1 | 6 |

| Course | Level | Nom CP |
|--------|-------|--------|
| 766 | 1 | 12 |
"""

    GOOD_REPLY = (
        "**Study Plan:**\n\n"
        "| Year | Session | Subject Code | Subject Name | CP | Notes |\n"
        "|------|---------|-------------|-------------|-----|-------|\n"
        "(table content irrelevant — codes appear in this reply prose)\n"
    )

    GOOD_PLAN: list[ScheduledSubject] = [
        # 2026 Autumn — 4 subjects, 24 CP
        _row("CSCI235", year=2026, session="Autumn"),
        _row("CSIT214", year=2026, session="Autumn"),
        _row("CSIT302", year=2026, session="Autumn"),
        _row("ISIT219", year=2026, session="Autumn"),
        # 2026 Spring — 4 subjects, 24 CP
        _row("CSCI203", year=2026, session="Spring"),
        _row("CSCI251", year=2026, session="Spring"),
        _row("CSIT226", year=2026, session="Spring"),
        _row("ISIT312", year=2026, session="Spring"),
        # 2027 Autumn — 4 subjects (incl. capstone Part 1), 24 CP
        _row("CSIT321", year=2027, session="Autumn", cp=6),
        _row("CSIT314", year=2027, session="Autumn"),
        _row("CSCI316", year=2027, session="Autumn"),
        _row("CSCI323", year=2027, session="Autumn"),
        # 2027 Spring — capstone Part 2 + 2 electives, 18 CP
        _row("CSIT321", year=2027, session="Spring", cp=6),
        _row("CSIT123", year=2027, session="Spring"),  # placeholder — already in handbook
        _row("CSIT127", year=2027, session="Spring"),  # placeholder — already in handbook
    ]

    def test_good_plan_has_some_overlap_errors(self) -> None:
        # The synthetic GOOD_PLAN deliberately schedules CSIT123/CSIT127 which
        # are specified credits — so it should trigger 3.4 but pass 3.1/3.2/3.3.
        # This test pins that exact set of failures.
        # Build a reply that references every planned code so 3.1 sees a
        # superset of the planned codes.
        codes_in_reply = " ".join({r.subject_code for r in self.GOOD_PLAN})
        reply = self.GOOD_REPLY + " " + codes_in_reply
        errors = run_all(
            reply_text=reply,
            scheduled=self.GOOD_PLAN,
            sols_md=self.SOLS,
            handbook_md=self.HANDBOOK,
        )
        rules = sorted(e.rule for e in errors)
        # 3.4 fires for the CSIT123/CSIT127 specified-credit overlap.
        assert "no_historical_overlap" in rules
        # 3.1, 3.2a, 3.2b, 3.3 should all be clean for this plan.
        assert "no_invented_codes" not in rules
        assert "total_cp_equals_144" not in rules
        assert "csit321_two_rows" not in rules
        assert "csit321_autumn_spring" not in rules
        assert "csit321_total_cp" not in rules

    def test_clean_plan_produces_zero_errors(self) -> None:
        # Build a plan that should satisfy every Phase 3 rule:
        # - 90 CP planned + 54 CP completed = 144 (3.2a)
        # - ≤ 4 subjects and ≤ 24 CP per session (3.2b)
        # - Capstone: exactly 2 rows, same year, Autumn + Spring, sum 12 CP (3.3)
        # - No overlap with SOLS-completed codes (3.4)
        # - All planned codes appear in HANDBOOK (3.1)
        clean_plan = [
            # 2026 Autumn — 4 × 6 CP
            _row("CSCI235", year=2026, session="Autumn"),
            _row("CSIT214", year=2026, session="Autumn"),
            _row("CSIT302", year=2026, session="Autumn"),
            _row("ISIT219", year=2026, session="Autumn"),
            # 2026 Spring — 4 × 6 CP
            _row("CSCI203", year=2026, session="Spring"),
            _row("CSCI251", year=2026, session="Spring"),
            _row("CSIT226", year=2026, session="Spring"),
            _row("ISIT312", year=2026, session="Spring"),
            # 2027 Autumn — capstone Part 1 + 3 majors, 4 × 6 = 24 CP
            _row("CSIT321", year=2027, session="Autumn", cp=6),
            _row("CSIT314", year=2027, session="Autumn"),
            _row("CSCI316", year=2027, session="Autumn"),
            _row("CSCI323", year=2027, session="Autumn"),
            # 2027 Spring — capstone Part 2 + 2 fresh electives, 3 × 6 = 18 CP
            _row("CSIT321", year=2027, session="Spring", cp=6),
            _row("MATH255", year=2027, session="Spring"),
            _row("MATH221", year=2027, session="Spring"),
        ]
        # Planned total: 24 + 24 + 24 + 18 = 90 CP; + 54 completed = 144.
        codes_in_reply = " ".join({r.subject_code for r in clean_plan})
        reply = self.GOOD_REPLY + " " + codes_in_reply
        errors = run_all(
            reply_text=reply,
            scheduled=clean_plan,
            sols_md=self.SOLS,
            handbook_md=self.HANDBOOK,
        )
        assert errors == [], f"unexpected validator errors: {errors}"

    def test_compounded_breaches_each_reported(self) -> None:
        bad_plan = [
            # Hallucinated code, wrong capstone layout, oversized session.
            _row("CSIT999", year=2026, session="Autumn"),
            _row("CSIT321", year=2026, session="Autumn", cp=12),  # 1 row, 12 CP, wrong
            _row("CSIT110", year=2026, session="Autumn"),  # overlap (in SOLS Complete)
            _row("CSIT114", year=2026, session="Autumn"),  # overlap
            _row("CSIT115", year=2026, session="Autumn"),  # overlap
            _row("CSIT128", year=2026, session="Autumn"),  # overlap — also 6 subjects total
        ]
        reply = " ".join({r.subject_code for r in bad_plan})
        errors = run_all(
            reply_text=reply,
            scheduled=bad_plan,
            sols_md=self.SOLS,
            handbook_md=self.HANDBOOK,
        )
        rules = {e.rule for e in errors}
        assert "no_invented_codes" in rules         # CSIT999
        assert "csit321_two_rows" in rules           # only 1 capstone row
        assert "session_load_subjects" in rules      # 6 subjects in one session
        assert "session_load_cp" in rules            # > 24 CP in one session
        assert "no_historical_overlap" in rules      # 4 already-done subjects
        assert "total_cp_equals_144" in rules        # arithmetic doesn't line up
