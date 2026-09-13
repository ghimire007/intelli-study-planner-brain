"""Discover General Schedule subjects via CourseLoop search, then scrape each page.

Uses the handbook search API filtered by the General Schedule csTag, handbook
year, Wollongong campus, and Undergraduate award type, then reuses
scrape_courseloop.scrape_subject for the same subject JSON shape as
subjects_<course>.json.

Source search (browser):
  https://courses.uow.edu.au/search?ct=subject&csTags=2a2d01c94f52db0044a3cf401310c7ef

Writes under seeds/scraped/:
  subjects_general_schedule.json  — full subject records keyed by code
  general_schedule_<year>.json    — index: tag, year, codes, scrape stats

Usage:
  python scripts/scrape_general_schedule.py 2026
  python scripts/scrape_general_schedule.py 2026 --limit 20
  python scripts/scrape_general_schedule.py 2026 --resume
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Sibling import: scrape_courseloop lives next to this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_courseloop import scrape_subject  # noqa: E402

BASE = "https://courses.uow.edu.au"
SEARCH_URL = f"{BASE}/api/search/search-academic-items"
SITE_ID = "uow-prod-pres"
# General Schedule of Subjects tag from the public handbook search URL above.
GENERAL_SCHEDULE_TAG = "2a2d01c94f52db0044a3cf401310c7ef"
WOLLONGONG_CAMPUS = "Wollongong"
UNDERGRADUATE_STUDY_LEVEL = "Undergraduate"
PAGE_SIZE = 100
REQUEST_PAUSE_S = 0.25
SUBJECT_PAUSE_S = 0.3
SUBJECT_RETRIES = 4
SUBJECT_RETRY_BACKOFF_S = 5.0


def _post_json(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": BASE,
            "Referer": (
                f"{BASE}/search?ct=subject&csTags={GENERAL_SCHEDULE_TAG}"
            ),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    return payload.get("data") or payload


def discover_general_schedule_subjects(year: int) -> dict[str, str]:
    """Return {code: /subjects/... url} for General Schedule subjects in ``year``.

    Filters by csTags, implementationYear, Wollongong campus, and Undergraduate
    study level so multi-year duplicates (same code across 2020–2026) are
    collapsed to the handbook year entry.
    """
    filters = [
        {
            "filterField": "csTags",
            "filterValue": [GENERAL_SCHEDULE_TAG],
            "isExactMatch": True,
        },
        {
            "filterField": "implementationYear",
            "filterValue": [str(year)],
            "isExactMatch": True,
        },
        {
            "filterField": "locationDisplay",
            "filterValue": [WOLLONGONG_CAMPUS],
            "isExactMatch": True,
        },
        {
            "filterField": "studyLevel",
            "filterValue": [UNDERGRADUATE_STUDY_LEVEL],
            "isExactMatch": True,
        },
    ]
    links: dict[str, str] = {}
    total: int | None = None
    offset = 0

    while total is None or offset < total:
        page = _post_json(
            SEARCH_URL,
            {
                "siteId": SITE_ID,
                "query": "",
                "contenttype": "subject",
                "from": offset,
                "size": PAGE_SIZE,
                "searchFilters": filters,
            },
        )
        results = page.get("results") or []
        if total is None:
            total = int(page.get("total") or 0)
            print(f"Discovering General Schedule subjects ({year}): {total} hits")
        if not results:
            break
        for item in results:
            code = (item.get("code") or "").strip()
            uri = (item.get("uri") or "").strip()
            if not code or not uri:
                continue
            # Prefer year-rewritten path; scrape_subject also normalizes year.
            if f"/subjects/{year}/" not in uri:
                uri = f"/subjects/{year}/{code}"
            links[code] = uri
        offset += len(results)
        print(f"  discovered {len(links)}/{total} unique codes (offset {offset})")
        time.sleep(REQUEST_PAUSE_S)

    return links


def _load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape UOW General Schedule subjects into seeds/scraped/"
    )
    parser.add_argument(
        "year",
        nargs="?",
        type=int,
        default=2026,
        help="Handbook year (default: 2026)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Scrape at most N subjects (after discovery); useful for smoke tests",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Keep existing subjects_general_schedule.json entries and skip those codes",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Only write the index of codes; do not fetch subject pages",
    )
    args = parser.parse_args()
    year = args.year

    out_dir = Path(__file__).resolve().parent.parent / "seeds" / "scraped"
    out_dir.mkdir(parents=True, exist_ok=True)
    subjects_path = out_dir / "subjects_general_schedule.json"
    index_path = out_dir / f"general_schedule_{year}.json"

    print(f"Fetching General Schedule subject list ({year}) ...")
    try:
        links = discover_general_schedule_subjects(year)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        sys.exit(f"Search API failed ({exc.code}): {body}")
    except urllib.error.URLError as exc:
        sys.exit(f"Search API unreachable: {exc}")

    if not links:
        sys.exit("No General Schedule subjects discovered")

    codes = sorted(links.keys())
    if args.limit is not None:
        codes = codes[: max(0, args.limit)]

    index = {
        "year": year,
        "cs_tag": GENERAL_SCHEDULE_TAG,
        "campus": WOLLONGONG_CAMPUS,
        "study_level": UNDERGRADUATE_STUDY_LEVEL,
        "source_search_url": (
            f"{BASE}/search?ct=subject&csTags={GENERAL_SCHEDULE_TAG}"
        ),
        "search_filters": {
            "csTags": GENERAL_SCHEDULE_TAG,
            "implementationYear": str(year),
            "locationDisplay": WOLLONGONG_CAMPUS,
            "studyLevel": UNDERGRADUATE_STUDY_LEVEL,
        },
        "discovered_count": len(links),
        "codes": sorted(links.keys()),
    }
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"Wrote index ({len(links)} codes) -> {index_path}")

    if args.discover_only:
        print("Discover-only: skipping subject page scrape")
        return

    subjects: dict = _load_existing(subjects_path) if args.resume else {}
    if args.resume and subjects:
        print(f"Resume: keeping {len(subjects)} existing subject records")

    failed: list[str] = []
    scraped = 0
    for i, code in enumerate(codes, start=1):
        if args.resume and code in subjects:
            continue
        url = links.get(code)
        print(f"  [{i}/{len(codes)}] subject {code} ...")
        subject = scrape_subject(code, year, url)
        if subject is None:
            failed.append(code)
            print(f"    !! could not fetch {code}")
            continue
        # Ensure General Schedule tag is present even if page omits cs_tags text.
        tags = list(subject.get("tags") or [])
        if "General Schedule" not in tags:
            tags.append("General Schedule")
            subject["tags"] = tags
        subjects[code] = subject
        scraped += 1
        if scraped % 25 == 0:
            subjects_path.write_text(json.dumps(subjects, indent=2), encoding="utf-8")
            print(f"    checkpoint: {len(subjects)} subjects saved")
        time.sleep(SUBJECT_PAUSE_S)

    subjects_path.write_text(json.dumps(subjects, indent=2), encoding="utf-8")
    index["scraped_count"] = len(subjects)
    index["failed"] = failed
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    print(
        f"\nDone: scraped {scraped} new, {len(subjects)} total subjects "
        f"({len(failed)} failed) -> {subjects_path}"
    )
    if failed:
        print(f"Failed subjects: {', '.join(failed)}")


if __name__ == "__main__":
    main()
