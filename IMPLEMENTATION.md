# IntelliStudyPlanner (Courseo) — Technical Implementation Guide

## System Overview

AI-powered backend that generates personalised, validated study plans for UOW students through a conversational chat interface. A student pastes their SOLS enrolment record; a LangGraph agent — grounded in official handbook, subject, and major data stored in PostgreSQL — audits their progress and produces a semester-by-semester plan.

**Key properties:**
- No registration/login — sessions are anonymous UUIDs
- PII (name, student number, contact details) is scrubbed before anything is stored or sent to the LLM; grades are kept (needed to distinguish completed from enrolled subjects)
- All conversational state lives in a LangGraph Postgres checkpointer, keyed by session ID
- The agent never guesses academic facts — prerequisites, session availability, majors, and policies come from tool calls against seeded official data

---

## Architecture

### Services

| Service | Tech | Responsibility |
|---------|------|----------------|
| `brain` (this repo) | FastAPI + Python 3.12 | LangGraph agent, knowledge base, chat API |
| Frontend (separate repo) | React | ChatGPT-style chat UI, renders the plan JSON |

### High-Level Flow

```
Student pastes SOLS record
        │
        ▼
PII Scrubber (services/pii.py) ── redacts name / student no. / email / phone
        │
        ▼
LangGraph Advisor Agent (agents/graph.py)
   parse_input ── LLM extracts degree_code / year / campus
        │
        ▼
   agent (Gemini, tool-calling loop)
    ├── confirm_metadata_tool    ── student confirms degree/year/campus
    ├── fetch_handbook_tool      ── course rules from `handbook` table
    ├── lookup_subjects_tool     ── prereqs/sessions/URLs from `subject` table (batched)
    ├── lookup_major_tool        ── major requirements from `major` table
    └── lookup_uow_policy_tool   ── policy topics from app/knowledge/*.md
        │
        ▼
Structured reply: audit (collapsible) + plan table (linked subject codes) + plan JSON
```

---

## The LangGraph Agent (`app/agents/graph.py`)

### State (`AdvisorState`)

Persisted per thread by the Postgres checkpointer (`app/core/checkpointer.py`), so each turn only supplies the *new* message:

| Field | Type | Purpose |
|-------|------|---------|
| `messages` | `list[BaseMessage]` (add_messages) | Full conversation, including tool calls/results |
| `raw_sols` | `str` | PII-scrubbed SOLS paste, injected into every system prompt |
| `meta` | `dict \| None` | Parsed `{degree_code, year, campus}` (plain dict — checkpointer serialization) |
| `meta_confirmed` | `bool` | Whether the student has confirmed the metadata |
| `handbook` | `str \| None` | Cached handbook markdown once fetched |

### Graph Topology

```
parse_input ──► agent ──► END            (no tool calls)
                  │ ▲
                  ▼ │
               tools ──► capture_tool_results
```

- **`parse_input`** — runs once per session (skipped when `meta` already set). Calls the parser LLM (`services/sols_parser.py`) to extract degree_code/year/campus. Nullable fields: if extraction isn't confident, the agent asks the student instead of guessing.
- **`agent`** — the Gemini tool-calling node. Uses a *restricted* toolset (`confirm`) until metadata is confirmed, then the *full* toolset. System prompt rebuilt each turn by `prompts/builder.py`.
- **`tools`** — LangGraph `ToolNode` executing whatever the agent requested.
- **`capture_tool_results`** — caches `fetch_handbook_tool` output into `state.handbook` and `confirm_metadata_tool` output into `state.meta/meta_confirmed`, so later turns don't re-fetch/re-derive.
- **`should_continue`** — loops agent ⇄ tools until the agent responds without tool calls.

### Metadata Confirmation Gate

Two LLM bindings from the same skill registry (`build_skills`):

| Toolset | Available when | Tools |
|---------|---------------|-------|
| `confirm` | Before confirmation | `confirm_metadata_tool`, `lookup_uow_policy_tool` |
| `full` | After confirmation | + `fetch_handbook_tool`, `lookup_subjects_tool`, `lookup_major_tool` |

This deterministically prevents the agent from auditing/planning against unconfirmed degree data.

---

## Agent Skills (`app/agents/skills.py`)

Skills follow the **agent skills pattern**: thin LangChain tool adapters with zero business logic — each wraps a service function and binds runtime context (the DB session).

| Skill | Backing service | Returns |
|-------|-----------------|---------|
| `confirm_metadata_tool` | — | Echoes confirmed `{degree_code, year, campus}` (captured into state) |
| `fetch_handbook_tool(degree_code, year, campus)` | `handbook_service.fetch_handbook` | Course-level rules markdown, exact-campus match preferred |
| `lookup_subjects_tool(codes: list)` | `kb_service.fetch_subjects` | One markdown card per code: title, CP, prerequisites, per-campus sessions, handbook URL. Batched — one call per draft plan. Unknown codes return an explicit "do not invent details" marker |
| `lookup_major_tool(major_code)` | `kb_service.fetch_major` | Major card: title, CP, required subjects, URL. Unknown code returns the list of valid MAJ codes for self-correction |
| `lookup_uow_policy_tool(topic)` | `knowledge_service.load_topic` | Official policy text from `app/knowledge/*.md` (course transfer, credit/RPL, withdrawal, …) |

---

## Knowledge Base Pipeline (scrape → cards → DB)

UOW's handbook site is Next.js/CourseLoop — every page embeds its full data as JSON (`__NEXT_DATA__`), so scraping is JSON extraction, not HTML parsing.

| Step | Command | Output |
|------|---------|--------|
| 1. Scrape | `python scripts/scrape_courseloop.py 766 2026` | `seeds/scraped/{course,majors,subjects}_766.json` — crawls course page → all majors (`/aos/...`) → all subjects (`/subjects/...`), including subjects only referenced inside majors |
| 2. Build cards | `python scripts/build_knowledge_base.py 766` | `seeds/kb/subjects/*.md`, `seeds/kb/majors/*.md`, `INDEX.md` — compact human-reviewable markdown, exactly what the lookup tools return |
| 3. Seed | `python -m seeds.seed` (or `make seed`) | Upserts into `subject`/`major` tables; also inserts inline handbook data. Safe to rerun — KB rows update in place, handbook rows are insert-only |

Current coverage: course 766 (2026) — 8 majors, 42 subjects, real prerequisite expressions (e.g. `(CSIT110 or CSIT111) AND (CSIT113 or CSIT123)`) and per-campus session offerings. Rerun steps 1–3 for new years or new courses.

---

## Privacy — PII Scrubbing (`app/services/pii.py`)

Applied in `AgentChatService.start_session` *before* the SOLS paste reaches the checkpointer or any prompt:

- `**Student:** ...` header line → `[REDACTED]`
- 7–8 digit student numbers (bare or parenthesised) → `[REDACTED]`
- Email addresses and AU phone numbers → `[REDACTED]`
- **Kept:** marks/grades/status — required to classify subjects as Complete vs Enrolled

---

## Prompting (`app/prompts/`)

- `system.py` — the advisor persona + output contract: handbook and SOLS injected as context; mandatory `lookup_subjects_tool` verification of every subject in a draft plan; subject codes in the plan table rendered as `<a href>` links to their handbook pages; electives discussions must link the course handbook page; policy answers only from tool output, never memory; audit wrapped in a collapsible `<details>` block; final machine-readable plan as a fenced JSON block.
- `builder.py` — per-turn assembly: swaps in handbook content (or a "not yet fetched" placeholder) and, pre-confirmation, an instruction telling the agent exactly which metadata fields to ask the student for.

---

## Service Layer (`app/services/`)

| Module | Responsibility |
|--------|----------------|
| `agent_chat_service.py` | Public chat API surface: start/continue/history. Owns PII scrubbing, `ChatSession` row creation, thread_id ↔ session mapping |
| `sols_parser.py` | LLM extraction of degree_code/year/campus from the SOLS paste (`SOLSMeta`, nullable fields) |
| `handbook_service.py` | `handbook` table lookup, campus-preferring |
| `kb_service.py` | `subject`/`major` card lookups (newest year wins) |
| `knowledge_service.py` | Static policy topics from `app/knowledge/*.md` |
| `pii.py` | Regex PII scrubber |

`app/agents/history.py` reconstructs user-facing history (with per-message tokens/cost from `usage_metadata` + `llm/pricing.py`) straight from checkpointer snapshots — no `chat_message` table exists anymore.

---

## Database Schema

PostgreSQL (Supabase), SQLAlchemy 2.0 async + psycopg3, Alembic migrations (head: `e7a8b9c0d1e2`).

### Domain tables (Alembic-managed)

| Table | Key columns | Purpose |
|-------|-------------|---------|
| `handbook` | `(year, course, campus)` unique; `information TEXT` | Course-level rules markdown per campus |
| `subject` | `(year, code)` unique; `title`, `credit_points`, `url`, `card TEXT`, `data JSON` | Per-subject knowledge: `card` = markdown returned to the agent; `data` = full scraped JSON (rules, offerings) |
| `major` | `(year, code)` unique; same shape as `subject` | Per-major requirements |
| `chat_session` | `id UUID`, `degree_code`, `created_at` | Thin indexable session row (API 404s against it; label only, not source of truth) |

### LangGraph tables (checkpointer-managed)

`checkpoints`, `checkpoint_writes`, etc. — created by `AsyncPostgresSaver.setup()`, hold all conversational state keyed by `thread_id = str(chat_session.id)`.

---

## API (`app/api/v1/`)

All under `/api/v1`:

| Method | Path | Behaviour |
|--------|------|-----------|
| `POST` | `/chat` | Start session: body `{message: <raw SOLS>}` → `201 {session_id, reply}` |
| `POST` | `/chat/{session_id}` | Follow-up message → `{session_id, reply}` |
| `GET` | `/chat/{session_id}` | Full history (assistant messages include model/tokens/cost) |
| `GET` | `/test-records` / `/test-records/{name}` | Serve the 12 synthetic SOLS fixtures in `app/test_records/` |

---

## LLM Integration

- **Model:** Google Gemini (`GEMINI_MODEL`, default `gemini-2.0-flash-001`) via `langchain-google-genai`
- **Cost tracking:** per-message input/output/cached tokens and USD cost computed in `llm/pricing.py`, surfaced in every API reply
- **Cost efficiency:** handbook is fetched once per session and cached in graph state; subject/major details are pulled on demand via batched tool calls instead of living permanently in the prompt

---

## Repo Map

```
app/
├── main.py                  # FastAPI entry, lifespan (DB + checkpointer setup)
├── core/                    # config, async DB engine, LangGraph checkpointer
├── api/v1/                  # chat + test-records routers
├── agents/
│   ├── graph.py             # StateGraph: parse_input → agent ⇄ tools
│   ├── skills.py            # tool adapters (agent skills pattern)
│   └── history.py           # history + cost reconstruction from checkpoints
├── services/                # pii, sols_parser, handbook/kb/knowledge services, chat service
├── prompts/                 # system prompt + per-turn builder
├── models/                  # Handbook, Subject, Major, ChatSession
├── schemas/                 # request/response pydantic models
├── knowledge/               # static UOW policy topic markdown
└── test_records/            # 12 synthetic SOLS fixtures

scripts/
├── scrape_courseloop.py     # crawl UOW handbook site → seeds/scraped/*.json
└── build_knowledge_base.py  # scraped JSON → seeds/kb/ markdown cards

seeds/
├── seed.py                  # single seed entry point: handbook + subject/major KB
├── scraped/                 # raw crawler output (JSON)
└── kb/                      # reviewable markdown cards + INDEX.md

migrations/                  # Alembic (head: e7a8b9c0d1e2 — subject/major tables)
```

---

## Setup / Operations

```bash
pip install -r requirements.txt
cp .env.example .env                          # DATABASE_URL, GEMINI_API_KEY, ...
make migrate-up                               # apply migrations
python scripts/scrape_courseloop.py 766 2026  # refresh scraped data (optional — committed)
python scripts/build_knowledge_base.py 766    # rebuild cards (optional — committed)
make seed                                     # handbook + subject/major KB
make run-dev                                  # http://localhost:7777
```

---

## Status vs Sponsor Requirements (Week 12 meeting)

| Requirement | Status |
|-------------|--------|
| LangGraph agent + skills pattern (handbook, majors, subjects) | ✅ Implemented |
| PII filtering of enrolment record (keep grades) | ✅ Implemented |
| No registration required | ✅ Implemented |
| Handbook links in the study plan table | ✅ Prompt + per-subject URLs in KB |
| Elective section link when discussing electives | ✅ Prompt instruction |
| Cost tracking per message | ✅ Implemented |
| LLM self-testing before output | ⏳ Deferred (verification node candidate) |
| Testing report / eval harness over test_records | ⏳ Deferred |
| User-supplied API keys | ⏳ Deferred (frontend/tech decision pending) |
