
"""Load elective pool configs and resolve allowed subject codes."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.prerequisite_parser import normalize_code

SCRAPED_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "seeds"
    / "scraped"
)

# Courseo's permitted elective levels.
ALLOWED_ELECTIVE_LEVELS = frozenset({100, 200, 300})


def subject_level(subject: dict) -> int | None:
    """Return the subject's numeric level, or None if unknown.

    Prefer explicit handbook metadata. Fall back to the numeric suffix
    of a conventional subject code, e.g. CSIT328 -> 300.
    """
    raw_level = subject.get("subject_level")

    if raw_level is not None:
        match = re.fullmatch(
            r"\s*(100|200|300|400|500|600|700|800|900)"
            r"\s*(?:-?\s*level|-?\s*lv)?\s*",
            str(raw_level),
            flags=re.IGNORECASE,
        )
        if match:
            return int(match.group(1))

        # Explicit but unrecognised metadata must not silently fall back
        # to a potentially conflicting code-derived level.
        if str(raw_level).strip():
            return None

    code = normalize_code(str(subject.get("code") or ""))
    match = re.fullmatch(r"[A-Z]{2,8}(\d{3,4})[A-Z]?", code)

    if not match:
        return None

    number = match.group(1)

    # For codes with a three-digit suffix, the first digit identifies
    # the level. For a four-digit suffix, use its first digit as well.
    level_digit = int(number[0])
    if level_digit == 0:
        return None

    return level_digit * 100


def load_elective_pools(course: str) -> dict:
    path = SCRAPED_DIR / f"elective_pools_{course}.json"

    if not path.exists():
        return {}

    return json.loads(path.read_text(encoding="utf-8"))


def _matches_prefixes(code: str, prefixes: list[str]) -> bool:
    norm = normalize_code(code)
    normalized_prefixes = [
        normalize_code(prefix)
        for prefix in prefixes
        if prefix
    ]
    return any(norm.startswith(prefix) for prefix in normalized_prefixes)


def _is_general_schedule(subject: dict) -> bool:
    tags = subject.get("tags") or []
    return any(
        str(tag).strip().casefold() == "general schedule"
        for tag in tags
    )


def resolve_pool_candidates(
    pool: dict,
    catalog: dict[str, dict],
    forbidden: set[str],
) -> set[str]:
    """Resolve a pool, allowing only 100-, 200-, or 300-level subjects.

    Subjects with missing or unrecognised levels are rejected.
    Pool configuration can narrow these levels, but cannot broaden them.
    """
    mode = pool.get("mode")
    candidates: set[str] = set()

    normalized_forbidden = {
        normalize_code(code)
        for code in forbidden
        if code
    }

    if mode == "named_list":
        source_codes = pool.get("codes") or []

        for code in source_codes:
            norm = normalize_code(str(code))
            if not norm or norm in normalized_forbidden:
                continue

            subject = catalog.get(norm)
            if subject is None:
                subject = next(
                    (
                        entry
                        for key, entry in catalog.items()
                        if normalize_code(key) == norm
                        or normalize_code(
                            str(entry.get("code") or "")
                        ) == norm
                    ),
                    None,
                )

            # A named list is not allowed to bypass level validation.
            if subject is None:
                continue

            if subject_level(subject) not in ALLOWED_ELECTIVE_LEVELS:
                continue

            candidates.add(norm)

        return candidates

    if mode not in {"open", "prefix_level"}:
        return candidates

    prefixes = pool.get("prefixes") or []
    include_general_schedule = bool(
        pool.get("include_general_schedule")
    )

    configured_levels: set[int] = set()
    for rule in pool.get("level_rules") or []:
        for level in rule.get("levels") or []:
            try:
                configured_levels.add(int(level))
            except (TypeError, ValueError):
                continue

    # Pool rules may narrow the allowed levels, never broaden them.
    allowed_levels = ALLOWED_ELECTIVE_LEVELS
    if configured_levels:
        allowed_levels = ALLOWED_ELECTIVE_LEVELS & configured_levels

    if not allowed_levels:
        return candidates

    for key, subject in catalog.items():
        code = normalize_code(
            str(subject.get("code") or key)
        )

        if not code or code in normalized_forbidden:
            continue

        level = subject_level(subject)

        if level not in allowed_levels:
            continue

        prefix_match = (
            not prefixes
            or _matches_prefixes(code, prefixes)
        )

        if not prefix_match:
            if not (
                include_general_schedule
                and _is_general_schedule(subject)
            ):
                continue
        elif not prefixes and include_general_schedule:
            if not _is_general_schedule(subject):
                continue

        candidates.add(code)

    return candidates
