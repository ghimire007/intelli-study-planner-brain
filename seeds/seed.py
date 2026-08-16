"""
Seed script — inserts handbook data plus the subject/major knowledge base.
Run via: make seed  (or: python -m seeds.seed)

Handbook data is inline below. Subject/major data comes from seeds/scraped/
(produced by scripts/scrape_courseloop.py) with markdown cards from seeds/kb/
(produced by scripts/build_knowledge_base.py); those sections are skipped with
a warning if the scraped files aren't present. Handbook rows are insert-only;
subject/major rows are upserted so a fresh scrape can be re-seeded safely.
"""
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.handbook import Handbook
from app.models.major import Major
from app.models.subject import Subject

SEEDS_DIR = Path(__file__).resolve().parent
KB_COURSES = ("766", "1807", "1838")
KB_YEAR = 2026

HANDBOOK_766_2026_WOLLONGONG = """# 766 — Bachelor of Computer Science (Wollongong Campus, 2026 Handbook)

## Global Rules
- Total **144 credit points (CP)** required to graduate.
- Maximum **60 CP** of 100-level subjects (subject codes with a 1xx number, e.g. CSIT110) — including those already completed.
- **CSIT321 (Capstone) = 12 CP**; every other subject = 6 CP. Never count CSIT321 as 6 CP.
- Do NOT invent subject codes. Only use codes that appear in this handbook or the student's enrolment record.
- A subject counts toward exactly ONE category: Core, Core Selection, Major Core, or Elective. No double-counting.

---

## (A) Core Subjects — Complete ALL

> **Commencement year rule:** CSIT314 is **NOT** a core subject for students who commenced **2023 or before**. Remove it from the core list when auditing or planning for those students.

| Subject Code | Session Availability | Prerequisites |
|-------------|---------------------|--------------|
| CSIT110 | Autumn or Spring | None |
| CSIT123 | Autumn | None |
| CSIT114 | Autumn | None |
| CSIT115 | Autumn or Spring | None |
| CSIT121 | Autumn or Spring | CSIT110 OR CSIT111 OR ENGG100 |
| CSIT127 | Spring | None |
| CSIT128 | Autumn or Spring | None |
| CSCI235 | Autumn | CSIT115 |
| CSIT214 | Autumn or Spring | CSIT114 |
| CSIT205 | Autumn | None |
| CSCI203 | Spring | (CSIT110 OR CSIT111) AND (CSIT113 OR CSIT123) |
| CSIT226 | Spring | None |
| CSIT314 | Autumn | CSIT214 AND 12 CP at 200-level (2024+ cohort only) |

### Equivalency / Replacement Rules
If a student holds BOTH a subject and its replacement, the **replacement becomes an elective**.

| Replacement Code | Replaces Core Subject | Session | Note |
|-----------------|----------------------|---------|------|
| CSIT111 | CSIT110 | Autumn or Spring | CSIT111 satisfies all CSIT110 prerequisites throughout |
| CSIT113 | CSIT123 | Autumn or Spring | CSIT113 satisfies all CSIT123 prerequisites throughout |
| MATH255 | CSIT205 | Autumn or Spring | Either MATH255 or MATH221 replaces CSIT205 |
| MATH221 | CSIT205 | Autumn or Spring | Either MATH255 or MATH221 replaces CSIT205 |

---

## (B) Core Selection — Complete ONE

| Subject Code | Session Availability | Prerequisites |
|-------------|---------------------|--------------|
| CSCI251 | Spring | CSIT121 OR CSIT213 |
| CSIT213 | Autumn | CSIT110 OR CSIT111 |

**If BOTH CSCI251 and CSIT213 are complete:** CSCI251 satisfies the Core Selection; CSIT213 becomes an elective.

---

## (C) Capstone — CSIT321 (12 CP)

| Subject Code | CP | Session | Prerequisites | Corequisites |
|-------------|-----|---------|--------------|-------------|
| CSIT321 | 12 | Annual: Part 1 = Autumn, Part 2 = Spring | CSIT214 AND 18 CP at 200-level CSCI/CSIT/ISIT | CSIT226 |

**Scheduling rules:**
- CSIT321 spans exactly **two consecutive sessions**: Autumn (Part 1) then the following Spring (Part 2).
- If the student was enrolled in Part 1 in the **immediately preceding session**, they MUST be enrolled in Part 2 in the current session — do not insert a gap.
- Schedule CSIT321 only after all prerequisites are fully satisfied (not merely enrolled).
- CSIT226 must be complete or co-enrolled alongside Part 1.

---

## (D) Major Core Subjects — Complete ALL subjects in the declared major

If no major is declared, skip this section and use the **No-Major Path** below.
For a **double major**, list requirements for BOTH majors. At most **ONE subject** may be cross-counted between the two majors.

### AI & Big Data (AIBD) — Complete ALL 4

| Subject Code | Session | Prerequisites |
|-------------|---------|--------------|
| CSCI218 | Spring | (CSIT110 OR CSIT111) AND 18 CP at 100-level |
| CSCI316 | Autumn | CSCI203 |
| CSCI323 | Autumn | (CSIT110 OR CSIT111) AND 12 CP of 200-level CSCI/CSIT |
| ISIT312 | Spring | CSIT115 AND 18 CP at 200-level |

### Cybersecurity (CySe) — Complete ALL 4

| Subject Code | Session | Prerequisites |
|-------------|---------|--------------|
| CSCI262 | Spring | CSIT121 AND CSIT115 AND CSIT127 |
| CSCI369 | Spring | (CSIT110 OR CSIT111) AND 18 CP at 200-level |
| CSIT302 | Autumn | CSIT127 AND 12 CP at 100-level CSIT |
| CSIT375 | Autumn | CSIT121 AND CSIT127 AND 18 CP at 200-level |

### Digital Systems Security (DSS) — Complete ALL 4

| Subject Code | Session | Prerequisites | Corequisites |
|-------------|---------|--------------|-------------|
| CSCI262 | Spring | CSIT121 AND CSIT115 AND CSIT127 | None |
| CSCI361 | Autumn | CSIT121 AND 12 CP of 200-level CSCI | None |
| CSCI368 | Spring | CSIT127 AND CSIT121 AND 12 CP of 200-level CSCI/CSIT | None |
| CSIT328 | Autumn | (CSIT110 OR CSIT111) AND CSIT128 | 12 CP at 200-level |

### Game and Mobile Development (GMD) — Complete ALL 4

| Subject Code | Session | Prerequisites | Corequisites |
|-------------|---------|--------------|-------------|
| CSCI336 | Spring | CSIT121 AND 18 CP at 200-level | None |
| CSCI356 | Spring | CSIT121 | CSIT214 |
| CSCI388 | Autumn | CSIT121 AND 18 CP at 200-level | None |
| CSIT242 | Autumn | CSIT121 | CSIT213 |

### Software Engineering (SE) — Complete ALL 4

| Subject Code | Session | Prerequisites | Corequisites |
|-------------|---------|--------------|-------------|
| CSCI318 | Spring | (CSIT121 AND CSIT214) OR (ECTE250 AND CSCI291) | None |
| CSCI334 | Autumn | CSIT121 AND CSIT214 | None |
| CSIT377 | Spring | CSIT128 AND 6 CP at 200-level | 12 CP at 200-level |
| ISIT219 | Autumn | CSIT128 | None |

> **SE Commencement Year Rule:** For SE students who commenced **2023 or before**: ISIT219 is **NOT** an SE major core. CSIT314 **IS** an SE major core for those students (treat it as both a core subject exemption AND a major core requirement).

---

## No-Major Path (if no major is declared)

Complete **24 CP** from CSCI/CSIT/ISIT subjects **not already in Core or Core Selection**, as follows:
- **18 CP** of 300-level CSCI/CSIT/ISIT subjects (subject codes with a 3xx number)
- **6 CP** at 200-level OR 300-level CSCI/CSIT/ISIT subjects

No subject used here may already appear in Core or Core Selection.

---

## Electives

Fill any remaining CP to reach 144 total. Valid elective sources:
- Any CSIT/CSCI/ISIT subject not already counted in Core, Core Selection, Major Core, or No-Major path
- General Schedule subjects (from any UOW faculty)
- **100-level cap:** total 100-level CP across the entire degree (complete + planned) must not exceed 60 CP
- **Do not invent subject codes.** If a specific elective code is not available, write "Elective (200-level)" or "Elective (300-level)" as a placeholder rather than fabricating a code.

---

## Unspecified Credits

Unspecified credits count toward the total CP and toward the 100-level cap based on their listed level. Include them in the Stage 1 total.

---

## Student Enrolment Record Format

The enrolment record is a table with the following columns:

    Year | Session | Campus | Delivery | Subject Code | NomCP | Mark | Grade | Status

A subject is **Complete** if ALL of the following are true:
- Grade is one of: **HD, D, C, P, PS, S**
- Status is **"Complete"**
- OR it is listed as a **Specified Credit**

Grades F, N, NH, W, WF, AF, or any blank Grade do **NOT** count as complete.

Specified Credits table format: `Course | Subject Code | Name | Level | NomCP`
Unspecified Credits table format: `Course | Level | NomCP`

---

## STAGE 1: ANALYSIS (Audit of Completed Credits)

Complete this stage in full before starting Stage 2.

**Step 1.1 — Commencement Year and Major:**
Identify the student's commencement year (earliest year in the enrolment record). Identify declared major(s), if any. Note whether commencement year is 2023 or before.

**Step 1.2 — Apply Equivalency Rules:**
Before categorising, resolve all replacements:
- CSIT111 present → treat as CSIT110 for core and prerequisite purposes. If CSIT110 also present, CSIT111 is an elective.
- CSIT113 present → treat as CSIT123 for core and prerequisite purposes. If CSIT123 also present, CSIT113 is an elective.
- MATH255 or MATH221 present → satisfies CSIT205 core. If CSIT205 is also present, the math subject is an elective.
- Apply commencement year rule for CSIT314 and (if SE major) for ISIT219.

**Step 1.3 — Identify Complete Subjects:**
List every subject that is Complete (per the definition above). Then categorise each as exactly one of:

| Category | Rule |
|----------|------|
| Core | Appears in Section A core list, adjusted for commencement year |
| Core Selection | One qualifying subject from Section B (CSCI251 takes priority if both present) |
| Major Core | Appears in the declared major's list in Section D |
| Elective | Everything else (including "losing" replacements and discontinued subjects) |

**Step 1.4 — Count CP per category:**
Sum CP for Core, Core Selection, Major Core, Electives. Remember: CSIT321 = 12 CP, all others = 6 CP.

**Step 1.5 — Total Complete CP:**
Total Complete CP = Core CP + Core Selection CP + Major Core CP + Elective CP + Unspecified CP

⚠️ **DOUBLE CHECK Stage 1 before continuing:**
1. Is the commencement year correct?
2. Is CSIT314 correctly included or excluded from Core based on commencement year?
3. Does each subject appear in exactly ONE category?
4. Is CSIT321 counted as 12 CP?
5. Does the arithmetic add up?
Correct any errors and repeat until all checks pass.

---

## STAGE 2: PLANNING (Drafting the Study Plan)

Start only after Stage 1 is fully verified.

**Step 2.1 — List Outstanding Mandatory Subjects:**
Identify subjects not completed in Stage 1 that are still required:
- All remaining Core subjects (per commencement year rule)
- Core Selection (if neither CSCI251 nor CSIT213 is complete)
- All remaining Major Core subjects for each declared major
- CSIT321 if not already complete

**Step 2.2 — Assign Sessions:**
Schedule each subject into the correct session based on Section A–D availability:
- Autumn-only subjects → only Autumn
- Spring-only subjects → only Spring
- Autumn-or-Spring subjects → choose whichever fits the plan
- A subject missed in its only available session incurs a one-year delay — flag this clearly if it occurs.

**Step 2.3 — Enforce Prerequisites and Corequisites:**
For every subject being scheduled:
- All prerequisites must be **Complete** (Stage 1) or planned in a **strictly earlier** session.
- All corequisites must be **Complete** or planned in the **same or earlier** session.
- "CP at level X" prerequisites: count only Complete CP or CP planned in earlier sessions.
- Never assume a corequisite satisfies a prerequisite.

**Step 2.4 — Schedule CSIT321:**
- Place Part 1 (Autumn) in the final year.
- Place Part 2 (Spring) in the immediately following session.
- If the student was already enrolled in Part 1 last session, Part 2 must appear in the current session.

**Step 2.5 — Session Load Cap:**
Each session must contain at most **4 subjects**. Redistribute if any session exceeds this.

**Step 2.6 — Calculate Required Remaining CP:**
Required CP = 144 − Total Complete CP (from Stage 1.5)

**Step 2.7 — Add Electives:**
Add elective subjects (using valid sources listed above) until total planned CP equals Required CP from Step 2.6. Do not invent subject codes; use a placeholder "Elective (level)" if needed.

⚠️ **DOUBLE CHECK Stage 2 before outputting:**
1. Total Complete CP (Stage 1) + Total Planned CP = exactly 144
2. No subject appears more than once across the entire plan
3. Every subject's prerequisites are satisfied in a strictly earlier session
4. Every corequisite is satisfied in the same or earlier session
5. All Autumn-only subjects are in Autumn sessions; all Spring-only subjects are in Spring sessions
6. No session has more than 4 subjects
7. CSIT321 spans exactly two consecutive sessions (Autumn → Spring)
8. Total 100-level CP (complete + planned) does not exceed 60 CP
9. No subject code has been invented
Correct any errors and repeat until all nine checks pass.
"""

# Handbook data for 1807 Bachelor of Information Technology (Wollongong Campus, 2026)
HANDBOOK_1807_2026_WOLLONGONG = """# 1807 — Bachelor of Information Technology (Wollongong Campus, 2026 Handbook)


## Global Rules

To qualify for the award of Bachelor of Information Technology, complete **144 credit points** and satisfy all course requirements:

- **(a) Core — 96 CP:** Complete all core subjects listed in Section A (**including CSIT321** at 12 CP). Core totals **96 CP** (Y1 42 + Y2 36 + CSIT314 6 + CSIT321 12).
- **(b) Major (optional, Wollongong):** To qualify for a major, complete **24 CP** from that major's list (Section B).
- **(c) No-major path (Wollongong):** If not undertaking a major, in addition to the 96 CP core, complete:
  - **18 CP** of **300-level** CSCI, CSIT or ISIT subjects, **and**
  - an additional **6 CP** subject at **200/300-level** CSCI, CSIT or ISIT
- **(d) Double major (Wollongong only):** Subjects selected must satisfy each major. UOW Coursework Rules allow a maximum of **one subject** to be cross-counted toward more than one major.
- **(e) Electives:** Elective subjects to bring the total to **144 CP**, chosen from the School of Computing and Information Technology (any CSIT, CSCI or ISIT subject **not** in the core or chosen major) **or** from the General Schedule.
- **(f) 100-level cap:** No more than **60 CP** at 100-level (complete + planned).

**Agent counting rules:**
- **CSIT321 (Capstone) = 12 CP**; every other subject = 6 CP unless stated otherwise. Never count CSIT321 as 6 CP.
- Do NOT invent subject codes. Only use codes that appear in this handbook or the student's enrolment record.
- A subject counts toward exactly ONE category among Core / Major Core / No-Major Path / Elective, except the single allowed cross-count between two majors under (d).
- This document covers the **Wollongong campus** offering only (not Liverpool or SIM). Singapore's "no major + specified core + IT/Business electives" path does **not** apply here.

---

## Pre-Execution Verification Protocol (Mandatory Reasoning Steps)

Before writing any response or constructing tables:
1. **Context Window Pre-Calculation:** Execute all mathematical additions and prerequisite dependency mappings in the audit block prior to generating the table.
2. **Explicit Verification:** Never generate the `Study Plan` table without verifying that every prerequisite appears in a strictly earlier session than the subject depending on it.
3. **CP Arithmetic Strictness:** Sum each column explicitly. Ensure `Total Completed CP` + `Total Planned CP` = **144 CP** exactly.

---

## (A) Core Subjects — Complete ALL

### Year 1 Core (42 CP) — Complete ALL 7

| Subject Code | Session Availability | Prerequisites |
|-------------|---------------------|--------------|
| CSIT110 | Autumn or Spring | None |
| CSIT123 | Autumn | None |
| CSIT114 | Autumn | None |
| CSIT115 | Autumn or Spring | None |
| CSIT121 | Autumn or Spring | CSIT110 OR CSIT111 OR ENGG100 |
| CSIT127 | Spring | None |
| CSIT128 | Autumn or Spring | None |

### Year 2 Core (36 CP) — Complete ALL 6

| Subject Code | Session Availability | Prerequisites |
|-------------|---------------------|--------------|
| CSIT205 | Autumn | None |
| CSIT214 | Autumn or Spring | CSIT114 |
| CSIT226 | Spring | None |
| CSIT305 | Spring | None |
| ISIT219 | Autumn | CSIT128 |
| ISIT224 | Spring | (CSIT113 OR CSIT123 OR BUS 101) AND another 18 CP at 100-level |

### Year 3 Core (18 CP) — Complete ALL

| Subject Code | CP | Session Availability | Prerequisites | Corequisites |
|-------------|-----|---------------------|--------------|-------------|
| CSIT314 | 6 | Autumn | CSIT214 AND 12 CP at 200-level CSCI/ISIT | None |
| CSIT321 | 12 | Two consecutive sessions (start session flexible) | CSIT214 AND an additional 18 CP at 200-level CSCI/CSIT/ISIT | CSIT226 AND CSIT314 |

**CSIT321 is Core** and counts **12 CP** toward the **96 CP** core total (Year 1 42 + Year 2 36 + CSIT314 6 + CSIT321 12 = 96). Do **not** categorise CSIT321 as Elective or as a separate non-core bucket.

**CSIT321 scheduling rules:**
- Spans exactly **two consecutive sessions** (Part 1 then Part 2). There must be **no gap** between parts.
- **Start session is flexible:** Part 1 may begin in **Autumn or Spring**, whichever fits the student's plan, provided all prerequisites and corequisites are satisfied.
  - Example: Part 1 in **Spring**, Part 2 in the following **Autumn**.
  - Example: Part 1 in **Autumn**, Part 2 in the following **Spring**.
- If the student was enrolled in Part 1 in the **immediately preceding session**, they MUST be enrolled in Part 2 in the current session — do not insert a gap.
- Schedule CSIT321 only after all prerequisites are fully satisfied (not merely enrolled).
- CSIT226 and CSIT314 must be complete or co-enrolled as required by the corequisite rule.

### Equivalency / Replacement Rules

Official core replacement (Wol/Liv):

| Code | Role | Session | Note |
|------|------|---------|------|
| CSIT205 | Current core | Autumn | Replacement of **MATH255** since **2024** |
| MATH255 | Former core | — (no longer offered) | Replaced by **CSIT205** since **2024** |

**How to apply:**
- MATH255 complete → satisfies the **CSIT205** core requirement. Do not also require CSIT205.
- If the student holds **BOTH** MATH255 and CSIT205 → **CSIT205** counts as Core; **MATH255** becomes an elective.
- Do not schedule MATH255 for current students; use CSIT205.

**Prerequisite alternates** (not core replacements — accepted in prereq clauses where listed):
- CSIT111 may satisfy CSIT110 where a prereq says `CSIT110 OR CSIT111`
- CSIT113 may satisfy CSIT123 where a prereq says `CSIT113 OR CSIT123`

---

## (B) Major Core Subjects — Complete ALL subjects in the declared major

Wollongong majors (**24 CP** each). Select **one or two** majors (see Global Rules (b) and (d)).
Note: 300-level subjects in a major may require 100/200-level prerequisites that are **not** listed inside the major — look those up via `lookup_subjects_tool` / `lookup_major_tool`.

If no major is declared, skip this section and use the **No-Major Path** below.
For a **double major**, ensure subjects satisfy **both** majors. At most **ONE subject** may be cross-counted between the two majors (Global Rule (d)).

### Web Design and Development (MAJ40246) — Complete ALL 4

| Subject Code | Session | Prerequisites | Corequisites |
|-------------|---------|--------------|-------------|
| ISIT207 | Spring | (CSIT110 OR CSIT111) AND CSIT128 | None |
| CSIT377 | Spring | CSIT128 AND 6 CP at 200-level | 12 CP at 200-level |
| ISIT307 | Autumn | (CSIT110 OR CSIT111) AND CSIT115 AND CSIT128 AND 12 CP at 200-level | None |
| CSIT328 | Autumn | (CSIT110 OR CSIT111) AND CSIT128 | 12 CP at 200-level |

### Network Design and Management (MAJ40163) — Complete ALL 4

| Subject Code | Session | Prerequisites | Corequisites |
|-------------|---------|--------------|-------------|
| ISIT212 | Autumn | ISIT105 OR CSIT127 | None |
| CSCI322 | Spring | CSIT127 AND 18 CP at 200-level | None |
| ISIT302 | Autumn | CSIT127 AND 6 CP at 200-level | 12 CP at 200-level |
| CSIT302 | Autumn | CSIT127 AND 12 CP at 100-level CSIT | None |

---

## No-Major Path (if no major is declared)

Wollongong / Liverpool rule (Global Rule (c)(ii)) — in addition to the **96 CP** core:

- **18 CP** of **300-level** CSCI, CSIT or ISIT subjects (not already in Core)
- **6 CP** at **200-level OR 300-level** CSCI, CSIT or ISIT (not already in Core)

Then fill remaining CP with electives (Global Rule (e)) to reach 144.

No subject used on this path may already appear in Core.

---

## Electives

Elective subjects bring the total to **144 CP** (Global Rule (e)). Valid sources:
- Any CSIT, CSCI or ISIT subject **not** already counted in Core or the chosen major(s) / No-Major Path
- General Schedule subjects
- **100-level cap:** total 100-level CP across the entire degree (complete + planned) must not exceed **60 CP** (Global Rule (f))
- **Do not invent subject codes.** If a specific elective code is not available, write "Elective (200-level)" or "Elective (300-level)" as a placeholder rather than fabricating a code.

---

## Unspecified Credits

Unspecified credits count toward the total CP and toward the 100-level cap based on their listed level. Include them in the Stage 1 total.

---

## Student Enrolment Record Format

The enrolment record is a table with the following columns:

    Year | Session | Campus | Delivery | Subject Code | NomCP | Mark | Grade | Status

A subject is **Complete** if ALL of the following are true:
- Grade is one of: **HD, D, C, P, PS, S**
- Status is **"Complete"**
- OR it is listed as a **Specified Credit**

Grades F, N, NH, W, WF, AF, or any blank Grade do **NOT** count as complete.

Specified Credits table format: `Course | Subject Code | Name | Level | NomCP`
Unspecified Credits table format: `Course | Level | NomCP`

---

## STAGE 1: ANALYSIS (Audit of Completed Credits)

Complete this stage in full before starting Stage 2.

**Step 1.1 — Commencement Year and Major:**
Identify the student's commencement year (earliest year in the enrolment record). Identify declared major(s), if any (MAJ40246 and/or MAJ40163 for Wollongong).

**Step 1.2 — Apply Equivalency Rules:**
Before categorising, resolve replacements:
- MATH255 present → treat as satisfying CSIT205 core. If CSIT205 is also present, MATH255 is an elective.
- Apply prerequisite alternates (CSIT111 / CSIT113) only where a later subject's prereq clause allows them.

**Step 1.3 — Identify Complete Subjects:**
List every subject that is Complete (per the definition above). Then categorise each as exactly one of:

| Category | Rule |
|----------|------|
| Core | Appears in Section A (Years 1–3), **including CSIT321** (12 CP toward the 96 CP core) |
| Major Core | Appears in the declared major's list in Section B |
| Elective | Everything else (including "losing" replacements and discontinued subjects) |

Never put CSIT321 in Elective — it is always Core when present (complete or enrolled toward the degree).

**Step 1.4 — Count CP per category:**
Sum CP for Core, Major Core, Electives. Remember: **CSIT321 = 12 CP** and those 12 CP belong in **Core** (part of the 96 CP core), all other listed subjects = 6 CP unless stated otherwise.

**Step 1.5 — Total Complete CP:**
Total Complete CP = Core CP + Major Core CP + Elective CP + Unspecified CP

⚠️ **STRICT PRE-EXECUTION CHECK — Stage 1:**
Before moving to Stage 2, explicitly confirm:
1. Is commencement year verified?
2. Is each completed subject in exactly ONE category?
3. Is CSIT321 categorised as **Core** (not Elective) and counted as **12 CP** toward the 96 CP core?
4. Does Core CP + Major Core CP + Elective CP + Unspecified = Total Complete CP?
5. Are declared majors correctly identified (or no-major path selected)?
Correct any errors and repeat until all checks pass.

---

## STAGE 2: PLANNING (Drafting the Study Plan)

Start only after Stage 1 is fully verified.

**Step 2.1 — List Outstanding Mandatory Subjects:**
Identify subjects not completed in Stage 1 that are still required:
- All remaining Core subjects in Section A (**including CSIT321** if not complete — it is part of the 96 CP core)
- All remaining Major Core subjects for each declared major (Section B) or No-Major Path requirements

**Step 2.2 — Assign Sessions:**
Schedule each subject into the correct session based on Section A–B availability:
- Autumn-only subjects → only Autumn
- Spring-only subjects → only Spring
- Autumn-or-Spring subjects → choose whichever fits the plan
- A subject missed in its only available session incurs a one-year delay — flag this clearly if it occurs.

**Step 2.3 — Enforce Prerequisites and Corequisites:**
For every subject being scheduled:
- All prerequisites must be **Complete** (Stage 1) or planned in a **strictly earlier** session.
- All corequisites must be **Complete** or planned in the **same or earlier** session.
- "CP at level X" prerequisites: count only Complete CP or CP planned in earlier sessions.
- Never assume a corequisite satisfies a prerequisite.
- Prefer `lookup_subjects_tool` to verify prereqs/sessions before finalising.

**Step 2.4 — Schedule CSIT321:**
- Place Part 1 in the final year in **either Autumn or Spring**, whichever fits once prerequisites and corequisites are satisfied.
- Place Part 2 in the **immediately following** session (Spring→Autumn or Autumn→Spring).
- If the student was already enrolled in Part 1 last session, Part 2 must appear in the current session.
- Ensure CSIT226 and CSIT314 corequisites are satisfied.

**Step 2.5 — Session Load Cap:**
Each session must contain at most **4 subjects**. Redistribute if any session exceeds this.

**Step 2.6 — Calculate Required Remaining CP:**
Required CP = 144 − Total Complete CP (from Stage 1.5)

**Step 2.7 — Add Electives:**
Add elective subjects (using valid sources listed above) until total planned CP equals Required CP from Step 2.6. Do not invent subject codes; use a placeholder "Elective (level)" if needed.

**Step 2.8 — Stage 2 Pre-Execution Validation Checklist (Run BEFORE rendering output):**
Before generating the visible Markdown table and JSON block, verify each item sequentially:
1. **Total CP Check:** Does `Total Complete CP` + `Total Planned CP` = exactly **144 CP**?
2. **Prerequisite Check:** Is EVERY subject's prerequisite completed in a strictly earlier session? (List each pair mentally: `Prereq (Session N-1)` -> `Subject (Session N)`).
3. **Corequisite Check:** Are all corequisites planned in the same or an earlier session?
4. **Session Match:** Are Autumn-only subjects in Autumn? Spring-only subjects in Spring?
5. **Session Capacity:** Does any session exceed 4 subjects (24 CP)?
6. **Capstone Gap Rule:** Does CSIT321 span two consecutive sessions with zero gap?
7. **100-Level Cap:** Is total 100-level CP (Completed + Planned) ≤ **60 CP**?
8. No subject appears more than once across the entire plan, unless the status is failed
9. No subject code has been invented
If any item fails, adjust the plan and re-run Step 2.8.
"""


# Handbook data for 1838 Bachelor of Business Information Systems (Wollongong Campus, 2026)
# DRAFT from seeds/scraped/course_1838.json + subjects_1838.json — verify global rules
# and sessions against the live CourseLoop handbook before production use.
HANDBOOK_1838_2026_WOLLONGONG = """# 1838 — Bachelor of Business Information Systems (Wollongong Campus, 2026 Handbook)

> **Author note:** Draft distilled from CourseLoop scrape. No majors are offered on this
> degree at Wollongong. Confirm award wording, sessions, and prerequisites against the
> official handbook before use.

## Global Rules

To qualify for the award of Bachelor of Business Information Systems, complete **144 credit points** and satisfy all course requirements:

- **(a) Core — 96 CP:** Complete all core subjects listed in Section A (**including CSIT321** at 12 CP). Core totals **96 CP** (Y1 48 + Y2 IT core 30 + CSIT314 6 + CSIT321 12).
- **(b) No majors:** This degree has **no major** at Wollongong — do not apply 1807/766 major rules.
- **(c) Year 2 Business electives — 18 CP:** Select **3** subjects from the Business Electives List (Section B), not already counted in Core.
- **(d) Year 3 structured electives — 30 CP:** In addition to Y3 Core (CSIT314 + CSIT321):
  - **6 CP** — **1** subject from the Business Electives List (Section B), and
  - **24 CP** — **1** subject at **200/300-level** CSCI/CSIT/ISIT **and 3** subjects at **300-level** CSCI/CSIT/ISIT (not already in Core).
- **(e) 100-level cap:** No more than **60 CP** at 100-level (complete + planned).

**Agent counting rules:**
- **CSIT321 (Capstone) = 12 CP**; every other listed subject = 6 CP unless stated otherwise. Never count CSIT321 as 6 CP.
- Do NOT invent subject codes. Only use codes that appear in this handbook or the student's enrolment record.
- A subject counts toward exactly ONE category: Core / Y2 Business Elective / Y3 Business Elective / Y3 CSIT Elective.
- This document covers the **Wollongong campus** offering only (not Liverpool or SIM).

---

## (A) Core Subjects — Complete ALL

### Year 1 Core (48 CP) — Complete ALL 8

| Subject Code | Session Availability | Prerequisites |
|-------------|---------------------|--------------|
| CSIT110 | Autumn or Spring | None |
| CSIT115 | Autumn or Spring | None |
| CSIT121 | Autumn or Spring | CSIT110 OR CSIT111 OR ENGG100 |
| CSIT128 | Autumn or Spring | None |
| CSIT127 | Spring | None |
| MGNT110 | Spring | None |
| CSIT123 | Autumn | None |
| CSIT114 | Autumn | None |

### Year 2 Core — IT subjects (30 CP) — Complete ALL 5

| Subject Code | Session Availability | Prerequisites |
|-------------|---------------------|--------------|
| CSIT214 | Autumn or Spring | CSIT114 |
| CSIT205 | Autumn or Spring | None |
| CSIT226 | Spring | None |
| ISIT224 | Spring | (CSIT113 OR CSIT123 OR BUS 101) AND another 18 CP at 100-level |
| CSIT305 | Spring | None |

### Year 3 Core (18 CP) — Complete ALL

| Subject Code | CP | Session Availability | Prerequisites | Corequisites |
|-------------|-----|---------------------|--------------|-------------|
| CSIT314 | 6 | Autumn | CSIT214 AND 12 CP at 200-level CSCI/ISIT | None |
| CSIT321 | 12 | Two consecutive sessions (start session flexible) | CSIT214 AND an additional 18 CP at 200-level CSCI/CSIT/ISIT | CSIT226 AND CSIT314 |

**CSIT321 is Core** and counts **12 CP** toward the **96 CP** core total. Do **not** categorise CSIT321 as an elective.

**CSIT321 scheduling rules:**
- Spans exactly **two consecutive sessions** (Part 1 then Part 2). There must be **no gap** between parts.
- **Start session is flexible:** Part 1 may begin in **Autumn or Spring**, provided prerequisites and corequisites are satisfied.
- If the student was enrolled in Part 1 in the **immediately preceding session**, they MUST be enrolled in Part 2 in the current session.
- CSIT226 and CSIT314 must be complete or co-enrolled as required by the corequisite rule.

### Equivalency / Replacement Rules

**Prerequisite alternates** (not core replacements — accepted in prereq clauses where listed):
- CSIT111 may satisfy CSIT110 where a prereq says `CSIT110 OR CSIT111`
- CSIT113 may satisfy CSIT123 where a prereq says `CSIT113 OR CSIT123`
- Completing **BUS 101** satisfies the BUS 101 prerequisite branch of ISIT224 (i.e. no alternate subject substitutes for it — BUS 101 must be taken directly to meet that branch)

---

## (B) Business Electives List (Wollongong)

Used for **Year 2** (3 × 6 CP = 18 CP) and **Year 3** (1 × 6 CP). Subjects must **not** already be counted as Core.

| Subject Code | Title |
|-------------|-------|
| ECON100 | Economic Essentials for Business |
| ACCY121 | Accounting for Decision Making |
| MARK101 / MARK213 | Marketing Principles (same subject) |
| ACCY122 | Accounting Principles |
| BUS 101 | Principles of Responsible Business |
| BUS 121 | Statistics for Business |
| MGNT102 | Professional Communication: Concepts and Practices |
| MGNT201 | Organisational Behaviour |
| MGNT206 | Strategic Human Resource Management |
| MGNT220 | Understanding Organisations |
| MGNT311 | Management of Change |

**Note:** MGNT110 is **Core** (Year 1), not a Business Elective.

---

## (C) Year 3 CSIT/CSCI/ISIT Electives (24 CP)

Complete **after** Core requirements, in the final year structure:

- **6 CP** — one **200-level or 300-level** CSCI/CSIT/ISIT subject (not in Core)
- **18 CP** — three **300-level** CSCI/CSIT/ISIT subjects (not in Core)

Use `lookup_subjects_tool` to verify level, prerequisites, and session availability before finalising.

---

## Electives — General

Any remaining CP to reach 144 is satisfied by the structured buckets above (Y2 business + Y3 business + Y3 CSIT). Do not invent codes — use placeholders such as "Business Elective" or "CSIT Elective (300-level)" if a specific code is unavailable.

---

## Unspecified Credits

Unspecified credits count toward the total CP and toward the 100-level cap based on their listed level. Include them in the Stage 1 total.

---

## Student Enrolment Record Format

The enrolment record is a table with the following columns:

    Year | Session | Campus | Delivery | Subject Code | NomCP | Mark | Grade | Status

A subject is **Complete** if ALL of the following are true:
- Grade is one of: **HD, D, C, P, PS, S**
- Status is **"Complete"**
- OR it is listed as a **Specified Credit**

Grades F, N, NH, W, WF, AF, or any blank Grade do **NOT** count as complete.

Specified Credits table format: `Course | Subject Code | Name | Level | NomCP`
Unspecified Credits table format: `Course | Level | NomCP`

---

## STAGE 1: ANALYSIS (Audit of Completed Credits)

Complete this stage in full before starting Stage 2.

**Step 1.1 — Commencement Year:**
Identify the student's commencement year (earliest year in the enrolment record). This degree has **no major** — do not ask for or apply a major.

**Step 1.2 — Apply Equivalency Rules:**
Apply prerequisite alternates from Section A only where a later subject's prereq clause allows them.

**Step 1.3 — Identify Complete Subjects:**
List every subject that is Complete. Categorise each as exactly one of:

| Category | Rule |
|----------|------|
| Core | Appears in Section A (**including CSIT321** at 12 CP toward the 96 CP core) |
| Y2 Business Elective | One of the 3 business electives taken in Year 2 (from Section B, not Core) |
| Y3 Business Elective | The 1 business elective in Year 3 (from Section B, not Core) |
| Y3 CSIT Elective | The 4 CSIT/CSCI/ISIT electives in Year 3 (1×200/300 + 3×300 per Section C) |

Never put CSIT321 in an elective category.

**Step 1.4 — Count CP per category:**
Sum CP per category. **CSIT321 = 12 CP** in Core; all other listed subjects = 6 CP unless stated otherwise.

**Step 1.5 — Total Complete CP:**
Total Complete CP = Core CP + Y2 Business Elective CP + Y3 Business Elective CP + Y3 CSIT Elective CP + Unspecified CP

Target when fully complete: Core **96 CP** + structured electives **48 CP** = **144 CP**.

⚠️ **DOUBLE CHECK Stage 1 before continuing:**
1. Is the commencement year correct?
2. Does each subject appear in exactly ONE category?
3. Is CSIT321 categorised as **Core** (not Elective) and counted as **12 CP** toward the 96 CP core?
4. Are Y2 business electives counted separately (up to 18 CP)?
5. Does the arithmetic add up toward 144 CP?
Correct any errors and repeat until all checks pass.

---

## STAGE 2: PLANNING (Drafting the Study Plan)

Start only after Stage 1 is fully verified.

**Step 2.1 — List Outstanding Mandatory Subjects:**
- All remaining **Core** subjects in Section A (including CSIT321 if not complete)
- Remaining **Y2 business electives** (until 18 CP)
- Remaining **Y3 business elective** (6 CP)
- Remaining **Y3 CSIT electives** (24 CP per Section C)

**Step 2.2 — Assign Sessions:**
Schedule each subject into the correct session based on Section A availability. Autumn-only → Autumn; Spring-only → Spring; Autumn-or-Spring → choose whichever fits.

**Step 2.3 — Enforce Prerequisites and Corequisites:**
All prerequisites must be **Complete** or planned in a **strictly earlier** session. Corequisites must be **Complete** or planned in the **same or earlier** session. Prefer `lookup_subjects_tool` before finalising.

**Step 2.4 — Schedule CSIT321:**
- Part 1 in final year in **Autumn or Spring** once prerequisites/corequisites are satisfied.
- Part 2 in the **immediately following** session (no gap).
- Ensure CSIT226 and CSIT314 corequisites are satisfied.

**Step 2.5 — Session Load Cap:**
Each session must contain at most **4 subjects**.

**Step 2.6 — Calculate Required Remaining CP:**
Required CP = 144 − Total Complete CP (from Stage 1.5)

**Step 2.7 — Fill structured elective buckets:**
Allocate business and CSIT electives until structured elective CP and total CP reach 144. Do not invent subject codes.

⚠️ **DOUBLE CHECK Stage 2 before outputting:**
1. Total Complete CP + Total Planned CP = exactly **144**
2. No subject appears more than once
3. Prerequisites and corequisites satisfied
4. Session availability respected
5. No session has more than 4 subjects
6. CSIT321 spans two consecutive sessions with no gap
7. Total 100-level CP ≤ **60**
8. No subject code invented
Correct any errors and repeat until all checks pass.
"""

SEED_DATA = [
    {
        "year": 2026,
        "course": "766",
        "campus": "Wollongong",
        "information": HANDBOOK_766_2026_WOLLONGONG,
    },
    {
        "year": 2026,
        "course": "1807",
        "campus": "Wollongong",
        "information": HANDBOOK_1807_2026_WOLLONGONG,
    },
    {
        "year": 2026,
        "course": "1838",
        "campus": "Wollongong",
        "information": HANDBOOK_1838_2026_WOLLONGONG,
    },
]


async def _upsert(session, model, year: int, code: str, values: dict) -> str:
    result = await session.execute(
        select(model).where(model.year == year, model.code == code)
    )
    row = result.scalar_one_or_none()
    if row:
        for key, value in values.items():
            setattr(row, key, value)
        return "updated"
    session.add(model(year=year, code=code, **values))
    return "inserted"


async def seed_knowledge_base(session, course: str, year: int = KB_YEAR) -> None:
    """Upsert subject/major rows from seeds/scraped/ + seeds/kb/ card files."""
    plans = [
        (Subject, "subjects", SEEDS_DIR / "scraped" / f"subjects_{course}.json"),
        (Major, "majors", SEEDS_DIR / "scraped" / f"majors_{course}.json"),
    ]
    for model, kind, path in plans:
        if not path.exists():
            print(f"Skipping {kind} — {path.name} not found (run scripts/scrape_courseloop.py)")
            continue
        print(f"Seeding {kind} from {path.name} ...")
        for code, data in json.loads(path.read_text()).items():
            card_path = SEEDS_DIR / "kb" / kind / f"{code}.md"
            if not card_path.exists():
                print(f"Skipping {kind[:-1]} {code} — no card (run scripts/build_knowledge_base.py)")
                continue
            action = await _upsert(session, model, year, code, {
                "title": data["title"],
                "credit_points": int(data["cp"]),
                "url": data["url"],
                "card": card_path.read_text(),
                "data": data,
            })
            print(f"{action} {kind[:-1]} {code}")


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        for entry in SEED_DATA:
            result = await session.execute(
                select(Handbook).where(
                    Handbook.year == entry["year"],
                    Handbook.course == entry["course"],
                    Handbook.campus == entry["campus"],
                )
            )
            if result.scalar_one_or_none():
                print(f"Skipping {entry['course']} {entry['year']} ({entry['campus']}) — already exists")
                continue
            session.add(Handbook(**entry))
            print(f"Inserted {entry['course']} {entry['year']} ({entry['campus']})")
        for course in KB_COURSES:
            await seed_knowledge_base(session, course)
        await session.commit()
    print("Seed complete.")


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(seed())
