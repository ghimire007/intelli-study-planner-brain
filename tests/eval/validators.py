"""
Deterministic rule validators for the UOW Course 766 study plan (Phase 3).

Each validator is a pure function that consumes the parsed Phase 2 output
plus pre-computed SOLS context, and returns a `list[ValidationError]` —
empty list means the plan satisfies that rule. The uniform list return type
lets `run_all` flatten with a single spread expression and keeps every
validator independently unit-testable.

Phase 3 spec coverage
---------------------
| §    | Function                          | Rule source (seeds/seed.py)          |
|------|-----------------------------------|--------------------------------------|
| 3.1  | validate_no_invented_codes        | Global Rules: no invented codes      |
| 3.2a | validate_total_cp                 | Global Rules: 144 CP total           |
| 3.2b | validate_session_load_cap         | Stage 2.5: ≤4 subjects, ≤24 CP / sess|
| 3.3  | validate_csit321_cp_and_span      | Capstone scheduling rules            |
| 3.4  | validate_no_historical_overlap    | "Do not re-recommend completed"      |

Deferred (not in Phase 3 spec; stubs intentionally absent):
- validate_prerequisites          — needs prerequisite graph extraction
- validate_session_availability   — needs Autumn/Spring availability map
- validate_max_100_level_cp       — needs level extraction from codes
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.services.sols_normalizer import normalize_sols_paste
from tests.eval.parser import (
    ScheduledSubject,
    all_completed_subject_codes,
    extract_subject_codes,
    total_completed_cp,
)


# ===========================================================================
# Error shape
# ===========================================================================

@dataclass
class ValidationError:
    rule: str          # short stable identifier, e.g. "total_cp_equals_144"
    detail: str        # human-readable failure description


# ===========================================================================
# Constants — all sourced from the seeded 766/2026/Wollongong handbook
# ===========================================================================

CAPSTONE_CODE = "CSIT321"
CAPSTONE_TOTAL_CP = 12        # handbook §Global Rules + §Capstone
DEGREE_TOTAL_CP = 144         # handbook §Global Rules
SESSION_LOAD_SUBJECTS = 4     # handbook §Stage 2.5
SESSION_LOAD_CP = 24          # implied: 4 subjects × 6 CP


# ===========================================================================
# 3.1 — Hallucination Guard (Whitelist Matching)
# ===========================================================================

def validate_no_invented_codes(
    reply_text: str,
    *,
    handbook_md: str,
    sols_md: str,
) -> list[ValidationError]:
    """
    Phase 3.1: every UOW subject code in the LLM's reply must appear in the
    union of (handbook codes) ∪ (SOLS codes). Any code outside that whitelist
    is reported as a hallucination.

        generated  = extract_subject_codes(reply_text)
        whitelist  = extract_subject_codes(handbook_md) | extract_subject_codes(sols_md)
        invented   = generated - whitelist
    """
    generated = extract_subject_codes(reply_text)
    whitelist = extract_subject_codes(handbook_md) | extract_subject_codes(sols_md)
    invented = generated - whitelist
    if not invented:
        return []
    return [
        ValidationError(
            rule="no_invented_codes",
            detail=(
                f"Hallucinated subject codes (not in handbook ∪ SOLS): "
                f"{sorted(invented)}"
            ),
        )
    ]


# ===========================================================================
# 3.2a — Degree Completion Cap
# ===========================================================================

def validate_total_cp(
    scheduled: list[ScheduledSubject],
    *,
    completed_cp: int,
) -> list[ValidationError]:
    """
    Phase 3.2a: sum of planned CP plus historical complete CP must equal 144.

        planned + completed == 144
    """
    planned_cp = sum(row.credit_points for row in scheduled)
    total = planned_cp + completed_cp
    if total == DEGREE_TOTAL_CP:
        return []
    return [
        ValidationError(
            rule="total_cp_equals_144",
            detail=(
                f"Total CP = {total} (planned={planned_cp}, completed={completed_cp}); "
                f"expected exactly {DEGREE_TOTAL_CP}."
            ),
        )
    ]


# ===========================================================================
# 3.2b — Session Load Limiter
# ===========================================================================

def validate_session_load_cap(
    scheduled: list[ScheduledSubject],
) -> list[ValidationError]:
    """
    Phase 3.2b: per `(year, session)`, the plan must contain at most
    4 subjects AND at most 24 CP. Reports each breaching session separately.
    """
    groups: dict[tuple[int, str], list[ScheduledSubject]] = defaultdict(list)
    for row in scheduled:
        groups[(row.year, row.session)].append(row)

    errors: list[ValidationError] = []
    for (year, session), rows in sorted(groups.items()):
        if len(rows) > SESSION_LOAD_SUBJECTS:
            errors.append(
                ValidationError(
                    rule="session_load_subjects",
                    detail=(
                        f"{year} {session}: {len(rows)} subjects scheduled "
                        f"({[r.subject_code for r in rows]}); cap is "
                        f"{SESSION_LOAD_SUBJECTS}."
                    ),
                )
            )
        session_cp = sum(r.credit_points for r in rows)
        if session_cp > SESSION_LOAD_CP:
            errors.append(
                ValidationError(
                    rule="session_load_cp",
                    detail=(
                        f"{year} {session}: {session_cp} CP scheduled; cap "
                        f"is {SESSION_LOAD_CP}."
                    ),
                )
            )
    return errors


# ===========================================================================
# 3.3 — CSIT321 Capstone Execution
# ===========================================================================

def validate_csit321_cp_and_span(
    scheduled: list[ScheduledSubject],
) -> list[ValidationError]:
    """
    Phase 3.3: if CSIT321 appears in the plan, enforce
    - exactly 2 occurrences,
    - one Autumn (Part 1) + one Spring (Part 2),
    - the two parts are in *consecutive* sessions with no gap,
    - total CP across both rows == 12.

    Two layouts are accepted as "consecutive":
    - **Same-year Autumn → Spring**: Autumn Y (Part 1) + Spring Y (Part 2).
      Documented in the seeded handbook.
    - **Spring → next-year Autumn**: Spring Y (Part 1) + Autumn Y+1 (Part 2).
      Allowed by real-world UOW policy (no session sits between Spring Y
      and Autumn Y+1 in the academic calendar).

    Any other layout — wrong sessions, gap > 0, going backwards in time, or
    the two rows >1 year apart — is flagged as `csit321_consecutive_sessions`.

    If CSIT321 doesn't appear at all (e.g. already complete in SOLS), the
    validator returns no errors — there's no constraint to assert.
    """
    capstone_rows = [r for r in scheduled if r.subject_code == CAPSTONE_CODE]
    if not capstone_rows:
        return []

    errors: list[ValidationError] = []

    if len(capstone_rows) != 2:
        errors.append(
            ValidationError(
                rule="csit321_two_rows",
                detail=(
                    f"CSIT321 appears in {len(capstone_rows)} row(s); "
                    f"expected exactly 2 (Part 1 + Part 2)."
                ),
            )
        )

    # The session + consecutive-pair checks only make sense for exactly 2 rows.
    if len(capstone_rows) == 2:
        sessions_set = {r.session for r in capstone_rows}
        if sessions_set != {"Autumn", "Spring"}:
            errors.append(
                ValidationError(
                    rule="csit321_autumn_spring",
                    detail=(
                        f"CSIT321 sessions = {sorted(r.session for r in capstone_rows)}; "
                        f"expected one 'Autumn' and one 'Spring'."
                    ),
                )
            )
        else:
            autumn_row = next(r for r in capstone_rows if r.session == "Autumn")
            spring_row = next(r for r in capstone_rows if r.session == "Spring")

            same_year_autumn_first = autumn_row.year == spring_row.year
            spring_then_autumn = spring_row.year + 1 == autumn_row.year

            if not (same_year_autumn_first or spring_then_autumn):
                errors.append(
                    ValidationError(
                        rule="csit321_consecutive_sessions",
                        detail=(
                            f"CSIT321 parts are not in consecutive sessions: "
                            f"Autumn {autumn_row.year} + Spring {spring_row.year}. "
                            f"Valid layouts: same-year Autumn → Spring, or "
                            f"Spring Y → Autumn Y+1."
                        ),
                    )
                )

    total_cp = sum(r.credit_points for r in capstone_rows)
    if total_cp != CAPSTONE_TOTAL_CP:
        errors.append(
            ValidationError(
                rule="csit321_total_cp",
                detail=(
                    f"CSIT321 total CP across all rows = {total_cp}; "
                    f"expected {CAPSTONE_TOTAL_CP}."
                ),
            )
        )

    return errors


# ===========================================================================
# 3.4 — Historical Overlap Check (Duplicate Guard)
# ===========================================================================

def validate_no_historical_overlap(
    scheduled: list[ScheduledSubject],
    *,
    completed_codes: set[str],
) -> list[ValidationError]:
    """
    Phase 3.4: no subject already completed with a passing grade (or held as
    Specified Credit) in the student's SOLS may be re-scheduled in the future
    plan. `completed_codes` should be the union of:
    - codes from enrolment-history rows where `is_complete(row)`, and
    - codes from every row in the Specified Credit table.

    The caller normally produces this via
    `parser.all_completed_subject_codes(sols_md)`.
    """
    planned_codes = {r.subject_code for r in scheduled}
    redundant = planned_codes & completed_codes
    if not redundant:
        return []
    return [
        ValidationError(
            rule="no_historical_overlap",
            detail=(
                f"Subject(s) already completed with a passing grade are "
                f"re-scheduled in the plan: {sorted(redundant)}"
            ),
        )
    ]


# ===========================================================================
# Aggregator
# ===========================================================================

def run_all(
    *,
    reply_text: str,
    scheduled: list[ScheduledSubject],
    sols_md: str,
    handbook_md: str,
) -> list[ValidationError]:
    """
    Run every Phase 3 validator and return the flattened list of failures.
    Empty list = the plan satisfies every deterministic rule implemented so
    far.

    All SOLS-side derivations (`completed_codes`, `completed_cp`) are computed
    once here and threaded into the individual validators — keeps each
    validator a pure function over its declared inputs.

    `sols_md` is normalized via `normalize_sols_paste` so the validator
    pipeline tolerates the tab-separated clipboard format the SOLS web UI
    produces. Normalization is idempotent on Markdown input — the existing
    `.md` test fixtures are unaffected. This normalization deliberately
    lives here (not at `ChatService` ingress) so production LLM calls don't
    pay the ~240-token framing overhead on every chat start.
    """
    sols_md = normalize_sols_paste(sols_md)
    completed_codes = all_completed_subject_codes(sols_md)
    completed_cp = total_completed_cp(sols_md)

    return [
        *validate_no_invented_codes(
            reply_text, handbook_md=handbook_md, sols_md=sols_md
        ),
        *validate_total_cp(scheduled, completed_cp=completed_cp),
        *validate_session_load_cap(scheduled),
        *validate_csit321_cp_and_span(scheduled),
        *validate_no_historical_overlap(
            scheduled, completed_codes=completed_codes
        ),
    ]
