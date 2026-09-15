"""Merge General Schedule + degree subject scrapes into one canonical catalog.

Dedupes by subject code (handbook year), unions tags, and records which sources
contributed each code. Does not touch the DB or elective pools.

Inputs (seeds/scraped/):
  subjects_general_schedule.json
  subjects_<course>.json  for each --course (default: 766, 1807, 1838)

Outputs:
  subjects_canonical_<year>.json  — {code: subject record + sources[]}
  subjects_canonical_<year>_index.json — counts and source breakdown

Usage:
  python scripts/merge_subjects.py 2026
  python scripts/merge_subjects.py 2026 --courses 766 1807 1838
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_COURSES = ("766", "1807", "1838")


def _load_subjects(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _normalize_code(code: str) -> str:
    return (code or "").upper().replace(" ", "")


def _merge_record(existing: dict | None, incoming: dict, source: str) -> dict:
    """Prefer existing body; always union tags and sources."""
    if existing is None:
        out = dict(incoming)
        out["sources"] = [source]
        tags = list(out.get("tags") or [])
        out["tags"] = list(dict.fromkeys(tags))
        return out

    sources = list(existing.get("sources") or [])
    if source not in sources:
        sources.append(source)
    existing["sources"] = sources

    tags = list(existing.get("tags") or [])
    for tag in incoming.get("tags") or []:
        if tag and tag not in tags:
            tags.append(tag)
    existing["tags"] = tags
    return existing


def merge_catalogs(
    year: int,
    scraped_dir: Path,
    courses: tuple[str, ...] | list[str],
) -> tuple[dict[str, dict], dict]:
    sources: list[tuple[str, Path]] = [
        ("general_schedule", scraped_dir / "subjects_general_schedule.json"),
    ]
    for course in courses:
        sources.append((f"course_{course}", scraped_dir / f"subjects_{course}.json"))

    catalog: dict[str, dict] = {}
    loaded: dict[str, int] = {}
    missing: list[str] = []

    for source_name, path in sources:
        subjects = _load_subjects(path)
        if not subjects and not path.exists():
            missing.append(path.name)
            loaded[source_name] = 0
            continue
        loaded[source_name] = len(subjects)
        for code, record in subjects.items():
            key = _normalize_code(record.get("code") or code)
            if not key:
                continue
            # Keep a stable display code from the preferred record.
            catalog[key] = _merge_record(catalog.get(key), record, source_name)

    index = {
        "year": year,
        "courses": list(courses),
        "loaded": loaded,
        "missing_files": missing,
        "canonical_count": len(catalog),
        "codes": sorted(catalog.keys()),
    }
    return catalog, index


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge scraped subject JSONs into subjects_canonical_<year>.json"
    )
    parser.add_argument(
        "year",
        nargs="?",
        type=int,
        default=2026,
        help="Handbook year label for output filenames (default: 2026)",
    )
    parser.add_argument(
        "--courses",
        nargs="+",
        default=list(DEFAULT_COURSES),
        help="Degree codes whose subjects_*.json to include",
    )
    args = parser.parse_args()

    scraped_dir = Path(__file__).resolve().parent.parent / "seeds" / "scraped"
    if not scraped_dir.is_dir():
        sys.exit(f"Scraped dir not found: {scraped_dir}")

    catalog, index = merge_catalogs(args.year, scraped_dir, args.courses)
    if not catalog:
        sys.exit("No subjects loaded — run scrapers first")

    out_catalog = scraped_dir / f"subjects_canonical_{args.year}.json"
    out_index = scraped_dir / f"subjects_canonical_{args.year}_index.json"
    out_catalog.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    out_index.write_text(json.dumps(index, indent=2), encoding="utf-8")

    print(
        f"Merged {index['canonical_count']} subjects "
        f"(sources: {index['loaded']}) -> {out_catalog.name}"
    )
    if index["missing_files"]:
        print(f"Missing (skipped): {', '.join(index['missing_files'])}")


if __name__ == "__main__":
    main()
