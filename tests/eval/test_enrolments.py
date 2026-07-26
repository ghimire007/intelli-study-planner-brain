"""
Phase 1 smoke tests + Phase 4 statistical-stability sweep.

This module hosts two distinct test layers parametrized over the same 12
mock enrolment records:

- **Phase 1 (smoke)**   — fast, cost-free, runs with `--llm=fake`. Proves the
  harness boots end-to-end: every `.md` record is discoverable, loadable,
  and drivable through `ChatService.start_session(...)` without HTTP.

- **Phase 4 (eval)**    — slow, live-only, runs with `--llm=gemini`. Runs N
  iterations per profile (default 10, tunable via `--n-runs`), aggregates
  validator failures via `validators.run_all`, and asserts a per-profile
  pass-rate threshold defined in `PASS_RATE_THRESHOLDS`. Skipped under
  `--llm=fake` because the FakeLLM emits an intentionally invalid plan that
  would score 0% on every profile and yield no signal.

Run examples
------------
    python -m pytest tests/eval -v                       # fake LLM, fast
    python -m pytest tests/eval -v --llm=gemini          # full live sweep (slow + $$$)
    python -m pytest tests/eval -v --llm=gemini --n-runs=3  # quick live sweep
    python -m pytest tests/eval -v -m smoke              # smoke only
    python -m pytest tests/eval -v -m eval --llm=gemini  # eval only
"""
from __future__ import annotations

from collections import defaultdict

import pytest

from app.services.chat_service import ChatService
from tests.conftest import discover_test_records
from tests.eval.parser import (
    SUBJECT_CODE_PATTERN,
    extract_subject_codes,
    parse_study_plan_table,
)
from tests.eval.validators import ValidationError, run_all

try:
    from seeds.seed import HANDBOOK_766_2026_WOLLONGONG
except ImportError:  # pragma: no cover — seeds package always available in dev
    HANDBOOK_766_2026_WOLLONGONG = ""


# Collected at import time so pytest can use it for `parametrize` ids.
_RECORDS = discover_test_records()
_RECORD_IDS = [stem for stem, _ in _RECORDS]


pytestmark = [pytest.mark.eval]


# ---------------------------------------------------------------------------
# Pure harness sanity (no DB / no LLM)
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_records_discovered(test_records: list[tuple[str, str]]) -> None:
    assert test_records, "No .md records discovered in app/test_records/"
    assert len(test_records) >= 12, (
        f"Expected at least 12 records, found {len(test_records)}"
    )
    for stem, content in test_records:
        assert content.strip(), f"Empty record: {stem}.md"


@pytest.mark.smoke
@pytest.mark.parametrize("stem,content", _RECORDS, ids=_RECORD_IDS)
def test_record_contains_subject_codes(stem: str, content: str) -> None:
    """Every mock SOLS paste should mention at least one UOW subject code."""
    codes = extract_subject_codes(content)
    assert codes, f"No subject codes (pattern {SUBJECT_CODE_PATTERN.pattern}) in {stem}.md"


# ---------------------------------------------------------------------------
# Service-layer smoke: bypass HTTP and call ChatService directly
# ---------------------------------------------------------------------------

@pytest.mark.smoke
@pytest.mark.parametrize("stem,content", _RECORDS, ids=_RECORD_IDS)
async def test_start_session_smoke(
    stem: str,
    content: str,
    chat_service: ChatService,
) -> None:
    """
    Phase 1 contract: every mock enrolment produces a non-empty assistant
    reply with non-negative token accounting. This is intentionally weak; the
    Phase 4 sweep below replaces it with parser + validator assertions.
    """
    session, reply = await chat_service.start_session(content)

    assert session.id is not None, f"No session.id for {stem}"
    assert reply.content, f"Empty reply.content for {stem}"
    assert reply.role.value == "assistant", f"Wrong role for {stem}: {reply.role}"
    assert reply.tokens_in is not None and reply.tokens_in >= 0
    assert reply.tokens_out is not None and reply.tokens_out >= 0


# ---------------------------------------------------------------------------
# Phase 4: Statistical Stability & Loop Control
# ---------------------------------------------------------------------------

# Per-profile pass-rate thresholds (fraction of N iterations that must pass
# every Phase 3 validator). Tuned for record complexity:
#
# - Linear paths   (1.00 = 10/10): no advanced standing, no failures, no leave.
# - Mid-complexity (0.90 =  9/10): final-year planning, double-major.
# - Non-linear     (0.80 =  8/10): transfers, retakes, part-time, leave of absence.
#
# Records absent from this dict are skipped (e.g. `honours.md` is course 767
# with no seeded handbook — `start_session` raises `ValueError`).
PASS_RATE_THRESHOLDS: dict[str, float] = {
    # Linear / vanilla paths — strict
    "first_year_sem_1":                    1.00,
    "first_year_sem_2":                    1.00,
    "second_year_major":                   1.00,
    # Mid-complexity — high bar with some headroom for LLM variance
    "almost_graduated":                    0.90,
    "third_year_double_major":             0.80,
    # Transfers / advanced standing
    "international_transfer":              0.80,
    "mid_course_transfer_from_eng_to_cs":  0.80,
    "returning_after_leave":               0.80,
    "tafe_transfer":                       0.80,
    # Retakes / failed subjects
    "repeating_transfer":                  0.80,
    # Alternative load patterns
    "part_time":                           0.80,
    # honours: course 767 — handbook not seeded; excluded from the sweep.
}


@pytest.mark.eval
@pytest.mark.parametrize("stem,content", _RECORDS, ids=_RECORD_IDS)
async def test_pass_rate_threshold(
    require_live_llm,  # noqa: ARG001 — fixture skips on --llm=fake
    stem: str,
    content: str,
    chat_service: ChatService,
    request: pytest.FixtureRequest,
) -> None:
    """
    Phase 4: run each profile `--n-runs` times (default 10) against the live
    LLM, collect pass/fail per run via `validators.run_all`, then assert that
    the per-profile pass-rate meets the threshold defined in
    `PASS_RATE_THRESHOLDS`.

    Design note — why an internal loop instead of `@pytest.mark.repeat(N)`
    ---------------------------------------------------------------------
    `pytest-repeat` generates N independent test items, each of which passes
    or fails in isolation; pytest's exit code goes non-zero on the first
    failure. To gate on aggregate pass-rate ("≥ 80% of runs must pass") we
    need the N iterations to share state and produce a single verdict — that
    requires either an internal loop (this approach) or a session-scoped
    collector + sessionfinish hook (complex coordination, fragile state).
    The internal loop yields one row per profile in the pytest output and
    keeps each test independently re-runnable. `pytest-repeat` is still
    installed for ad-hoc per-iteration sweeps if needed.

    Profile selection
    -----------------
    Profiles absent from `PASS_RATE_THRESHOLDS` are skipped. Currently that's
    `honours.md` only (course 767, no seeded handbook).
    """
    if stem not in PASS_RATE_THRESHOLDS:
        pytest.skip(f"{stem!r} has no defined pass-rate threshold")

    threshold = PASS_RATE_THRESHOLDS[stem]
    n_runs: int = request.config.getoption("--n-runs")

    pass_count = 0
    rule_failures: dict[str, int] = defaultdict(int)

    for _ in range(n_runs):
        try:
            _session, reply = await chat_service.start_session(content)
            scheduled = parse_study_plan_table(reply.content)
            errors = run_all(
                reply_text=reply.content,
                scheduled=scheduled,
                sols_md=content,
                handbook_md=HANDBOOK_766_2026_WOLLONGONG,
            )
        except Exception as exc:  # noqa: BLE001 — capture any LLM/DB failure as a failed run
            errors = [
                ValidationError(
                    rule="iteration_exception",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            ]

        if not errors:
            pass_count += 1
        else:
            # De-dup rule names per iteration so one rule firing twice in a
            # single run only counts as one "iteration where rule X failed".
            for rule in {e.rule for e in errors}:
                rule_failures[rule] += 1

    actual_rate = pass_count / n_runs

    if actual_rate >= threshold:
        return

    summary = ", ".join(
        f"{rule}={count}/{n_runs}"
        for rule, count in sorted(rule_failures.items(), key=lambda kv: -kv[1])
    )
    pytest.fail(
        f"{stem}: pass-rate {pass_count}/{n_runs} = {actual_rate:.0%} "
        f"below threshold {threshold:.0%}. "
        f"Rule-failure counts (iterations flagging each rule): {summary}"
    )
