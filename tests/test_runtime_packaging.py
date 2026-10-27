"""Exercise elective loaders against the files actually copied into the runtime image."""
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke


def test_docker_image_contains_the_runtime_elective_and_course_data(tmp_path):
    root = Path(__file__).resolve().parents[1]
    image = tmp_path / "image"
    image.mkdir()
    for line in (root / "Dockerfile").read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        _, source, destination = shlex.split(line)
        if (root / source).is_dir():
            shutil.copytree(root / source, image / destination, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(root / source, image / destination)
    env = {**os.environ, "PYTHONPATH": str(image),
           "DATABASE_URL": "postgresql+psycopg_async://ci:ci@127.0.0.1:5432/ci",
           "GEMINI_API_KEY": "not-used"}
    script = """
from app.services.elective_pools import load_elective_pools
from app.services.subject_catalog import load_subject_catalog
from app.services.course_rules import load_course_rules
from app.services.elective_ranking import get_elective_priorities
from app.schemas.elective_ranking import ElectivePriorityInput
for course in ('766', '1807', '1838', '1802', '765'):
    assert load_elective_pools(course).get('pools'), course
    assert load_subject_catalog(course), course
    assert load_course_rules(course), course
result = get_elective_priorities(ElectivePriorityInput(
    course='766', campus='Wollongong', session='Autumn', mode='interest',
    interests=['economics'], completed_subjects=[], planned_subjects=[]))
assert any(pool.priorities for pool in result.pools)
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=image, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
