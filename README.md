# IntelliStudy Planner Brain

AI-powered backend for the University of Wollongong study plan generator.

---

## Project Structure

```
app/
├── main.py                 # FastAPI entry point, lifespan (DB connect/disconnect)
├── core/
│   ├── config.py           # Settings via pydantic-settings (.env)
│   └── database.py         # Async SQLAlchemy engine, session factory, Base
└── models/
    └── handbook.py         # Handbook ORM model

migrations/                 # Alembic migration files
├── env.py                  # Async-aware migration environment
├── script.py.mako          # Migration file template
└── versions/               # Generated migration scripts live here
```

---

## Getting Started

### Prerequisites

- Python 3.12+

### Local Setup

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd intelli-study-planner-brain

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create a .env file with:
# DATABASE_URL=postgresql+psycopg_async://user:pass@host/db
# APP_PORT=7777

# 5. Generate and apply the initial DB migration
make migrate msg="initial handbook table"

# 6. Run the dev server (auto-applies any pending migrations on start)
make run-dev
```

API: `http://localhost:7777`  
Swagger docs: `http://localhost:7777/docs`

> **Docker** is for deployment only — ignore it during local development.

---

## Database

**PostgreSQL** via Supabase. ORM: **SQLAlchemy 2.0 async** with **psycopg3**.  
Migrations managed by **Alembic**.

### `handbook` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | `BIGINT` PK | Auto-increment |
| `year` | `INTEGER` | Handbook year (e.g. `2025`) |
| `course` | `VARCHAR(255)` | Degree/major/minor code (e.g. `766`) |
| `location` | `VARCHAR(255)` | Campus (e.g. `Wollongong`, `Shoalhaven`) |
| `information` | `TEXT` | Full structured markdown — see `HANDBOOK_TEMPLATE.md` |

Unique constraint on `(year, course, location)` — one entry per degree per campus per year.

### Migration Commands

```bash
# Generate a new migration after changing a model
make migrate msg="describe what changed"

# Apply all pending migrations
make migrate-up

# Roll back the last migration
make migrate-down

# See migration history
make migrate-history

# Check current DB migration state
make migrate-current
```

> `make run-dev` automatically runs `migrate-up` before starting — no need to run it separately during development.

### Handbook Data Format

See `HANDBOOK_TEMPLATE.md` for the standard format for the `information` field.  
See `IMPLEMENTATION.md` for full technical architecture and implementation plan.

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | `postgresql+psycopg_async://user:pass@host/db` |
| `APP_PORT` | Port to run on (default: `7777`) |

---

## Tech Stack

- **FastAPI** — async Python web framework
- **SQLAlchemy 2.0 async** — ORM
- **PostgreSQL** (Supabase) — database
- **Alembic** — migration management
- **Pydantic v2** — settings and schema validation
- **Docker** — deployment only
