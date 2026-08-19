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

- **(a) Core — 96 CP:** Complete all core subjects listed in Section A (**including CSIT321** at 12 CP). 
- **(b) Major (optional):** To qualify for a major, complete **24 CP** from that major's list (Section B).
- **(c) No-major path:** If not undertaking a major, in addition to the 96 CP core, complete:
  - **18 CP** of **300-level** CSCI, CSIT or ISIT subjects, **and**
  - an additional **6 CP** subject at **200/300-level** CSCI, CSIT or ISIT
- **(d) Double major (Wollongong only):** Subjects selected must satisfy BOTH majors. The total number of subjects to be completed is 15 core subjects + 8 major subjects. No electives should be scheduled. 
- **(e) Electives:** Elective subjects to bring the total to **144 CP**. An elective is any CSIT, CSCI or ISIT subject **not** in the core or chosen major OR from the General Schedule (assume any non CSIT, CSCI or ISIT subject is a valid elective). A maximum of **24 CP** of electives can be counted towards the **144 credit points** to complete the degree. 
- **(f) 100-level cap:** No more than **60 CP** at 100-level (complete + planned).

**Agent counting rules:**
- **CSIT321 (Capstone) = 12 CP**; every other subject = 6 CP unless stated otherwise. Never count CSIT321 as 6 CP.
- Do NOT invent subject codes or names. Only use codes and names that appear in this handbook or the student's enrolment record.
- A subject counts toward exactly ONE category among Core / Major Core / No-Major Core / Elective / Excess.
- This document covers the **Wollongong campus** offering only (not Liverpool or SIM). Singapore's "no major + specified core + IT/Business electives" path does **not** apply here.

---

## (A) Core Subjects — Complete ALL

| Subject Code | Session Availability | Prerequisites |
|-------------|---------------------|--------------|
| CSIT110 | Autumn or Spring | None |
| CSIT123 | Autumn | None |
| CSIT114 | Autumn | None |
| CSIT115 | Autumn or Spring | None |
| CSIT121 | Autumn or Spring | CSIT110 OR CSIT111 OR ENGG100 |
| CSIT127 | Spring | None |
| CSIT128 | Autumn or Spring | None |
| CSIT205 | Autumn | None |
| CSIT214 | Autumn or Spring | CSIT114 |
| CSIT226 | Spring | None |
| CSIT305 | Spring | None |
| ISIT219 | Autumn | CSIT128 |
| ISIT224 | Spring | (CSIT113 OR CSIT123 OR BUS 101) AND another 18 CP at 100-level |
| CSIT314 | 6 | Autumn | CSIT214 AND 12 CP at 200-level CSCI/ISIT | None |
| CSIT321 | 12 | Two consecutive sessions (Autumn then Spring or Spring then Autumn) | CSIT214 AND an additional 18 CP at 200-level CSCI/CSIT/ISIT | CSIT226 AND CSIT314 |

**CSIT321 is Core** and counts **12 CP** toward the **96 CP** core total. Do **not** categorise CSIT321 as Elective or as a separate non-core category.

**CSIT321 scheduling rules:**
- Spans exactly **two consecutive sessions** (Part 1 then Part 2). There must be **no gap** between parts.
- **Start session is flexible:** Part 1 may begin in **Autumn or Spring**, whichever fits the student's plan, provided all prerequisites and corequisites are satisfied.
  - Example: Part 1 in **Spring**, Part 2 in the following **Autumn**.
  - Example: Part 1 in **Autumn**, Part 2 in the following **Spring**.
- If the student was enrolled in Part 1 in the **immediately preceding session**, they MUST be enrolled in Part 2 in the current session — do not insert a gap.
- Schedule CSIT321 only after all prerequisites are fully satisfied.
- CSIT226 and CSIT314 must be complete or enrolled in the same session as Part 1 as required by the corequisite rule.

### Equivalency / Replacement Rules

Official core replacement (Wol):

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
For a **double major**, ensure subjects satisfy **both** majors.

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

Wollongong rule (Global Rule (c)(ii)) — in addition to the **96 CP** core:

- **18 CP** of **300-level** CSCI, CSIT or ISIT subjects (not already in Core)
- **6 CP** at **200-level OR 300-level** CSCI, CSIT or ISIT (not already in Core)
Label these 4 subjects as No-major core. These count as **24 CP** toward the **24 CP** No-major core total. Do **not** categorise them as Elective or as a separate non-core category.

No subject used on this path may already appear in Core.

---

## Electives

Elective subjects bring the total to **144 CP** (Global Rule (e)). 
For any elective:
- Assume any non CSIT, CSCI or ISIT subject is a valid elective and is a part of the general schedule
- It can be any CSIT, CSCI or ISIT subject **not** already counted in Core or the chosen major(s) / No-Major category.
- The elective subject’s CP is added to the elective category. 
- There may be a maximum of 4 electives.
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

Grades TF, F, N, NH, W, WF, AF, or any blank Grade do **NOT** count as complete or towards the CP total.

Specified Credits table format: `Course | Subject Code | Name | Level | NomCP`
Unspecified Credits table format: `Course | Level | NomCP`

–-

## STAGE 1: ANALYSIS (Audit of Completed Credits)

Complete ALL steps in this stage in full before starting Stage 2.

**Step 1.0 — Commencement Year and Major:**
Identify the student's commencement year (earliest year in the enrolment record). Identify declared major(s), if any (MAJ40246 and/or MAJ40163 for Wollongong).

**Step 1.1 (Campus Check): 
Does the proposed study plan include any majors that are not listed in the provided Handbook for this degree?
If the answer is "Yes," flag it immediately and pause the planning process to ask for clarification or to confirm the No-Major path.

**Step 1.2 — Apply Equivalency Rules:**
Before categorising, resolve replacements:
- MATH255 present → treat as satisfying CSIT205 core. If CSIT205 is also present, MATH255 is an elective.
- Apply prerequisite alternates (CSIT111 / CSIT113) only where a later subject's prerequisite clause allows them.

**Step 1.3 — Identify Complete Subjects:**
List every subject that is Complete or enrolled. Then categorise each as exactly one of:

| Category | Rule |
|----------|------|
| Core | Appears in Section A, **including CSIT321** (12 CP toward the 96 CP core) |
| Major Core | Appears in the declared major's list in Section B |
| No-major Core | Appears in the no-major path in Section B |
| Elective | Everything else (including "losing" replacements and discontinued subjects. If a subject is not CSIT/ CSCI/ ISIT assume it is a valid elective) |

Never put CSIT321 in Elective — it is always Core when present (complete or enrolled toward the degree).

**Step 1.4 — Count CP per category:**
Sum CP for Core, Major Core, No-Major core, Electives and Excess/Non-award. Remember: **CSIT321 = 12 CP** and those 12 CP belong in **Core** (part of the 96 CP core), all other listed subjects = 6 CP unless stated otherwise.
The Elective CP category can have a maximum of 24 CP (4 subjects) counted towards the Total Valid CP total. Any CP over 24 should be placed in **Excess/Non-award**. Label any subjects in **Excess/Non-award** explicitly as “Excess” in the study plan notes. 

**Step 1.5 — Total Complete CP and Enrolled CP Audit (Mandatory)**
Total Complete CP = Core CP + Major Core CP (or No-Major Core CP if doing no-major path) + Elective CP
After categorising and counting all subjects, execute this specific proof before initiating any planning:
- If Total Complete CP == 0, explicitly conclude: "Degree Requirements Met." Do not draft future sessions and skip Stage 2.
- If Total Complete CP > 0, continue.

**Step 1.6 — STRICT PRE-EXECUTION CHECK — Stage 1:**
Before moving to Stage 2, explicitly confirm:
1. Is commencement year verified?
2. Is the major valid for the campus?
3. Is each completed subject in exactly ONE category?
4. Is CSIT321 categorised as **Core** (not Elective) and counted as **12 CP** toward the 96 CP core?
5. Does Core CP + Major Core CP (or No-Major Core CP if doing no-major path) + Elective CP = Total Complete CP?
6. Are declared majors correctly identified (or no-major path selected)?
Correct any errors and repeat until all checks pass.

---

## STAGE 2: PLANNING (Drafting the Study Plan)

Start only after Stage 1 is fully verified. Complete ALL steps in this stage in full.
Schedule the study plan in FULL, scheduling all the years necessary to successfully graduate. DO NOT return an incomplete plan or only the student’s enrolment record. 

**Step 2.1 — List Outstanding Mandatory Subjects:**
A required remaining subject is any subject not completed in Stage 1 including:
- All remaining Core subjects in Section A (**including CSIT321** if not complete — it is part of the 96 CP core)
- All remaining Major Core subjects for each declared major (Section B) or No-Major Path requirements
Before drafting any semester in Stage 2, you must create a table listing every required remaining subject and its valid sessions as retrieved by `lookup_subjects_tool`. If the tool output is missing a session, you must assume the subject is NOT available in that session. You are forbidden from drafting the study plan until this table exists in memory.
If a subject is listed as `Autumn`, it is FORBIDDEN for it to be placed in a `Spring` session. If a subject is listed as `Spring`, it is FORBIDDEN for it to be placed in a `Autumn` session.  

**Step 2.2 — Schedule subjects enforcing Prerequisites and Corequisites:**
If balancing your load requires placing a subject in an invalid session, you must instead extend the degree duration. Session availability is a hard constraint; workload balancing is a soft constraint. Never violate a hard constraint to satisfy a soft one.

For every subject being planned:
- All prerequisites must be **Complete** (Stage 1) or planned in a **strictly earlier** session.
- Simultaneous Completion is forbidden. A subject cannot be planned in the same session as its prerequisite.
- Explicitly map any subject’s prerequisites. For each prerequisite, map it to a completed or planned subject code and session that occurs earlier than the current subject's session. If a prerequisite is missing, the subject cannot be included in the plan in this session.
- For every subject with a prerequisite involving credit point totals at a specific level (e.g., "12 CP at 200-level"), perform the following:
* Step A: Identify all subjects previously completed or planned that correspond to the level required.
* Step B: Sum the credit points (CP) for these subjects.
* Step C: Verify that this sum is ≥ the prerequisite requirement.
* Step D: The subject requiring these CP cannot be scheduled in a session until the cumulative CP of the relevant level subjects, completed in *strictly earlier* sessions, meets the threshold.
- All corequisites must be **Complete** or planned in the **same or earlier** session.
- "CP at level X" prerequisites: count only Complete CP or CP planned in a **strictly earlier** session.
- Never assume a corequisite satisfies a prerequisite.
- Use `lookup_subjects_tool` to verify prerequisites before finalising.
- Verify with the table created in Step 2.1 that the subject can be placed in this session before finalising. 

To finalise a subject:
To finalise a subject in the plan it is MANDATORY that these rules are true:
* All prerequisites are met in a **strictly earlier** session
* All corequisites are met in the **same or earlier** session
* The subject is in a session valid for that subject verified by the table made in Step 2.1
* The session does not already have 4 subjects
- If any of these mandatory rules are not met, the subject must be placed in a different session or year. Repeat these until all the above rules are true to finalise a subject. 

Specifically for CSIT321:
- Place Part 2 in the **immediately following** session from the placement of Part 1 (Spring then Autumn the next year or Autumn then Spring the same year).
- If the student was already enrolled in Part 1 last session, Part 2 must appear in next current session.
- Ensure CSIT226 and CSIT314 corequisites are satisfied.

**Step 2.3 — Calculate Required Remaining CP:**
Required CP = 144 - (Total Complete CP + Total Planned CP). If this result is 0, the study plan must explicitly state "Degree Requirements Met" and cease adding future semesters or subjects.

**Step 2.4 — Add Electives:**
If doing a **Double Major** NO electives should be added. 
For all other major options (or no-major path):
- Add elective subjects until total planned CP equals Required CP from Step 2.6. Do not invent subject codes; use a placeholder "Elective (level)". If more than 4 electives are needed to equal the Required CP from step 2.3 re-check the plan for missed core or major subjects or incorrect maths. 
- Prioritise placing electives in sessions with 1 to 3 subjects over adding an extra session of just electives. 

**Step 2.5 — Mandatory Stage 2 Pre-Execution Validation Checklist (Run BEFORE rendering output):**
Before generating the visible Markdown table and JSON block for the whole plan (completed and planned subjects), it is MANDATORY to verify each item sequentially:
1. Read the table row-by-row and explicitly quote the tool output for each subject's session to ensure you can quote the tool for that subject/session combination. 
2. **Total CP Check:** Does `Total Complete CP` + `Total Planned CP` = exactly **144 CP**?
3. **Prerequisite Check:** Is EVERY subject's prerequisite completed in a strictly earlier session? List each pair mentally: `Prereq (Session N-1 or earlier)` -> `Subject (Session N)`, `Subject1 S CP (Session N-1 or earlier) + … + Subject2 S CP (Session N-1 or earlier) = J CP` -> `Prereq J CP total (Session N)`.
4. **Corequisite Check:** Are all corequisites planned in the same or an earlier session?
5. **Session Capacity:** Does any session exceed 4 subjects (24 CP)?
6. **Capstone Gap Rule:** Does CSIT321 span two consecutive sessions with zero gap?
7. **100-Level Cap:** Is total 100-level CP (Completed + Planned) ≤ **60 CP**?
8. No subject appears more than once across the entire plan, unless the status is failed.
9. No subject code or name has been invented.
If any item fails, adjust the plan and re-run Step 2.5.

Once ALL the above stages and steps have been completed and ALL requirements of Step 1.6 and Step 2.5 have PASSED, generate the markdown table and JSON block for the whole plan (completed and planned subjects). 
"""

# Handbook data for 1807 Bachelor of Information Technology (Liverpool Campus, 2026)
HANDBOOK_1807_2026_LIVERPOOL = """# 1807 — Bachelor of Information Technology (Liverpool Campus, 2026 Handbook)


## Global Rules

To qualify for the award of Bachelor of Information Technology, complete **144 credit points** and satisfy all course requirements:

- **(a) Core — 96 CP:** Complete all core subjects listed in Section A (**including CSIT321** at 12 CP). 
- **(b) Major (optional):** To qualify for a major, complete **24 CP** from that major's list (Section B).
- **(c) No-major path:** If not undertaking a major, in addition to the 96 CP core, complete:
  - **18 CP** of **300-level** CSCI, CSIT or ISIT subjects, **and**
  - an additional **6 CP** subject at **200/300-level** CSCI, CSIT or ISIT
- **(d) Electives:** Elective subjects to bring the total to **144 CP**. An elective is any CSIT, CSCI or ISIT subject **not** in the core or chosen major OR from the General Schedule (assume any non CSIT, CSCI or ISIT subject is a valid elective). A maximum of **24 CP** of electives can be counted towards the **144 credit points** to complete the degree. 
- **(e) 100-level cap:** No more than **60 CP** at 100-level (complete + planned).

**Agent counting rules:**
- **CSIT321 (Capstone) = 12 CP**; every other subject = 6 CP unless stated otherwise. Never count CSIT321 as 6 CP.
- Do NOT invent subject codes or names. Only use codes and names that appear in this handbook or the student's enrolment record.
- A subject counts toward exactly ONE category among Core / Major Core / No-Major Core / Elective / Excess.
- This document covers the **Liverpool campus** offering only (not Wollongong or SIM). Singapore's "no major + specified core + IT/Business electives" path does **not** apply here.

---

## (A) Core Subjects — Complete ALL

| Subject Code | Session Availability | Prerequisites |
|-------------|---------------------|--------------|
| CSIT110 | Autumn or Spring | None |
| CSIT123 | Autumn | None |
| CSIT114 | Autumn | None |
| CSIT115 | Autumn or Spring | None |
| CSIT121 | Autumn or Spring | CSIT110 OR CSIT111 OR ENGG100 |
| CSIT127 | Spring | None |
| CSIT128 | Autumn or Spring | None |
| CSIT205 | Autumn | None |
| CSIT214 | Autumn or Spring | CSIT114 |
| CSIT226 | Spring | None |
| CSIT305 | Spring | None |
| ISIT219 | Autumn | CSIT128 |
| ISIT224 | Spring | (CSIT113 OR CSIT123 OR BUS 101) AND another 18 CP at 100-level |
| CSIT314 | 6 | Autumn | CSIT214 AND 12 CP at 200-level CSCI/ISIT | None |
| CSIT321 | 12 | Two consecutive sessions (Autumn then Spring or Spring then Autumn) | CSIT214 AND an additional 18 CP at 200-level CSCI/CSIT/ISIT | CSIT226 AND CSIT314 |

**CSIT321 is Core** and counts **12 CP** toward the **96 CP** core total. Do **not** categorise CSIT321 as Elective or as a separate non-core category.

**CSIT321 scheduling rules:**
- Spans exactly **two consecutive sessions** (Part 1 then Part 2). There must be **no gap** between parts.
- **Start session is flexible:** Part 1 may begin in **Autumn or Spring**, whichever fits the student's plan, provided all prerequisites and corequisites are satisfied.
  - Example: Part 1 in **Spring**, Part 2 in the following **Autumn**.
  - Example: Part 1 in **Autumn**, Part 2 in the following **Spring**.
- If the student was enrolled in Part 1 in the **immediately preceding session**, they MUST be enrolled in Part 2 in the current session — do not insert a gap.
- Schedule CSIT321 only after all prerequisites are fully satisfied.
- CSIT226 and CSIT314 must be complete or enrolled in the same session as Part 1 as required by the corequisite rule.

### Equivalency / Replacement Rules

Official core replacement (Wol):

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

Liverpool major (**24 CP** each).
Note: 300-level subjects in a major may require 100/200-level prerequisites that are **not** listed inside the major — look those up via `lookup_subjects_tool` / `lookup_major_tool`.

If no major is declared, skip this section and use the **No-Major Path** below.

### Network Design and Management (MAJ40163) — Complete ALL 4

| Subject Code | Session | Prerequisites | Corequisites |
|-------------|---------|--------------|-------------|
| ISIT212 | Autumn | ISIT105 OR CSIT127 | None |
| CSCI322 | Spring | CSIT127 AND 18 CP at 200-level | None |
| ISIT302 | Autumn | CSIT127 AND 6 CP at 200-level | 12 CP at 200-level |
| CSIT302 | Autumn | CSIT127 AND 12 CP at 100-level CSIT | None |

---

## No-Major Path (if no major is declared)

Liverpool rule (Global Rule (c)(ii)) — in addition to the **96 CP** core:

- **18 CP** of **300-level** CSCI, CSIT or ISIT subjects (not already in Core)
- **6 CP** at **200-level OR 300-level** CSCI, CSIT or ISIT (not already in Core)
Label these 4 subjects as No-major core. These count as **24 CP** toward the **24 CP** No-major core total. Do **not** categorise them as Elective or as a separate non-core category.

No subject used on this path may already appear in Core.

---

## Electives

Elective subjects bring the total to **144 CP** (Global Rule (d)). 
For any elective:
- Assume any non CSIT, CSCI or ISIT subject is a valid elective and is a part of the general schedule
- It can be any CSIT, CSCI or ISIT subject **not** already counted in Core or the chosen major(s) / No-Major category.
- The elective subject’s CP is added to the elective category. 
- There may be a maximum of 4 electives.
- **100-level cap:** total 100-level CP across the entire degree (complete + planned) must not exceed **60 CP** (Global Rule (e))
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

Grades TF, F, N, NH, W, WF, AF, or any blank Grade do **NOT** count as complete or towards the CP total.

Specified Credits table format: `Course | Subject Code | Name | Level | NomCP`
Unspecified Credits table format: `Course | Level | NomCP`

–-

## STAGE 1: ANALYSIS (Audit of Completed Credits)

Complete ALL steps in this stage in full before starting Stage 2.

**Step 1.0 — Commencement Year and Major:**
Identify the student's commencement year (earliest year in the enrolment record). Identify declared major, if any (MAJ40163 for Liverpool).
If the major is anything other than Network Design and Development, stop generating the study plan and inform the user they CANNOT have this major. Ask if they would like to pursue MAJ40163 Network Design and Development or No major. 

**Step 1.1 (Campus Check): 
Does the proposed study plan include any majors that are not listed in the provided Handbook for this degree?
If the answer is "Yes," flag it immediately and pause the planning process to ask for clarification or to confirm the No-Major path.

**Step 1.2 — Apply Equivalency Rules:**
Before categorising, resolve replacements:
- MATH255 present → treat as satisfying CSIT205 core. If CSIT205 is also present, MATH255 is an elective.
- Apply prerequisite alternates (CSIT111 / CSIT113) only where a later subject's prerequisite clause allows them.

**Step 1.3 — Identify Complete Subjects:**
List every subject that is Complete or enrolled. Then categorise each as exactly one of:

| Category | Rule |
|----------|------|
| Core | Appears in Section A, **including CSIT321** (12 CP toward the 96 CP core) |
| Major Core | Appears in the declared major's list in Section B |
| No-major Core | Appears in the no-major path in Section B |
| Elective | Everything else (including "losing" replacements and discontinued subjects. If a subject is not CSIT/ CSCI/ ISIT assume it is a valid elective) |

Never put CSIT321 in Elective — it is always Core when present (complete or enrolled toward the degree).

**Step 1.4 — Count CP per category:**
Sum CP for Core, Major Core, No-Major core, Electives and Excess/Non-award. Remember: **CSIT321 = 12 CP** and those 12 CP belong in **Core** (part of the 96 CP core), all other listed subjects = 6 CP unless stated otherwise.
The Elective CP category can have a maximum of 24 CP (4 subjects) counted towards the Total Valid CP total. Any CP over 24 should be placed in **Excess/Non-award**. Label any subjects in **Excess/Non-award** explicitly as “Excess” in the study plan notes. 

**Step 1.5 — Total Complete CP and Enrolled CP Audit (Mandatory)**
Total Complete CP = Core CP + Major Core CP (or No-Major Core CP if doing no-major path) + Elective CP
After categorising and counting all subjects, execute this specific proof before initiating any planning:
- If Total Complete CP == 0, explicitly conclude: "Degree Requirements Met." Do not draft future sessions and skip Stage 2.
- If Total Complete CP > 0, continue.

**Step 1.6 — STRICT PRE-EXECUTION CHECK — Stage 1:**
Before moving to Stage 2, explicitly confirm:
1. Is commencement year verified?
2. Is the major valid for the campus?
3. Is each completed subject in exactly ONE category?
4. Is CSIT321 categorised as **Core** (not Elective) and counted as **12 CP** toward the 96 CP core?
5. Does Core CP + Major Core CP (or No-Major Core CP if doing no-major path) + Elective CP = Total Complete CP?
6. Are declared majors correctly identified (or no-major path selected)?
Correct any errors and repeat until all checks pass.

---

## STAGE 2: PLANNING (Drafting the Study Plan)

Start only after Stage 1 is fully verified. Complete ALL steps in this stage in full.
Schedule the study plan in FULL, scheduling all the years necessary to successfully graduate. DO NOT return an incomplete plan or only the student’s enrolment record. 


**Step 2.1 — List Outstanding Mandatory Subjects:**
A required remaining subject is any subject not completed in Stage 1 including:
- All remaining Core subjects in Section A (**including CSIT321** if not complete — it is part of the 96 CP core)
- All remaining Major Core subjects for each declared major (Section B) or No-Major Path requirements
Before drafting any semester in Stage 2, you must create a table listing every required remaining subject and its valid sessions as retrieved by `lookup_subjects_tool`. If the tool output is missing a session, you must assume the subject is NOT available in that session. You are forbidden from drafting the study plan until this table exists in memory.
If a subject is listed as `Autumn`, it is FORBIDDEN for it to be placed in a `Spring` session. If a subject is listed as `Spring`, it is FORBIDDEN for it to be placed in a `Autumn` session.  

**Step 2.2 — Schedule subjects enforcing Prerequisites and Corequisites:**
If balancing your load requires placing a subject in an invalid session, you must instead extend the degree duration. Session availability is a hard constraint; workload balancing is a soft constraint. Never violate a hard constraint to satisfy a soft one.

For every subject being planned:
- All prerequisites must be **Complete** (Stage 1) or planned in a **strictly earlier** session.
- Simultaneous Completion is forbidden. A subject cannot be planned in the same session as its prerequisite.
- Explicitly map any subject’s prerequisites. For each prerequisite, map it to a completed or planned subject code and session that occurs earlier than the current subject's session. If a prerequisite is missing, the subject cannot be included in the plan in this session.
- For every subject with a prerequisite involving credit point totals at a specific level (e.g., "12 CP at 200-level"), perform the following:
* Step A: Identify all subjects previously completed or planned that correspond to the level required.
* Step B: Sum the credit points (CP) for these subjects.
* Step C: Verify that this sum is ≥ the prerequisite requirement.
* Step D: The subject requiring these CP cannot be scheduled in a session until the cumulative CP of the relevant level subjects, completed in *strictly earlier* sessions, meets the threshold.
- All corequisites must be **Complete** or planned in the **same or earlier** session.
- "CP at level X" prerequisites: count only Complete CP or CP planned in a **strictly earlier** session.
- Never assume a corequisite satisfies a prerequisite.
- Use `lookup_subjects_tool` to verify prerequisites/sessions before finalising.
- Verify with the table created in Step 2.1 that the subject can be placed in this session before finalising. 

To finalise a subject:
To finalise a subject in the plan it is MANDATORY that these rules are true:
* All prerequisites are met in a **strictly earlier** session
* All corequisites are met in the **same or earlier** session
* The subject is in a session valid for that subject verified by the table made in Step 2.1
* The session does not already have 4 subjects
- If any of these mandatory rules are not met, the subject must be placed in a different session or year. Repeat these until all the above rules are true to finalise a subject. 

Specifically for CSIT321:
- Place Part 2 in the **immediately following** session from the placement of Part 1 (Spring then Autumn the next year or Autumn then Spring the same year).
- If the student was already enrolled in Part 1 last session, Part 2 must appear in next current session.
- Ensure CSIT226 and CSIT314 corequisites are satisfied.

**Step 2.3 — Calculate Required Remaining CP:**
Required CP = 144 - (Total Complete CP + Total Planned CP). If this result is 0, the study plan must explicitly state "Degree Requirements Met" and cease adding future semesters or subjects.

**Step 2.4 — Add Electives:**
Add elective subjects until total planned CP equals Required CP from Step 2.6. Do not invent subject codes; use a placeholder "Elective (level)". If more than 4 electives are needed to equal the Required CP from step 2.3 re-check the plan for missed core or major subjects or incorrect maths. 
Prioritise placing electives in sessions with 1 to 3 subjects over adding an extra session of just electives. 

**Step 2.5 — Mandatory Stage 2 Pre-Execution Validation Checklist (Run BEFORE rendering output):**
Before generating the visible Markdown table and JSON block for the whole plan (completed and planned subjects), verify each item sequentially:
1. Read the table row-by-row and explicitly quote the tool output for each subject's session to ensure you can quote the tool for that subject/session combination. 
2. **Total CP Check:** Does `Total Complete CP` + `Total Planned CP` = exactly **144 CP**?
3. **Prerequisite Check:** Is EVERY subject's prerequisite completed in a strictly earlier session? List each pair mentally: `Prereq (Session N-1 or earlier)` -> `Subject (Session N)`, `Subject1 S CP (Session N-1 or earlier) + … + Subject2 S CP (Session N-1 or earlier) = J CP` -> `Prereq J CP total (Session N)`.
4. **Corequisite Check:** Are all corequisites planned in the same or an earlier session?
5. **Session Capacity:** Does any session exceed 4 subjects (24 CP)?
6. **Capstone Gap Rule:** Does CSIT321 span two consecutive sessions with zero gap?
7. **100-Level Cap:** Is total 100-level CP (Completed + Planned) ≤ **60 CP**?
8. No subject appears more than once across the entire plan, unless the status is failed
9. No subject code has been invented
If any item fails, adjust the plan and re-run Step 2.5.

Once ALL the above stages and steps have been completed and ALL requirements of Step 1.6 and Step 2.5 have PASSED, generate the markdown table and JSON block for the whole plan (completed and planned subjects). 
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
            "course": "1807",
            "campus": "Liverpool",
            "information": HANDBOOK_1807_2026_LIVERPOOL,
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
            row = result.scalar_one_or_none()
            
            if row:
                # Update existing record values
                for key, value in entry.items():
                    setattr(row, key, value)
                print(f"Updated {entry['course']} {entry['year']} ({entry['campus']})")
            else:
                # Insert new record
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
