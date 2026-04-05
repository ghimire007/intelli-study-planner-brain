# IntelliStudyPlanner — Technical Implementation Guide

## System Overview

A microservice-based AI platform that generates personalised, validated study plans for UOW students via a conversational chat interface. The LLM is grounded in structured handbook data and degree rules stored in a PostgreSQL knowledge base.

---

## Architecture

### Services

| Service | Tech | Responsibility |
|---------|------|----------------|
| `brain` (this repo) | FastAPI + Python | LLM agents, knowledge engine, study plan logic |
| Frontend | React | ChatGPT-style chat UI, structured output rendering |
| Auth (future) | FastAPI + JWT | Optional user accounts, session persistence |

### Agent Architecture (LangChain / LangGraph)

```
User Input (SOLS paste)
        │
        ▼
Data Sanitisation Engine
        │
        ▼
Degree Router Agent  ──── identifies degree code (e.g. 766)
        │
        ▼
Academic Agent (e.g. CS 766 Agent)
    ├── Handbook Retrieval Tool  ──── queries handbook table
    ├── Rule Validator            ──── CP caps, prereqs, session availability
    ├── Subject Equivalency Tool  ──── maps discontinued → current subjects
    └── Plan Generator            ──── produces semester × year table
        │
        ▼
Structured Study Plan Output (JSON → React table)
```

---

## Implementation Flow

### 1. Data Ingestion — Handbook Knowledge Base

- Handbook pages scraped/parsed and stored in the `handbook` table
- Each row = one degree or major/minor for a specific year
- `information` field stores the full structured markdown (see `HANDBOOK_TEMPLATE.md`)
- Indexed on `year` + `course` for fast retrieval

### 2. Data Sanitisation Engine

- Input: raw SOLS copy-paste (semi-structured text)
- Parses: subject codes, credit points, session/year, grades, completion status
- Output: clean structured dict passed to the Academic Agent
- Key problem solved: Oracle-formatted SOLS output loses tabular alignment when pasted; this engine reconstructs it

### 3. Academic Agent (LangGraph StatefulGraph)

Each degree has a dedicated agent node. For CS 766 (initial POC):

**State tracked per conversation:**
- Completed subjects + credit points
- Current year/session
- Degree commencement year (determines which handbook rules apply)
- Declared major/electives
- Student interests (for elective recommendations)

**Validation rules enforced:**
- Total 144 CP required
- Max 60 CP at 100-level subjects
- Core subject quotas per year/session
- Prerequisite chain resolution
- Session availability (Autumn-only vs Spring-only subjects)
- Commencement year → applicable handbook rule mapping

**Subject Equivalency Logic:**
- Discontinued subjects mapped to current replacements (e.g. `ISIT204` → `CSIT305`)
- Stored inline in the handbook `information` field under `## Discontinued Subjects`

### 4. Study Plan Output

- Format: structured JSON → rendered as semester × year table in React
- Minimum: one complete plan per request
- Supports: 3 iterative refinements via multi-turn chat

### 5. LLM Integration

- Primary model: **Google Gemini 2.0** via LangChain
- Fallback: open-source model (future S2)
- Cost control: free-tier API keys (6-key rotation across team), rate limiting per session
- Prompt strategy: handbook content injected as context, degree rules as system prompt constraints

---

## Database Schema

### `handbook` table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | `BIGINT` (PK, autoincrement) | Unique row identifier |
| `year` | `INTEGER` | Handbook year (e.g. 2026) |
| `course` | `VARCHAR(255)` | Degree code (e.g. `766`) |
| `information` | `TEXT` | Full structured markdown — see `HANDBOOK_TEMPLATE.md` |

**Unique constraint:** `(year, course)` — one entry per degree per year.

**Query pattern:** `SELECT information FROM handbook WHERE course = '766' AND year = 2026`

---

## API Endpoints (Planned)

```
POST /api/v1/plan/generate      — Submit SOLS input, receive study plan
POST /api/v1/plan/refine        — Multi-turn refinement
GET  /api/v1/handbook/{course}  — Retrieve handbook entry
POST /api/v1/handbook           — Ingest new handbook entry (admin)
```

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend framework | FastAPI (Python) |
| LLM orchestration | LangChain + LangGraph |
| LLM model | Google Gemini 2.0 |
| Database | PostgreSQL (Supabase) |
| ORM | SQLAlchemy 2.0 async |
| DB driver | psycopg3 (async) |
| Frontend | React.js |
| Containerisation | Docker + Docker Compose |
| CI/CD | GitHub Actions → AWS |
| Auth (future) | JWT / OAuth2 via FastAPI |

---

## Key Technical Challenges

| Challenge | Solution |
|-----------|----------|
| SOLS input is semi-structured text | Data Sanitisation Engine pre-processes before LLM |
| Handbook rules change by commencement year | `year` field on handbook rows; agent selects by student start year |
| Discontinued subjects | Equivalency table embedded in handbook `information` markdown |
| Session availability (Autumn/Spring-only) | Encoded per subject in handbook template |
| LLM non-determinism on hard rules | LangGraph enforces rule validation as deterministic tool calls, not LLM reasoning |
| Credit point cap enforcement (max 60 CP @ 100-level) | Rule Validator node in agent graph, not LLM |

---

## Initial Scope (S1 — Weeks 5–13)

- [ ] CS 766 handbook data ingested into DB
- [ ] Data Sanitisation Engine
- [ ] CS 766 Academic Agent (LangGraph)
- [ ] Basic study plan generation endpoint
- [ ] React chat interface integrated with backend

## Future Scope (S2 — Weeks 14–26)

- [ ] BIT, PCS, BIS degree agents
- [ ] User accounts + plan persistence
- [ ] Elective recommendation engine
- [ ] Exchange student / partner university support
- [ ] Subject Equivalency Database expansion
