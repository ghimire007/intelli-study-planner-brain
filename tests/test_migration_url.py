import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = pytest.mark.smoke


def test_previously_applied_guest_and_saved_plan_revisions_remain_in_history():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("c1d2e3f4a5b6").down_revision == "47293dc235ea"
    assert scripts.get_revision("d2e3f4a5b6c7").down_revision == "c1d2e3f4a5b6"
    assert scripts.get_heads() == ["d2e3f4a5b6c7"]
    # A database already at the old branch's head must need no DDL or stamp.
    assert list(scripts.iterate_revisions("head", "d2e3f4a5b6c7")) == []


def test_upgrade_from_main_preserves_the_original_additive_migrations():
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg_async://test:test@localhost/test"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "47293dc235ea:head", "--sql"],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE saved_study_plan" in result.stdout
    assert "ALTER TABLE app_user ADD COLUMN is_guest BOOLEAN DEFAULT false NOT NULL" in result.stdout
    assert "DROP TABLE" not in result.stdout


def test_alembic_loads_with_percent_encoded_password():
    env = {**os.environ, "DATABASE_URL":
           "postgresql+psycopg_async://test:encoded%21%40%25@localhost/test"}
    # Load the real migration environment without connecting or applying DDL.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "base", "--sql"],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
