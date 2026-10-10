"""Per-rule results collected during a run and printed at the end of the session."""
from __future__ import annotations

from collections import defaultdict

from tests.e2e.oracle import Violation

RUNS: list[tuple[str, list[Violation]]] = []
NEW_BASELINE: dict[str, list[str]] = {}


def report() -> list[str]:
    failed: dict[str, int] = defaultdict(int)
    for _, violations in RUNS:
        for rule in {v.rule for v in violations}:
            failed[rule] += 1
    lines = [f"{len(RUNS)} generated plans, {sum(1 for _, v in RUNS if not v)} with no violations"]
    lines += [f"  {rule:<22} failed in {count}/{len(RUNS)} plans" for rule, count in sorted(failed.items())]
    return lines
