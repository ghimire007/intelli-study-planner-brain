"""Load merged handbook subject records from seeds/scraped/."""

from __future__ import annotations

import json
from pathlib import Path

SEEDS_DIR = Path(__file__).resolve().parent.parent.parent / "seeds"
SCRAPED_DIR = SEEDS_DIR / "scraped"


def load_subject_catalog(course: str, year: int = 2026) -> dict[str, dict]:
    """Prefer canonical merge; fall back to per-degree scrape."""
    canonical = SCRAPED_DIR / f"subjects_canonical_{year}.json"
    if canonical.exists():
        return json.loads(canonical.read_text(encoding="utf-8"))
    degree_path = SCRAPED_DIR / f"subjects_{course}.json"
    if degree_path.exists():
        return json.loads(degree_path.read_text(encoding="utf-8"))
    return {}
