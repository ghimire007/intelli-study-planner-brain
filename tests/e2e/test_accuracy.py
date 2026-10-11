"""Generate real study plans for the 766 records and grade them with the oracle.

    pytest tests/e2e --llm=gemini                      # all cases, one plan each
    pytest tests/e2e --llm=gemini -k bcs_25 --e2e-runs=3

Needs a migrated, seeded database (`make migrate-up seed`) and a GEMINI_API_KEY
in .env. A HARD rule failing on any run fails the case; a SOFT rule fails it
only when it breaks in more than half the runs. Known failures live in
baseline.json, so a prompt change fails CI only for what it newly breaks;
--e2e-update-baseline records the current failures there instead of failing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.services.course_rules import load_course_rules
from app.services.subject_catalog import load_subject_catalog

from tests.e2e import summary
from tests.e2e.cases import load_cases
from tests.e2e.harness import generate_plan
from tests.e2e.oracle import Violation, check_plan
from tests.e2e.plan import parse_plan

pytestmark = pytest.mark.eval

BASELINE = json.loads((Path(__file__).parent / "baseline.json").read_text())
CASES = load_cases()


def failing_rules(per_run: list[list[Violation]], known: set[str] = frozenset()) -> dict[str, str]:
    """Rule -> message for every rule these runs fail, other than the known ones."""
    failing = {}
    for rule in sorted({v.rule for run in per_run for v in run} - known):
        failures = [v for run in per_run for v in run if v.rule == rule]
        runs_failing = sum(any(v.rule == rule for v in run) for run in per_run)
        if failures[0].hard or runs_failing * 2 > len(per_run):
            failing[rule] = f"{rule} ({runs_failing}/{len(per_run)} runs): {failures[0].detail}"
    return failing


def newly_broken(case_id: str, per_run: list[list[Violation]]) -> list[str]:
    """Failures the baseline does not already excuse."""
    return list(failing_rules(per_run, set(BASELINE.get(case_id, []))).values())


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_plan_is_accurate(case, db, llm_config, runs, request) -> None:
    rules = load_course_rules(case.record.course_code, case.campus)
    catalog = load_subject_catalog(case.record.course_code)

    per_run: list[list[Violation]] = []
    for _ in range(runs):
        plan_text = await generate_plan(case, db, llm_config)
        violations = check_plan(case, rules, catalog, parse_plan(plan_text))
        summary.RUNS.append((case.id, violations))
        per_run.append(violations)

    if request.config.getoption("--e2e-update-baseline"):
        summary.NEW_BASELINE[case.id] = sorted(failing_rules(per_run))
        return

    assert not (broken := newly_broken(case.id, per_run)), "\n".join(broken)
