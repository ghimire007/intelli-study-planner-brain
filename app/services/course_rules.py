"""Load structured course rules from scraped CourseLoop JSON + small overrides."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SEEDS_DIR = Path(__file__).resolve().parents[2] / "seeds"
SCRAPED_DIR = SEEDS_DIR / "scraped"
OVERRIDES_DIR = SEEDS_DIR / "overrides"

_MAX_100_LEVEL_RE = re.compile(
    r"maximum of (\d+) credit points.*100 level",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CourseRules:
    course: str
    campus: str
    year: int
    total_cp: int
    max_100_level_cp: int
    capstone_code: str
    capstone_cp: int
    core_subjects: frozenset[str]
    core_selection: frozenset[str]
    replacement_for: dict[str, str]
    satisfies: dict[str, frozenset[str]]
    major_core: dict[str, frozenset[str]]
    major_aliases: dict[str, str]


def _normalize_code(code: str) -> str:
    return code.upper().replace(" ", "")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_overrides(course: str) -> dict:
    path = OVERRIDES_DIR / f"course_{course}.json"
    if not path.exists():
        return {}
    return _load_json(path)


def _invert_equivalencies(equivalencies: dict[str, str]) -> dict[str, frozenset[str]]:
    satisfies: dict[str, set[str]] = {}
    for alternate, base in equivalencies.items():
        satisfies.setdefault(_normalize_code(base), set()).add(_normalize_code(alternate))
    return {base: frozenset(alts) for base, alts in satisfies.items()}


def _walk_nodes(node: dict):
    yield node
    for child in node.get("children") or []:
        yield from _walk_nodes(child)


def _campus_matches(title: str, campus: str) -> bool:
    return campus.strip().lower() in title.strip().lower()


def _preferred_campus_title(campus: str) -> str | None:
    campus_l = campus.strip().lower()
    preferred = {
        "wollongong": "Bachelor of Computer Science at Wollongong Campus",
        "singapore institute of management": (
            "Bachelor of Computer Science at Singapore Institute of Management, Singapore"
        ),
        "liverpool": "Bachelor of Computer Science at Liverpool Campus",
    }
    return preferred.get(campus_l)


def _collect_campus_nodes(structure: list[dict]) -> list[dict]:
    nodes: list[dict] = []
    for node in structure:
        nodes.append(node)
        nodes.extend(node.get("children") or [])
    return nodes


def _find_campus_root(structure: list[dict], campus: str) -> dict | None:
    nodes = _collect_campus_nodes(structure)
    preferred_title = _preferred_campus_title(campus)
    if preferred_title:
        for node in nodes:
            if (node.get("title") or "").strip() == preferred_title:
                return node

    candidates = [node for node in nodes if _campus_matches(node.get("title") or "", campus)]
    if not candidates:
        return None

    for node in candidates:
        title = (node.get("title") or "").lower()
        if "honours" in title or "top up" in title or "admitted" in title:
            continue
        return node
    return candidates[0]


def _section_title(node: dict) -> str:
    return (node.get("title") or "").strip().lower()


def _find_section(campus_root: dict, section: str) -> dict | None:
    for node in _walk_nodes(campus_root):
        title = _section_title(node)
        if section == "core selection":
            if "core selection" in title:
                return node
        elif section == "core":
            if "core" in title and "core selection" not in title:
                return node
        elif section == "capstone":
            if "capstone" in title:
                return node
    return None


def _item_codes(section: dict | None) -> list[str]:
    if section is None:
        return []
    return [
        item["code"]
        for item in section.get("items") or []
        if item.get("code") and not str(item["code"]).startswith("MAJ")
    ]


def _parse_max_100_level_cp(campus_root: dict) -> int:
    for node in _walk_nodes(campus_root):
        description = node.get("description") or ""
        match = _MAX_100_LEVEL_RE.search(description)
        if match:
            return int(match.group(1))
    return 60


def _major_core_from_scraped(majors_data: dict) -> dict[str, frozenset[str]]:
    major_core: dict[str, set[str]] = {}
    for code, major in majors_data.items():
        subjects: set[str] = set()
        for container in major.get("structure") or []:
            for item in container.get("items") or []:
                item_code = item.get("code")
                if item_code and not str(item_code).startswith("MAJ"):
                    subjects.add(_normalize_code(item_code))
        if subjects:
            major_core[_normalize_code(code)] = subjects
    return {code: frozenset(subjects) for code, subjects in major_core.items()}


def _major_aliases(majors_data: dict, overrides: dict) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for code, major in majors_data.items():
        norm_code = _normalize_code(code)
        title = (major.get("title") or "").strip().lower()
        if title:
            aliases[title] = norm_code
    for alias, code in (overrides.get("major_aliases") or {}).items():
        aliases[alias.strip().lower()] = _normalize_code(code)
    return aliases


@lru_cache
def load_course_rules(course: str, campus: str = "Wollongong") -> CourseRules:
    """Load course rules for *course* at *campus* from scraped JSON + overrides."""
    course_path = SCRAPED_DIR / f"course_{course}.json"
    majors_path = SCRAPED_DIR / f"majors_{course}.json"
    if not course_path.exists():
        raise FileNotFoundError(f"Missing scraped course file: {course_path}")

    course_data = _load_json(course_path)
    majors_data = _load_json(majors_path) if majors_path.exists() else {}
    overrides = _load_overrides(course)

    campus_root = _find_campus_root(course_data.get("structure") or [], campus)
    if campus_root is None:
        raise ValueError(f"Campus {campus!r} not found in course_{course}.json")

    core_section = _find_section(campus_root, "core")
    core_selection_section = _find_section(campus_root, "core selection")
    capstone_section = _find_section(campus_root, "capstone")

    capstone_items = capstone_section.get("items") if capstone_section else []
    capstone_code = capstone_items[0]["code"] if capstone_items else "CSIT321"
    capstone_cp = int(capstone_items[0].get("cp") or 12) if capstone_items else 12

    equivalencies = {
        _normalize_code(k): _normalize_code(v)
        for k, v in (overrides.get("equivalencies") or {}).items()
    }

    return CourseRules(
        course=str(course_data.get("code") or course),
        campus=campus,
        year=int(course_data.get("year") or 2026),
        total_cp=int(course_data.get("cp") or 144),
        max_100_level_cp=_parse_max_100_level_cp(campus_root),
        capstone_code=_normalize_code(capstone_code),
        capstone_cp=capstone_cp,
        core_subjects=frozenset(_normalize_code(c) for c in _item_codes(core_section)),
        core_selection=frozenset(_normalize_code(c) for c in _item_codes(core_selection_section)),
        replacement_for=equivalencies,
        satisfies=_invert_equivalencies(equivalencies),
        major_core=_major_core_from_scraped(majors_data),
        major_aliases=_major_aliases(majors_data, overrides),
    )
