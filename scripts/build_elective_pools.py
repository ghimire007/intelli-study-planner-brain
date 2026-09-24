"""Derive thin elective pool configs from scraped course trees.

Reads course_<code>.json (and optional majors for context later) and writes
elective_pools_<code>.json — pool rules / code lists only, no subject bodies.

Default campus: Wollongong. Named lists at structure root are attached when
referenced by description (e.g. Business Electives List).

Usage:
  python scripts/build_elective_pools.py
  python scripts/build_elective_pools.py 766 1807 1838 1802 1862 --campus Wollongong
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_COURSES = ("766", "1807", "1838", "1802", "1862")
SCHOOL_PREFIXES = ("CSIT", "CSCI", "ISIT")

_ELECTIVE_TITLE_RE = re.compile(r"elective", re.IGNORECASE)
_MAJOR_OR_ELECTIVE_RE = re.compile(r"major\s+study\s+or\s+elective", re.IGNORECASE)
_GS_RE = re.compile(r"general\s+schedule", re.IGNORECASE)
_SCHOOL_RE = re.compile(r"\b(CSIT|CSCI|ISIT)\b", re.IGNORECASE)
_BUSINESS_LIST_RE = re.compile(r"business\s+electives?\s+list", re.IGNORECASE)
_IT_BUSINESS_LIST_RE = re.compile(
    r"information\s+technology\s*/\s*business\s+elective", re.IGNORECASE
)
_LEVEL_RULE_RE = re.compile(
    r"one\s+200\s*/\s*300[- ]level.*?three\s+300[- ]level",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_code(code: str) -> str:
    return (code or "").upper().replace(" ", "")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk(node: dict):
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def _title(node: dict) -> str:
    return (node.get("title") or "").strip()


def _item_codes(node: dict) -> list[str]:
    codes: list[str] = []
    for item in node.get("items") or []:
        code = item.get("code")
        if code and not str(code).startswith("MAJ"):
            codes.append(_normalize_code(code))
    return codes


def _parse_cp(raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _find_campus_root(structure: list[dict], campus: str) -> dict | None:
    campus_l = campus.strip().lower()
    preferred = {
        "wollongong": [
            "bachelor of computer science at wollongong campus",
            "bachelor of information technology at wollongong campus",
            "bachelor of business information systems at wollongong campus",
        ],
    }
    nodes: list[dict] = []
    for node in structure:
        nodes.append(node)
        nodes.extend(node.get("children") or [])

    for want in preferred.get(campus_l, []):
        for node in nodes:
            if _title(node).lower() == want:
                return node

    candidates = [n for n in nodes if campus_l in _title(n).lower()]
    # Single-campus courses (e.g. 1802, 1862) have no per-campus containers;
    # the whole structure is that campus's tree.
    if not candidates and not any("campus" in _title(n).lower() for n in nodes):
        return {"title": campus, "items": [], "children": structure}
    for node in candidates:
        t = _title(node).lower()
        if "honours" in t or "top up" in t or "admitted" in t:
            continue
        return node
    return candidates[0] if candidates else None


def _collect_named_lists(structure: list[dict]) -> dict[str, dict]:
    """Top-level / shared lists that sit outside campus year trees."""
    named: dict[str, dict] = {}
    for node in structure:
        title = _title(node)
        codes = _item_codes(node)
        if not codes:
            continue
        lower = title.lower()
        if "business electives" in lower and "wollongong" in lower:
            key = "business_electives_wollongong_liverpool"
        elif "information technology/business elective" in lower:
            key = "it_business_electives"
        elif _ELECTIVE_TITLE_RE.search(title) and not any(
            c in lower for c in ("wollongong", "liverpool", "singapore", "hong kong")
        ):
            # Orphan root elective list (e.g. 766 36cp coded electives) — keep aside.
            key = "root_electives_list"
        else:
            continue
        named[key] = {
            "title": title,
            "cp": _parse_cp(node.get("cp")),
            "codes": codes,
            "description": (node.get("description") or "").strip(),
        }
    return named


def _classify_pool(node: dict, named_lists: dict[str, dict]) -> dict:
    title = _title(node)
    desc = (node.get("description") or "").strip()
    codes = _item_codes(node)
    cp = _parse_cp(node.get("cp"))
    lower_title = title.lower()

    pool: dict = {
        "id": re.sub(r"[^a-z0-9]+", "_", lower_title).strip("_") or "elective",
        "title": title,
        "cp": cp,
        "description": desc,
    }

    # Explicit codes on the section itself.
    if codes:
        pool["mode"] = "named_list"
        pool["codes"] = codes
        return pool

    # Points at Business Electives List.
    if _BUSINESS_LIST_RE.search(desc) and "business_electives_wollongong_liverpool" in named_lists:
        pool["mode"] = "named_list"
        pool["list_ref"] = "business_electives_wollongong_liverpool"
        pool["codes"] = named_lists["business_electives_wollongong_liverpool"]["codes"]
        return pool

    # Points at IT/Business list (SIM-style; rarely Wollongong).
    if _IT_BUSINESS_LIST_RE.search(desc) and "it_business_electives" in named_lists:
        pool["mode"] = "named_list"
        pool["list_ref"] = "it_business_electives"
        pool["codes"] = named_lists["it_business_electives"]["codes"]
        return pool

    # CSIT level-structured electives (1838 Y3).
    if _LEVEL_RULE_RE.search(desc) and _SCHOOL_RE.search(desc):
        pool["mode"] = "prefix_level"
        pool["prefixes"] = list(SCHOOL_PREFIXES)
        pool["level_rules"] = [
            {"count": 1, "levels": [200, 300]},
            {"count": 3, "levels": [300]},
        ]
        pool["exclude"] = ["core", "core_selection", "major_core"]
        return pool

    # Open school and/or General Schedule.
    include_gs = bool(_GS_RE.search(desc))
    include_school = bool(_SCHOOL_RE.search(desc))
    if include_gs or include_school:
        pool["mode"] = "open"
        pool["prefixes"] = list(SCHOOL_PREFIXES) if include_school else []
        pool["include_general_schedule"] = include_gs
        pool["exclude"] = ["core", "core_selection", "major_core"]
        if _MAJOR_OR_ELECTIVE_RE.search(title):
            pool["also_allows_major"] = True
        return pool

    # Fallback: empty elective section with no parseable rule.
    pool["mode"] = "unknown"
    return pool


def _is_elective_section(node: dict) -> bool:
    title = _title(node)
    if not _ELECTIVE_TITLE_RE.search(title):
        return False
    # Skip containers that only group child elective buckets (no own rule / items)
    # when they have elective children — emit children instead.
    children = node.get("children") or []
    elective_children = [c for c in children if _ELECTIVE_TITLE_RE.search(_title(c))]
    if elective_children and not _item_codes(node) and not (node.get("description") or "").strip():
        return False
    return True


def build_pools_for_course(
    course_data: dict,
    campus: str,
) -> dict:
    structure = course_data.get("structure") or []
    named_lists = _collect_named_lists(structure)
    campus_root = _find_campus_root(structure, campus)
    if campus_root is None:
        raise ValueError(f"Campus {campus!r} not found in course structure")

    pools: list[dict] = []
    seen_ids: dict[str, int] = {}
    emitted: set[int] = set()

    def _add_pool(node: dict) -> None:
        node_id = id(node)
        if node_id in emitted:
            return
        emitted.add(node_id)
        pool = _classify_pool(node, named_lists)
        base_id = pool["id"]
        n = seen_ids.get(base_id, 0)
        seen_ids[base_id] = n + 1
        if n:
            pool["id"] = f"{base_id}_{n + 1}"
        pools.append(pool)

    for node in _walk(campus_root):
        if node is campus_root or id(node) in emitted:
            continue
        title = _title(node)
        children = node.get("children") or []
        elective_children = [c for c in children if _ELECTIVE_TITLE_RE.search(_title(c))]
        # Parent Electives with child buckets → emit children only.
        if (
            _ELECTIVE_TITLE_RE.search(title)
            and elective_children
            and not _item_codes(node)
        ):
            for child in elective_children:
                _add_pool(child)
            continue

        if not _is_elective_section(node):
            continue
        if elective_children:
            continue

        _add_pool(node)

    return {
        "course": str(course_data.get("code") or ""),
        "year": int(course_data.get("year") or 2026),
        "campus": campus,
        "pools": pools,
        "named_lists": named_lists,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build elective_pools_*.json from course trees")
    parser.add_argument(
        "courses",
        nargs="*",
        default=list(DEFAULT_COURSES),
        help="Course codes (default: 766 1807 1838)",
    )
    parser.add_argument("--campus", default="Wollongong", help="Campus to derive pools for")
    args = parser.parse_args()

    scraped = Path(__file__).resolve().parent.parent / "seeds" / "scraped"
    if not scraped.is_dir():
        sys.exit(f"Scraped dir not found: {scraped}")

    for course in args.courses:
        path = scraped / f"course_{course}.json"
        if not path.exists():
            print(f"Skipping {course} — {path.name} not found")
            continue
        course_data = _load_json(path)
        try:
            out = build_pools_for_course(course_data, args.campus)
        except ValueError as exc:
            print(f"Skipping {course}: {exc}")
            continue
        out_path = scraped / f"elective_pools_{course}.json"
        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        modes = ", ".join(f"{p['id']}={p['mode']}" for p in out["pools"])
        print(
            f"{course} ({args.campus}): {len(out['pools'])} pools "
            f"[{modes}] -> {out_path.name}"
        )


if __name__ == "__main__":
    main()
