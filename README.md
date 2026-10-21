# IntelliStudy Planner Brain

AI-powered backend for the University of Wollongong study plan generator.  
Paste a SOLS enrolment, get handbook-aware study advice via an LLM.

---

## Project Structure

```
app/
├── main.py                     # FastAPI entry point, lifespan (DB + checkpointer connect/disconnect)
├── core/
│   ├── config.py               # Settings via pydantic-settings (.env)
│   ├── database.py             # Async SQLAlchemy engine, session factory, Base
│   ├── checkpointer.py         # LangGraph Postgres checkpointer (conversation state)
│   ├── crypto.py               # Envelope encryption for students' API keys
│   └── ratelimit.py            # In-process rate limiter (used by the key endpoints)
├── api/
│   └── v1/
│       ├── router.py           # Mounts all v1 routers under /api/v1
│       ├── auth.py             # Register, login, logout, profile, password reset
│       ├── chat.py             # Chat endpoints (start, continue, history, title)
│       ├── keys.py             # Students' own LLM API keys (vault)
│       ├── handbook.py         # Handbook, subject, major and policy lookups
│       ├── eligibility.py      # Eligible subjects and elective priorities
│       └── test_records.py     # Sample SOLS records for development
├── agents/                     # LangGraph study-plan advisor
│   ├── graphAPI.py             # Graph definition and routing
│   ├── state.py                # AdvisorState and plan/metadata helpers
│   ├── skills.py               # Tools the agent can call (handbook, subject, major, elective lookups)
│   ├── llms.py                 # Per-role model selection with retry
│   ├── history.py              # Chat history and per-message token/cost metadata
│   └── nodes/                  # conversation, handbook, stage1 (analysis), stage2 (plan)
├── llm/                        # Provider layer: Gemini, Anthropic, OpenAI
│   ├── factory.py              # Builds the chat model for a provider
│   ├── registry.py             # Providers, models and key-page links
│   ├── config.py               # LLMConfig (keeps the key out of repr)
│   ├── pricing.py              # Per-model token pricing
│   ├── verify.py               # Checks a key against its provider
│   └── errors.py, keyshape.py, text.py
├── models/                     # SQLAlchemy models: auth, session, handbook, subject, major, credential
├── schemas/                    # Pydantic request/response schemas
├── services/                   # agent_chat_service, auth, vault, handbook, eligibility, elective ranking, SOLS parser, ...
├── prompts/                    # System prompts and the prompt builder
├── knowledge/                  # UOW policy markdown (honours, credit and RPL, transfers, ...)
└── test_records/               # Sample SOLS records

migrations/                     # Alembic migration files
├── env.py
├── script.py.mako
└── versions/

seeds/                          # DB seed scripts + knowledge base data
├── seed.py                     # handbook + subject/major KB seeding
├── scraped/                    # raw CourseLoop crawler output (JSON)
├── kb/                         # generated subject/major markdown cards
└── overrides/

tests/                          # pytest suite (tests/e2e needs a database and a live model)
static/
└── index.html                  # Simple chat UI
```

---

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL (or a Supabase project)
- A Google Gemini API key (or a student's own Gemini, Anthropic or OpenAI key saved through the app)
- A `SECRETS_MASTER_KEYS` value if students will save their own keys (see Environment Variables)

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
| `POST` | `/api/v1/chat/{session_id}/title` | Generate a title for a session |

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
| `PATCH` | `/api/v1/auth/me` | Update the profile |
| `DELETE` | `/api/v1/auth/me` | Delete the account |
| `POST` | `/api/v1/auth/forgot-password` | Email a password reset link |
| `POST` | `/api/v1/auth/reset-password` | Set a new password from a reset token |

Register accepts `email`, `password`, and optional `display_name`. Login accepts
`email` and `password`. The legacy `X-Courseo-Login-Session` header is not used
for authentication.

### Other routes

| Prefix | Description |
|--------|-------------|
| `/api/v1/keys` | List providers, and add, update, delete and verify a student's own LLM API key |
| `/api/v1/handbook` | Courses, course rules, subjects, majors and UOW policy topics |
| `/api/v1/planning` | `eligible-subjects` and `elective-priorities` |
| `/api/v1/test-records` | Sample SOLS records for development |

See `/docs` for request and response shapes.

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

Copy `.env.example` to `.env` and fill in the values:

```env
DATABASE_URL=postgresql+psycopg_async://user:pass@host/db
APP_PORT=7777
GEMINI_API_KEY=your-google-gemini-api-key
GEMINI_MODEL=gemini-3.5-flash
AUTH_COOKIE_SECURE=false
CORS_ORIGINS=http://localhost:5173
SECRETS_MASTER_KEYS=1:<base64 key>
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | Async psycopg3 connection string |
| `APP_PORT` | No | `7777` | Port the server listens on |
| `GEMINI_API_KEY` | Yes | — | Project Gemini key, used when a student has no usable key of their own |
| `GEMINI_MODEL` | No | `gemini-3.5-flash` | Gemini model ID to use |
| `ALLOW_SYSTEM_FALLBACK_KEY` | No | `true` | Fall back to `GEMINI_API_KEY` when a student has no key |
| `SECRETS_MASTER_KEYS` | For student keys | — | Master key(s) that seal students' API keys, e.g. `1:<base64>`. Generate one with `python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"`. The server starts without it but students cannot save keys |
| `SECRETS_ACTIVE_KEY_VERSION` | No | `1` | Which master key seals new secrets |
| `SECRET_BACKEND` | No | `local` | `local` seals keys in the database; `infisical` stores them in Infisical |
| `INFISICAL_HOST`, `INFISICAL_CLIENT_ID`, `INFISICAL_CLIENT_SECRET`, `INFISICAL_PROJECT_ID`, `INFISICAL_ENVIRONMENT`, `INFISICAL_SECRET_PATH`, `INFISICAL_TIMEOUT_SECONDS` | With Infisical | see `app/core/config.py` | Infisical connection settings |
| `VAULT_VERIFY_ON_WRITE` | No | `true` | Check a key against its provider before saving it |
| `VAULT_WRITE_LIMIT_PER_HOUR`, `VAULT_VERIFY_LIMIT_PER_HOUR` | No | `20`, `30` | Per-user hourly caps on key writes and checks |
| `AUTH_COOKIE_NAME` | No | `courseo_session` | Authentication cookie name |
| `AUTH_SESSION_DAYS` | No | `30` | Login session lifetime in days |
| `AUTH_COOKIE_SECURE` | No | `true` | Require HTTPS for the auth cookie. Set `false` for local HTTP |
| `AUTH_COOKIE_SAMESITE` | No | `none` | `lax`, `strict` or `none`. `none` requires `AUTH_COOKIE_SECURE=true` |
| `CORS_ORIGINS` | No | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated frontend origins allowed to call the API with cookies |
| `FRONTEND_URL` | No | `https://courseo-frontend.onrender.com` | Base URL for password reset links |
| `PASSWORD_RESET_EXPIRE_MINUTES` | No | `60` | Password reset link lifetime |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` | For reset emails | — | Email settings for password reset |

---

## Database

**PostgreSQL** via Supabase. ORM: **SQLAlchemy 2.0 async** with **psycopg3**.  
Migrations managed by **Alembic**.

### Tables

Alembic owns these tables. LangGraph's checkpointer creates and manages its own `checkpoint_*` tables, which hold the conversation and plan state for each chat session. Chat messages are not stored in a separate table.

| Table | Purpose |
|-------|---------|
| `handbook` | One row per `(year, course, campus)` with the full structured handbook markdown in `information` |
| `subject`, `major` | Subject and major catalog entries per year: `code`, `title`, `credit_points`, `url`, a markdown `card` and structured `data` |
| `chat_session` | One row per chat: `id` (UUID), `user_id`, `degree_code`, `meta` (JSON), and the `provider`, `model` and `credential_id` used |
| `app_user` | Accounts, including student profile fields and elective mode |
| `auth_session` | Login sessions. Only a hash of the cookie token is stored |
| `password_reset_token` | Hashed, expiring password reset tokens |
| `llm_credential` | A student's own LLM API key, sealed locally or held by Infisical (the row keeps metadata and a reference) |
| `llm_credential_audit` | Audit trail for key changes |

See `app/models/` for the columns.

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
| Agent | **LangGraph** with a Postgres checkpointer |
| LLM | **Google Gemini**, **Anthropic** and **OpenAI** through LangChain |
| Settings | **Pydantic v2** `pydantic-settings` |
| Deployment | **Docker** (prod only) |
