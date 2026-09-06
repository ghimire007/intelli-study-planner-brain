"""Distill scraped CourseLoop JSON into a local markdown knowledge base.

Reads seeds/scraped/{course,majors,subjects}_<code>.json and writes one compact
markdown card per subject and per major to seeds/kb/. These cards are the exact
payload the future lookup_subject/lookup_major agent skills will return, and
double as human-reviewable seed data.

Usage:  python scripts/build_knowledge_base.py 766
"""
import json
import re
import sys
from pathlib import Path


def _fmt_list(values: list[str]) -> str:
    cleaned = [v.strip() for v in values if v and v.strip()]
    return "; ".join(cleaned) if cleaned else "none"


def _infer_subject_level(code: str) -> str:
    match = re.search(r"\d", (code or "").replace(" ", ""))
    return f"{match.group()}00-level" if match else "none"


def _subject_attributes(s: dict) -> dict[str, str]:
    """Normalize subject metadata for card output; fall back to legacy rules."""
    prerequisites = list(s.get("prerequisites") or [])
    corequisites = list(s.get("corequisites") or [])
    exclusions = list(s.get("exclusions") or [])
    degree_restrictions = list(s.get("degree_restrictions") or [])
    subject_level = (s.get("subject_level") or "").strip()
    tags = list(s.get("tags") or [])

    for rule in s.get("rules") or []:
        desc = (rule.get("description") or "").strip()
        if not desc:
            continue
        label = (rule.get("type") or "").strip().lower()
        if label in {"pre-requisite", "prerequisite"} and desc not in prerequisites:
            prerequisites.append(desc)
        elif label in {"co-requisite", "corequisite"} and desc not in corequisites:
            corequisites.append(desc)
        elif label in {"exclusion", "exclusions"} and desc not in exclusions:
            exclusions.append(desc)

    if not subject_level:
        subject_level = _infer_subject_level(s.get("code") or "")

    return {
        "prerequisites": _fmt_list(prerequisites),
        "corequisites": _fmt_list(corequisites),
        "exclusions": _fmt_list(exclusions),
        "degree_restrictions": _fmt_list(degree_restrictions),
        "subject_level": subject_level or "none",
        "tags": _fmt_list(tags),
    }


def subject_card(s: dict) -> str:
    attrs = _subject_attributes(s)
    lines = [f"# {s['code']} — {s['title']}", ""]
    lines.append(f"- **Credit Points:** {s['cp']}")
    lines.append(f"- **Subject Level:** {attrs['subject_level']}")
    lines.append(f"- **Prerequisites:** {attrs['prerequisites']}")
    lines.append(f"- **Corequisites:** {attrs['corequisites']}")
    lines.append(f"- **Exclusions:** {attrs['exclusions']}")
    lines.append(f"- **Degree Restrictions:** {attrs['degree_restrictions']}")
    lines.append(f"- **Tags / Topic Areas:** {attrs['tags']}")
    sessions: dict[str, list[str]] = {}
    for off in s["offerings"]:
        if off["campus"] and off["session"]:
            sessions.setdefault(off["campus"], []).append(off["session"])
    if sessions:
        lines.append("- **Availability:**")
        for campus, sess in sorted(sessions.items()):
            lines.append(f"  - {campus}: {', '.join(dict.fromkeys(sess))}")
    lines.append(f"- **Handbook URL:** {s['url']}")
    if s["description"]:
        lines += ["", s["description"].strip()]
    return "\n".join(lines) + "\n"


def _structure_lines(node: dict, depth: int = 0) -> list[str]:
    lines = []
    indent = "  " * depth
    header = node["title"] or "Section"
    cp = f" ({node['cp']} CP)" if node.get("cp") else ""
    lines.append(f"{indent}- **{header}{cp}**")
    for item in node["items"]:
        lines.append(f"{indent}  - {item['code']} — {item['name']} ({item['cp']} CP)")
    for child in node["children"]:
        lines += _structure_lines(child, depth + 1)
    return lines


def major_card(m: dict) -> str:
    lines = [f"# {m['code']} — {m['title']}", ""]
    lines.append(f"- **Credit Points:** {m['cp']}")
    lines.append(f"- **Handbook URL:** {m['url']}")
    if m["description"]:
        lines += ["", m["description"].strip(), ""]
    lines.append("## Structure")
    for container in m["structure"]:
        lines += _structure_lines(container)
    return "\n".join(lines) + "\n"


def main() -> None:
    course = sys.argv[1] if len(sys.argv) > 1 else "766"
    root = Path(__file__).resolve().parent.parent / "seeds"
    scraped = root / "scraped"
    kb = root / "kb"
    (kb / "subjects").mkdir(parents=True, exist_ok=True)
    (kb / "majors").mkdir(parents=True, exist_ok=True)

    subjects = json.loads((scraped / f"subjects_{course}.json").read_text())
    majors = json.loads((scraped / f"majors_{course}.json").read_text())

    for code, subject in subjects.items():
        (kb / "subjects" / f"{code}.md").write_text(subject_card(subject))
    for code, major in majors.items():
        (kb / "majors" / f"{code}.md").write_text(major_card(major))

    index = ["# Knowledge Base Index", "", "## Majors"]
    index += [f"- {c} — {m['title']} ({m['cp']} CP)" for c, m in sorted(majors.items())]
    index += ["", "## Subjects"]
    index += [f"- {c} — {s['title']} ({s['cp']} CP)" for c, s in sorted(subjects.items())]
    (kb / "INDEX.md").write_text("\n".join(index) + "\n")

    print(f"Wrote {len(subjects)} subject cards, {len(majors)} major cards -> {kb}")


if __name__ == "__main__":
    main()
