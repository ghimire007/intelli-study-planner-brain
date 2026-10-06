"""Run only against CI's disposable database, at the pre-profile revision."""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.needs_db


def test_existing_account_survives_profile_migration():
    url = os.environ.get("PROFILE_MIGRATION_TEST_URL")
    if not url:
        pytest.skip("Requires a disposable database at a1b2c3d4e5f6")
    engine = create_engine(url.replace("postgresql+psycopg_async:", "postgresql+psycopg:"))
    user_id, session_id, reset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "a1b2c3d4e5f6"
            conn.execute(text("INSERT INTO app_user (id, email, display_name, password_hash) "
                              "VALUES (:id, 'legacy@example.com', 'Legacy', 'preserved-hash')"),
                         {"id": user_id})
            for table, record_id in [("auth_session", session_id), ("password_reset_token", reset_id)]:
                conn.execute(text(f"INSERT INTO {table} (id, user_id, token_hash, expires_at) "
                                  "VALUES (:id, :user, :token, CURRENT_TIMESTAMP + interval '1 day')"),
                             {"id": record_id, "user": user_id, "token": str(record_id)})
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM app_user WHERE id = :id"), {"id": user_id}).mappings().one()
            assert row["email"] == "legacy@example.com"
            assert row["password_hash"] == "preserved-hash"
            assert row["display_name"] == "Legacy"
            assert row["degree_code"] == "766"
            assert row["elective_interests"] == []
            assert row["commencement_year"] is None
            assert row["campus"] is None
            assert row["major"] is None
            for table, record_id in [("auth_session", session_id), ("password_reset_token", reset_id)]:
                assert conn.execute(text(f"SELECT user_id FROM {table} WHERE id = :id"),
                                    {"id": record_id}).scalar_one() == user_id
    finally:
        engine.dispose()
