"""Load elective pool configs and resolve allowed subject codes."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.prerequisite_parser import normalize_code

SCRAPED_DIR = Path(__file__).resolve().parent.parent.parent / "seeds" / "scraped"


def load_elective_pools(course: str) -> dict:
    path = SCRAPED_DIR / f"elective_pools_{course}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _subject_level(subject: dict) -> int | None:
    level = (subject.get("subject_level") or "").strip()
    if level.endswith("-level") and level[:-6].isdigit():
        return int(level[:-6])
    code = subject.get("code") or ""
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) >= 3 and digits[-3].isdigit():
        return int(digits[-3]) * 100
    return None


def _matches_prefixes(code: str, prefixes: list[str]) -> bool:
    norm = normalize_code(code)
    return any(norm.startswith(prefix) for prefix in prefixes)


def _is_general_schedule(subject: dict) -> bool:
    return "General Schedule" in (subject.get("tags") or [])


def resolve_pool_candidates(
    pool: dict,
    catalog: dict[str, dict],
    forbidden: set[str],
) -> set[str]:
    """Return subject codes allowed by one elective pool definition."""
    mode = pool.get("mode")
    candidates: set[str] = set()

    if mode == "named_list":
        for code in pool.get("codes") or []:
            norm = normalize_code(code)
            if norm and norm not in forbidden:
                candidates.add(norm)
        return candidates

    if mode in {"open", "prefix_level"}:
        prefixes = pool.get("prefixes") or []
        include_gs = bool(pool.get("include_general_schedule"))
        allowed_levels: set[int] = set()
        for rule in pool.get("level_rules") or []:
            allowed_levels.update(rule.get("levels") or [])

        for code, subject in catalog.items():
            norm = normalize_code(subject.get("code") or code)
            if not norm or norm in forbidden:
                continue
            if prefixes and not _matches_prefixes(norm, prefixes):
                if not (include_gs and _is_general_schedule(subject)):
                    continue
            elif not prefixes and include_gs and not _is_general_schedule(subject):
                continue
            if allowed_levels:
                level = _subject_level(subject)
                if level is None or level not in allowed_levels:
                    continue
            candidates.add(norm)
        return candidates

    return candidates
