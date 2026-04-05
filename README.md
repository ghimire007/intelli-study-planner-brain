# IntelliStudy Planner Brain

AI-powered backend for the University of Wollongong study plan generator.  
Paste a SOLS enrolment, get handbook-aware study advice via an LLM.

---

## Project Structure

```
app/
├── main.py                     # FastAPI entry point, lifespan (DB connect/disconnect)
├── core/
│   ├── config.py               # Settings via pydantic-settings (.env)
│   └── database.py             # Async SQLAlchemy engine, session factory, Base
├── api/
│   └── v1/
│       ├── router.py           # Mounts all v1 routers under /api/v1
│       └── chat.py             # Chat endpoints (start, continue, history)
├── llm/
│   ├── base.py                 # BaseLLM abstract class + LLMResponse dataclass
│   └── gemini.py               # Google Gemini implementation
├── models/
│   ├── handbook.py             # Handbook ORM model
│   ├── session.py              # ChatSession ORM model
│   └── message.py              # ChatMessage ORM model (+ MessageRole, LLMProvider enums)
├── schemas/
│   └── chat.py                 # Pydantic request/response schemas
├── services/
│   ├── chat_service.py         # Core chat orchestration logic
│   └── sols_parser.py          # SOLS metadata extraction
└── prompts/
    ├── system.py               # Main LLM system prompt (handbook + SOLS injected)
    └── parser.py               # SOLS parser prompt

migrations/                     # Alembic migration files
├── env.py
├── script.py.mako
└── versions/

seeds/                          # DB seed scripts
├── seed.py
└── handbook_766_2026.md

static/
└── index.html                  # Simple chat UI
```

---

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL (or a Supabase project)
- A Google Gemini API key

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

# 4. Create a .env file (see Environment Variables below)
cp .env.example .env   # then fill in values

# 5. Apply DB migrations
make migrate-up

# 6. Seed handbook data
python -m seeds.seed

# 7. Run the dev server (auto-applies pending migrations on start)
make run-dev
```

| URL | Description |
|-----|-------------|
| `http://localhost:7777` | Chat UI |
| `http://localhost:7777/docs` | Swagger UI (interactive API docs) |
| `http://localhost:7777/redoc` | ReDoc (alternative API docs) |

> **Docker** is for deployment only — ignore it during local development.

---

## API Endpoints

All endpoints are prefixed with `/api/v1`.

### Chat — `/api/v1/chat`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/chat` | Start a new session — paste raw SOLS enrolment as `message` |
| `POST` | `/api/v1/chat/{session_id}` | Continue an existing session with a follow-up message |
| `GET` | `/api/v1/chat/{session_id}` | Retrieve full message history for a session |

#### Start session — `POST /api/v1/chat`

```json
// Request
{ "message": "<paste raw SOLS text here>" }

// Response 201
{
  "session_id": "uuid",
  "reply": {
    "id": 1,
    "role": "assistant",
    "content": "...",
    "provider": "gemini",
    "model": "gemini-2.0-flash-001",
    "tokens_in": 1200,
    "tokens_out": 340,
    "cached_tokens": 0,
    "cost_usd": 0.000102,
    "created_at": "2026-04-05T10:00:00Z"
  }
}
```

#### Continue session — `POST /api/v1/chat/{session_id}`

```json
// Request
{ "message": "Can I take CSCI321 in spring?" }

// Response 200
{
  "session_id": "uuid",
  "reply": { /* same MessageOut shape */ }
}
```

#### Get history — `GET /api/v1/chat/{session_id}`

```json
// Response 200
{
  "session_id": "uuid",
  "degree_code": "766",
  "messages": [ /* array of MessageOut, system messages excluded */ ]
}
```

---

## Environment Variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql+psycopg_async://user:pass@host/db
APP_PORT=7777
GEMINI_API_KEY=your-google-gemini-api-key
GEMINI_MODEL=gemini-2.0-flash-001
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | Async psycopg3 connection string |
| `APP_PORT` | No | `7777` | Port the server listens on |
| `GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `GEMINI_MODEL` | No | `gemini-2.0-flash-001` | Gemini model ID to use |

---

## Database

**PostgreSQL** via Supabase. ORM: **SQLAlchemy 2.0 async** with **psycopg3**.  
Migrations managed by **Alembic**.

### Tables

#### `handbook`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `BIGINT` PK | Auto-increment |
| `year` | `INTEGER` | Handbook year (e.g. `2026`) |
| `course` | `VARCHAR(255)` | Degree code (e.g. `766`) |
| `information` | `TEXT` | Full structured markdown |

Unique constraint on `(year, course)`.

#### `chat_session`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `UUID` PK | Auto-generated |
| `degree_code` | `VARCHAR(50)` | Extracted from SOLS |
| `meta` | `JSON` | Optional metadata |
| `created_at` | `TIMESTAMPTZ` | Auto-set |

#### `chat_message`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `BIGINT` PK | Auto-increment |
| `session_id` | `UUID` FK | References `chat_session.id` |
| `role` | `messagerole` enum | `system` / `user` / `assistant` |
| `content` | `TEXT` | Plain text content |
| `parts` | `JSON` | Raw LLM parts array (assistant only) |
| `provider` | `llmprovider` enum | `gemini` / `anthropic` / `openai` (assistant only) |
| `model` | `VARCHAR(100)` | Model ID used (assistant only) |
| `tokens_in` | `INTEGER` | Input token count |
| `tokens_out` | `INTEGER` | Output token count |
| `cached_tokens` | `INTEGER` | Cached token count |
| `cost_usd` | `NUMERIC(10,8)` | Estimated cost in USD |
| `meta` | `JSON` | Optional metadata |
| `created_at` | `TIMESTAMPTZ` | Auto-set |

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

> `make run-dev` automatically runs `migrate-up` before starting.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web framework | **FastAPI** (async) |
| ORM | **SQLAlchemy 2.0 async** |
| Database | **PostgreSQL** (Supabase) |
| Migrations | **Alembic** |
| LLM | **Google Gemini** (`google-genai`) |
| Settings | **Pydantic v2** `pydantic-settings` |
| Deployment | **Docker** (prod only) |
