import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke


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
