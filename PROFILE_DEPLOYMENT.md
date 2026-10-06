# Deploy the account setup fix

Deploy the backend changes together:

- `app/api/v1/auth.py`, `app/models/auth.py`, `app/schemas/auth.py`
- `migrations/env.py` and `migrations/versions/f2a3b4c5d6e7_add_student_profile_fields.py`
- `Dockerfile`
- `.github/workflows/ci.yml`, `requirements-dev.txt`, `tests/test_profile_update.py`,
  `tests/test_profile_migration.py`, and `tests/test_migration_url.py` for validation.

The migration and tests were initially untracked: include them explicitly in the
commit. Do not include the unrelated untracked chat tests as part of this fix.

1. Run CI and merge the fix into the backend's deployed branch (`main` in the
   repository workflow). The PostgreSQL job creates the old schema, inserts an
   account/session/reset token, upgrades to head, and checks that data survives.
2. Render's blueprint has `autoDeploy: false`. The successful main-branch CI run
   uses `RENDER_DEPLOY_HOOK_URL` to deploy its tested SHA. If the hook is not
   configured, manually deploy that same SHA to `courseo-backend` after CI passes.
   A service restart alone does not fetch new code.
3. Ensure Render uses this Dockerfile and has no Docker Command override that
   bypasses its CMD. Startup is now:
   `python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7777}`.
   It runs against Render's configured `DATABASE_URL` and refuses to start if
   migration fails. CI's database is separate from production. Keep the existing
   production database URL; do not recreate the database or stamp past migration.
4. Confirm logs show upgrade to `f2a3b4c5d6e7` and successful server startup.
   The migration adds five columns only, retaining account IDs, emails, password
   hashes, sessions, and reset tokens. Existing users get degree `766`, empty
   interests, and null year/campus/major. Downgrading removes profile preferences;
   it is not part of deployment.
5. Verify the deployed OpenAPI document exposes PATCH `/api/v1/auth/me`.
   An unauthenticated PATCH with `{}` must return 401, not 405. In a signed-in
   browser, save degree preferences with `elective_interests: []`: PATCH must
   return 200 and the updated profile. Reload and check GET `/api/v1/auth/me`
   returns the same preferences. Also verify a partial name update keeps those
   preferences and an email change without a correct password is rejected.
   Use the frontend's credentialed requests and configured CORS origin.

Render's free service plan does not offer a pre-deploy command; running migrations
in Docker startup covers the current single-instance configuration. If scaling
later, move migrations to a serialized release step before starting replicas.
See https://render.com/docs/deploys and https://render.com/docs/docker.

No production deployment or authenticated production verification was performed
as part of this local change. Production is not confirmed fixed until step 5 passes.
