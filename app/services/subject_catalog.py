"""Load merged handbook subject records from seeds/scraped/."""

from __future__ import annotations

import json
from pathlib import Path

SEEDS_DIR = Path(__file__).resolve().parent.parent.parent / "seeds"
SCRAPED_DIR = SEEDS_DIR / "scraped"


def _normalize(code: str) -> str:
    return code.upper().replace(" ", "")


def _load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_subject_catalog(course: str, year: int = 2026) -> dict[str, dict]:
    """Canonical merge (General Schedule + 766/1807/1838), plus this course's own
    scraped subjects that the merge lacks — so e.g. 1862's engineering subjects
    reach 1862 students without appearing for every other course."""
    canonical = _load(SCRAPED_DIR / f"subjects_canonical_{year}.json")
    known = {_normalize(code) for code in canonical}
    extra = {
        code: subject
        for code, subject in _load(SCRAPED_DIR / f"subjects_{course}.json").items()
        if _normalize(code) not in known
    }
    return {**canonical, **extra}
