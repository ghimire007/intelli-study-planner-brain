"""Crawl the UOW CourseLoop handbook site for a course and emit structured JSON.

Starting from a course page (e.g. /courses/2026/766), it walks the embedded
__NEXT_DATA__ curriculum tree, follows every referenced major (/aos/...) and
subject (/subjects/...) link, and writes three files under seeds/scraped/:

  course_<code>.json    — curriculum structure per campus
  majors_<code>.json    — one entry per major: subjects, campuses, CP
  subjects_<code>.json  — one entry per subject: title, CP, prerequisites,
                          session/campus offerings, handbook URL

Usage:  python scripts/scrape_courseloop.py 766 2026
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

BASE = "https://courses.uow.edu.au"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)


def fetch_page_content(path: str) -> dict | None:
    """Fetch a CourseLoop page and return its pageContent JSON (None on 404).

    Paths may contain spaces (e.g. subject code ``BUS 121``); those are
    percent-encoded before the request so urllib accepts the URL.
    """
    # Keep path separators and already-encoded % sequences; encode spaces etc.
    url = BASE + quote(path, safe="/:?=&%")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    match = NEXT_DATA_RE.search(html)
    if not match:
        return None
    props = json.loads(match.group(1))["props"]["pageProps"]
    return props.get("pageContent")


def walk_structure(container: dict) -> dict:
    """Flatten one curriculum container into {title, cp, items, children}."""
    items = []
    for rel in container.get("relationship") or []:
        items.append(
            {
                "code": rel.get("academic_item_code"),
                "name": rel.get("academic_item_name"),
                "cp": rel.get("academic_item_credit_points"),
                "type": rel.get("academic_item_type"),
                "url": rel.get("academic_item_url"),
            }
        )
    return {
        "title": container.get("title"),
        "cp": container.get("credit_points"),
        "description": container.get("description") or "",
        "items": items,
        "children": [walk_structure(c) for c in container.get("container") or []],
    }


def collect_links(node: dict, majors: dict, subjects: dict) -> None:
    """Recursively gather /aos/ and /subjects/ URLs from a walked structure."""
    for item in node["items"]:
        url = item.get("url") or ""
        if url.startswith("/aos/") and item["code"]:
            majors[item["code"]] = url
        elif url.startswith("/subjects/") and item["code"]:
            subjects[item["code"]] = url
    for child in node["children"]:
        collect_links(child, majors, subjects)


def parse_rules(pc: dict) -> list[dict]:
    """Extract human-readable enrolment rules (prerequisites etc.) from a page."""
    rules = []
    for rule in pc.get("enrolment_rules_applied_to_all") or []:
        rules.append(
            {
                "type": (rule.get("type") or {}).get("label"),
                "description": re.sub(r"<[^>]+>", "", rule.get("description") or "").strip(),
            }
        )
    return rules


def parse_offerings(pc: dict) -> list[dict]:
    offerings = []
    for off in pc.get("unit_offering") or []:
        offerings.append(
            {
                "campus": (off.get("location") or {}).get("value"),
                "session": (off.get("teaching_period") or {}).get("value"),
                "mode": (off.get("attendance_mode") or {}).get("value"),
                "display": off.get("display_name"),
            }
        )
    return offerings


def scrape_subject(code: str, year: int, url: str | None = None) -> dict | None:
    """Fetch one subject page, preferring the curriculum link when present."""
    # Prefer the CourseLoop URL from the curriculum tree (correct path/encoding);
    # fall back to rebuilding from code. Normalize year like scrape_major.
    candidates = []
    if url:
        candidates.append(re.sub(r"/subjects/\d{4}/", f"/subjects/{year}/", url))
        candidates.append(url)
    candidates.append(f"/subjects/{year}/{code}")

    path = None
    pc = None
    for candidate in candidates:
        pc = fetch_page_content(candidate)
        if pc is not None:
            path = candidate
            break
    if pc is None or path is None:
        return None
    return {
        "code": pc.get("code"),
        "title": pc.get("title"),
        "cp": pc.get("credit_points"),
        "description": re.sub(r"<[^>]+>", "", pc.get("description") or "").strip(),
        "rules": parse_rules(pc),
        "offerings": parse_offerings(pc),
        "url": f"{BASE}{quote(path, safe='/:?=&%')}",
    }


def scrape_major(url: str, year: int) -> dict | None:
    # normalize the /aos/ URL to the requested year, falling back to the
    # year baked into the link if the requested year isn't published
    for path in (re.sub(r"/aos/\d{4}/", f"/aos/{year}/", url), url):
        pc = fetch_page_content(path)
        if pc is not None:
            break
    else:
        return None
    structure = pc.get("curriculumStructure") or {}
    containers = [walk_structure(c) for c in structure.get("container") or []]
    return {
        "code": pc.get("code"),
        "title": pc.get("title"),
        "cp": pc.get("credit_points"),
        "description": re.sub(r"<[^>]+>", "", pc.get("description") or "").strip(),
        "structure": containers,
        "url": f"{BASE}{path}",
    }


def main() -> None:
    course = sys.argv[1] if len(sys.argv) > 1 else "766"
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2026

    out_dir = Path(__file__).resolve().parent.parent / "seeds" / "scraped"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching course {course} ({year}) ...")
    pc = fetch_page_content(f"/courses/{year}/{course}")
    if pc is None:
        sys.exit(f"Course page /courses/{year}/{course} not found")

    structure = pc.get("curriculumStructure") or {}
    campuses = [walk_structure(c) for c in structure.get("container") or []]
    course_out = {
        "code": pc.get("course_code") or pc.get("code"),
        "title": pc.get("title"),
        "year": year,
        "cp": pc.get("credit_points"),
        "structure": campuses,
        "url": f"{BASE}/courses/{year}/{course}",
    }

    major_links: dict[str, str] = {}
    subject_links: dict[str, str] = {}
    for campus in campuses:
        collect_links(campus, major_links, subject_links)

    majors = {}
    for code, url in sorted(major_links.items()):
        print(f"  major {code} ...")
        major = scrape_major(url, year)
        if major is None:
            print(f"    !! could not fetch {code}")
            continue
        majors[code] = major
        for container in major["structure"]:
            collect_links(container, {}, subject_links)
        time.sleep(0.3)

    subjects = {}
    failed = []
    for code, url in sorted(subject_links.items()):
        print(f"  subject {code} ...")
        subject = scrape_subject(code, year, url)
        if subject is None:
            failed.append(code)
            print(f"    !! could not fetch {code}")
            continue
        subjects[code] = subject
        time.sleep(0.3)

    (out_dir / f"course_{course}.json").write_text(json.dumps(course_out, indent=2))
    (out_dir / f"majors_{course}.json").write_text(json.dumps(majors, indent=2))
    (out_dir / f"subjects_{course}.json").write_text(json.dumps(subjects, indent=2))
    print(
        f"\nDone: {len(majors)}/{len(major_links)} majors, "
        f"{len(subjects)}/{len(subject_links)} subjects -> {out_dir}"
    )
    if failed:
        print(f"Failed subjects (need manual data): {', '.join(failed)}")


if __name__ == "__main__":
    main()
