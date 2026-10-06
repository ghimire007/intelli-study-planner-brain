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

seeds/                          # DB seed scripts + knowledge base data
├── seed.py                     # handbook + subject/major KB seeding
├── scraped/                    # raw CourseLoop crawler output (JSON)
└── kb/                         # generated subject/major markdown cards

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

### Authentication — `/api/v1/auth`

Authentication uses an opaque server-generated token in an HTTP-only cookie.
The database stores only a SHA-256 hash of that token, and passwords are hashed
with Argon2. Cross-origin clients must include credentials (for example,
`credentials: "include"` with `fetch`).

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/register` | Create an account and start a session |
| `POST` | `/api/v1/auth/login` | Verify credentials and start a session |
| `POST` | `/api/v1/auth/logout` | Revoke the current session |
| `GET` | `/api/v1/auth/me` | Return the authenticated user |

Register accepts `email`, `password`, and optional `display_name`. Login accepts
`email` and `password`. The legacy `X-Courseo-Login-Session` header is not used
for authentication.

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
GEMINI_MODEL=gemini-3.5-flash
AUTH_COOKIE_NAME=courseo_session
AUTH_SESSION_DAYS=30
AUTH_COOKIE_SECURE=false
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | Async psycopg3 connection string |
| `APP_PORT` | No | `7777` | Port the server listens on |
| `GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `GEMINI_MODEL` | No | `gemini-3.5-flash` | Gemini model ID to use |
| `AUTH_COOKIE_NAME` | No | `courseo_session` | Authentication cookie name |
| `AUTH_SESSION_DAYS` | No | `30` | Login session lifetime in days |
| `AUTH_COOKIE_SECURE` | No | `false` | Require HTTPS for auth cookies; set `true` in production |

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

## Demo verification

After integrating new course data, apply migrations **and seed the database**; a running
API with an empty handbook table cannot produce a verified plan.

```bash
source .venv/bin/activate
python -m alembic upgrade head
python -m seeds.seed
python -m uvicorn app.main:app --reload --port 7777
```

For local HTTP development, configure `AUTH_COOKIE_SECURE=false` and
`AUTH_COOKIE_SAMESITE=lax` in `.env`. Keep secure cross-site cookies for production.
The existing `.env` must contain the database connection and vault master keys;
do not replace master keys that encrypted stored student credentials.

1. Sign in, save the student's numeric course code, commencement year, campus and major.
2. Connect a provider key in Settings and verify that it is active. The model catalog
   includes Gemini, OpenAI and Anthropic; each model uses a key for its own provider.
3. For the verified Gemini demo, select **Gemini 3.5 Flash Lite**. Model access varies
   by key: an advertised provider model may still be unavailable to a particular account.
4. Start a chat asking for a complete study plan and provide the complete SOLS record.
   Both linked Markdown tables and flattened transfer-course records are supported.
   Confirm academic candidates or resolve conflicts when requested.
5. The returned reply contains one Markdown table and one fenced JSON plan. Names
   and credit points come from the checked-in subject catalog; the backend verifies
   degree credit, required subjects, preserved record rows and future placements.
6. Ask to revise the plan. Only future subjects may move; completed/current record rows
   remain unchanged. The new response supplies the same table/JSON contract.
7. Reload/reopen the chat. Its ownership-checked Postgres checkpoint history retains
   the rendered plan. Replayed browser context does not reset the plan on each question.

The API preserves the selected model in the session and allows explicit model changes
within a conversation, including provider changes when the student has a usable key.
`reply.requested_model` identifies the selected model; `reply.model` identifies the
provider-reported model. Google can report `gemini-3.5-flash-lite` for a selected
`gemini-3.5-flash` request. No silent substitute is made after an explicitly selected
model is denied. Older replies can lack `requested_model`.
When the complete enrolment record already satisfies the checked degree rules, the
backend renders it directly without a generation call; `reply.model` is then null.

Source data currently comes from the repository's **2026** handbook snapshots, rather
than a newly fetched historical handbook for each commencement year. Future offerings
are checked against that snapshot and must be reconfirmed with UOW before enrolment.
Missing/unsupported rules, unavailable handbooks, unknown subject data, ambiguous credit,
failed validation and provider timeouts produce an actionable error, not a draft plan.
Unspecified transfer credit requires confirmation before automated completion validation.

```bash
python -m pytest -m 'not needs_db' --llm=fake -q
ruff check app tests
```

`LLM_REQUEST_TIMEOUT_SECONDS` defaults to 60; `CHAT_TURN_TIMEOUT_SECONDS` defaults to
180. Generation drafts are kept internal and only a validated table plus matching JSON
is published. The adjacent frontend Study Plan panel reads that JSON.

For a repeatable real HTTP check, put demo login credentials in a private JSON file
containing `email` and `password` (never commit it), then run:

```bash
python -m scripts.verify_demo --credentials /path/to/private-login.json
```

The verifier uses the saved profile and stored provider key, checks the actual plan
content, regenerates it, reauthenticates, verifies restored history and denies anonymous
access. Use `--base-url`, `--model`, `--record` and `--revision` for other demo scenarios.
It writes plan/history evidence with restricted permissions and never prints credentials.
