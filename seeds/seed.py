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

## CORE DEGREE RULES (Total: 144 CP)
- **Core (96 CP):** Complete all Section A subjects. 
- **Major (24 CP):** Complete Section B declared major list.
- **No-Major Path (24 CP):** 18 CP at 300-level + 6 CP at 200/300-level (CSCI/CSIT/ISIT). Do not make up no-major subjects. Write no-major 1 (200/300 lv) etc.
- **Double Major:** Satisfy both majors (15 core + 8 major subjects). No electives.
- **Electives:** Max 24 CP (4 subjects). NON-IT SUBJECTS ARE VALID ELECTIVES. ANY MAJOR CORE SUBJECT THAT IS NOT A PART OF THE CHOSEN MAJOR IS AN ELECTIVE.
- **Excess:** Not counted towards the total CP. Excess is any subject that would be an elective but there are already 24 CP (4 subjects) of electives.
- **Level Cap:** Max 60 CP at 100-level overall.

---

## (A) CORE SUBJECTS (96 CP Total)
- CSIT110 (6 CP) | Aut/Spr | Prereq: None
- CSIT123 (6 CP) | Aut | Prereq: None
- CSIT114 (6 CP) | Aut | Prereq: None
- CSIT115 (6 CP) | Aut/Spr | Prereq: None
- CSIT121 (6 CP) | Aut/Spr | Prereq: CSIT110 OR CSIT111 OR ENGG100
- CSIT127 (6 CP) | Spr | Prereq: None
- CSIT128 (6 CP) | Aut/Spr | Prereq: None
- CSIT205 (6 CP) | Aut | Prereq: None (Replaces MATH255)
- CSIT214 (6 CP) | Aut/Spr | Prereq: CSIT114
- CSIT226 (6 CP) | Spr | Prereq: None
- CSIT305 (6 CP) | Spr | Prereq: None
- ISIT219 (6 CP) | Aut | Prereq: CSIT128
- ISIT224 (6 CP) | Spr | Prereq: (CSIT113 OR CSIT123 OR BUS101) AND 18 CP at 100-level
- CSIT314 (6 CP) | Aut | Prereq: CSIT214 AND 12 CP at 200-level CSCI/ISIT
- CSIT321 (12 CP) | Aut/Spr | Prereq: CSIT214 AND 18 CP at 200-level CSCI/CSIT/ISIT | Coreq: CSIT226 AND CSIT314 |

### Specifically for CSIT321:
- CSIT321 is split into Part 1 and Part 2 both worth 6CP each for the purpose of scheduling. They CANNOT BE TAKEN SIMULTANEOUSLY AND YOU CANNOT COMBINE BOTH PARTS. 
- CSIT321 Part 1 has ALL the prequisites and corequisites of CSIT321. CSIT321 Part 2 only has CSIT321 Part 1 as a prerequisite. 
- Part 2 MUST be in the **immediately following** session from Part 1 (Session N then Session N + 1).
- If the student was already enrolled in Part 1 last session, Part 2 must appear in next current session.
- Prioritise starting CSIT321 in the same session as CSIT314 if possible. 
- CSIT321 Part 1 is 6 CP. CSIT321 Part 2 is 6 CP.

### Specifically for CSIT314:
- CSIT314 is a corequisite of CSIT321
- CSIT314 is **NOT** a core subject for students with commencement year ≤ 2023, so remove it from the core list when auditing or planning for those students.
- CSIT314 is a mandatory subject for students with commencement year ≥ 2024. Example: A student who commenced 2025 -> 2025 ≥ 2024 -> CSIT314 IS core.

### Core Replacements & Alternates
- MATH255 Complete -> Satisfies CSIT205 core. If both present, CSIT205 = Core, MATH255 = Elective.
- CSIT111 satisfies CSIT110 where allowed. CSIT113 satisfies CSIT123 where allowed.

---

## (B) Core Selection — (6 CP required)

- CSCI251 (6 CP) | Spr | Prereq: CSIT121 or CSIT213
- CSIT213 (6 CP) | Aut | Prereq: CSIT110 OR CSIT111

### Core selection rules:
- If BOTH CSCI251 and CSIT213 are complete: CSCI251 satisifies the Core Selection; CSIT213 becomes an elective.
- Do not swap CSCI251 and CSIT213 when scheduling Core Selection

---

## (C) MAJORS (24 CP Each)

Only refer and use the student's declared major's subtable. Do not include or reference requirements from any other major subtable in the audit or plan. if the student has declared no major, skip this and use the No-Major Path below.

If no major is declared, skip this section and use the **No-Major Path** below.
For a **double major**, list requirements for BOTH majors. At most **ONE subject** may be cross-counted between the two majors.

### AI & Big Data (MAJ44204)
- CSCI218 (6 CP) | Spr | Prereq: (CSIT110 OR CSIT111) AND 18 CP at 100-level 
- CSCI316 (6 CP) | Aut | Prereq: CSCI203
- CSCI323 (6 CP) | Aut | Prereq: (CSIT110 OR CSIT111) AND 12 CP of 200-level CSCI/CSIT
- ISIT312 (6 CP) | Spr | Prereq: CSIT115 AND 18 CP at 200-level


### Cybersecurity (MAJ40516)
- CSCI262 (6 CP) | Spr | Prereq: CSIT121 AND CSIT115 AND CSIT127
- CSCI369 (6 CP) | Spr | (CSIT110 OR CSIT111) AND 18 CP at 200-level
- CSIT302 (6 CP) | Aut | CSIT127 AND 12 CP at 100-level CSIT
- CSIT375 (6 CP) | Aut | CSIT121 AND CSIT127 AND 18 CP at 200-level CSCI/CSIT


### Digital Systems Security (MAJ40164)
- CSCI262 (6 CP) | Spr | Prereq: CSIT121 AND CSIT115 AND CSIT127
- CSCI361 (6 CP) | Aut | Prereq: CSIT121 AND 12 CP of 200-level CSCI
- CSCI368 (6 CP) | Spr | Prereq: CSIT127 AND CSIT121 AND 12 CP of 200-level CSCI/CSIT
- CSIT328 (6 CP) | Aut | Prereq: (CSIT110 OR CSIT111) AND CSIT128 | Coreq: 12 CP at 200-level


### Game and Mobile Development (MAJ41477)
- CSCI336 (6 CP) | Spr | Prereq: CSIT121 AND 18 CP at 200-level
- CSCI356 (6 CP) | Spr | Prereq: CSIT121 | Coreq: CSIT214
- CSCI388 (6 CP) | Aut | Prereq: CSIT121 AND 18 CP at 200-level
- CSIT242 (6 CP) | Aut | Prereq: CSIT121 | Coreq: CSIT213 |


### Software Engineering (MAJ40277)

- CSCI318 (6 CP) | Spr | Prereq: (CSIT121 AND CSIT214) OR (ECTE250 AND CSCI291)
- CSCI334 (6 CP) | Aut | Prereq: CSIT121 AND CSIT214
- CSIT377 (6 CP) | Spr | Prereq: CSIT128 AND 6 CP at 200-level | Coreq: 12 CP at 200-level |
- ISIT219 (6 CP) | Aut | Prereq: CSIT128

#### Specifically for Software Engineering majors:
- ISIT219 is **NOT** an SE major core for students with commencement year ≤ 2023. 
- CSIT314 **IS** an SE major core for students with commencement year ≤ 2023.


### No-Major Path (if no major is declared)
- **18 CP** of 300-level CSCI/CSIT/ISIT subjects (subject codes with a 3xx number) **Not** already in the Core or Core Selection
- **6 CP** at 200-level OR 300-level CSCI/CSIT/ISIT subjects **Not** already in the Core or Core Selection

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

Grades TF, F, N, NH, W, WF, AF, or any blank Grade do **NOT** count as complete or count towards the CP total.

Specified Credits table format: `Course | Subject Code | Name | Level | NomCP`
Unspecified Credits table format: `Course | Level | NomCP`

–-

## EXECUTION STEPS & AUDIT PROTOCOL

### STAGE 1: ANALYSIS & AUDIT
1. Identify Commencement Year & Declared Major.
   - Valid Majors: Network Design & Management (MAJ40163), Web Design & Development (MAJ40246), or No-Major Path.
   - If invalid: Trigger CIRCUIT BREAKER -> Abort immediately to Scenario A.
2. Resolve Replacements (e.g., MATH255 -> CSIT205).
3. Audit COMPLETED and ENROLLED subjects in strict priority order (Core -> Major -> Elective -> Excess):
   - Core_CP_Completed = [X] CP
   - Major_CP_Completed = [X] CP
   - Raw_Elective_CP_Taken = [X] CP
   - Valid_Elective_CP = MIN(24, Raw_Elective_CP_Taken) = [X] CP
   - Excess_CP = MAX(0, Raw_Elective_CP_Taken - 24) = [X] CP (List codes here immediately)
   - Total_Applicable_Earned = Core_CP_Completed + Major_CP_Completed + Valid_Elective_CP = [X] / 144 CP

### STAGE 2: SESSION SCRATCHPAD
1. Calculate Remaining Needed CP to reach 144 CP.
2. Run Session Scratchpad for ALL future sessions in chronological order until 144 CP is reached.
3. Apply Session Filters (Availability, Prereq <= N-1, Coreq <= N, CP level thresholds) to every uncompleted subject.
4. Enforce Session Load Limits (Standard: 4 subjects / 24 CP; Hard Cap: Max 4 subjects).
5. Proceed to Step 10 (Macro & Tool Audit) and Step 11 (Pre-Flight Verification Matrix).

"""

# Handbook data for 1807 Bachelor of Information Technology (Wollongong Campus, 2026)
# Handbook data for 1807 Bachelor of Information Technology (Wollongong Campus, 2026)
HANDBOOK_1807_2026_WOLLONGONG = """# 1807 — Bachelor of Information Technology (Wollongong, 2026)

## CORE DEGREE RULES (Total: 144 CP)
- **Core (96 CP):** Complete all Section A subjects. 
- **Major (24 CP):** Complete Section B declared major list.
- **No-Major Path (24 CP):** 18 CP at 300-level + 6 CP at 200/300-level (CSCI/CSIT/ISIT). Do not make up no-major subjects. Write no-major 1 (200/300 lv) etc.
- **Double Major:** Satisfy both majors (15 core + 8 major subjects). No electives.
- **Electives:** Max 24 CP (4 subjects). NON-IT SUBJECTS ARE VALID ELECTIVES. ANY MAJOR CORE SUBJECT THAT IS NOT A PART OF THE CHOSEN MAJOR IS AN ELECTIVE.
- **Excess:** Not counted towards the total CP. Excess is any subject that would be an elective but there are already 24 CP (4 subjects) of electives.
- **Level Cap:** Max 60 CP at 100-level overall.

---

## (A) CORE SUBJECTS (96 CP Total)
- CSIT110 (6 CP) | Aut/Spr | Prereq: None
- CSIT123 (6 CP) | Aut | Prereq: None
- CSIT114 (6 CP) | Aut | Prereq: None
- CSIT115 (6 CP) | Aut/Spr | Prereq: None
- CSIT121 (6 CP) | Aut/Spr | Prereq: CSIT110 OR CSIT111 OR ENGG100
- CSIT127 (6 CP) | Spr | Prereq: None
- CSIT128 (6 CP) | Aut/Spr | Prereq: None
- CSIT205 (6 CP) | Aut | Prereq: None (Replaces MATH255)
- CSIT214 (6 CP) | Aut/Spr | Prereq: CSIT114
- CSIT226 (6 CP) | Spr | Prereq: None
- CSIT305 (6 CP) | Spr | Prereq: None
- ISIT219 (6 CP) | Aut | Prereq: CSIT128
- ISIT224 (6 CP) | Spr | Prereq: (CSIT113 OR CSIT123 OR BUS101) AND 18 CP at 100-level
- CSIT314 (6 CP) | Aut | Prereq: CSIT214 AND 12 CP at 200-level CSCI/ISIT
- CSIT321 (12 CP) | Aut/Spr | Prereq: CSIT214 AND 18 CP at 200-level CSCI/CSIT/ISIT | Coreq: CSIT226 AND CSIT314 |

### Specifically for CSIT321:
- CSIT321 is split into Part 1 and Part 2 both worth 6CP each for the purpose of scheduling. They CANNOT BE TAKEN SIMULTANEOUSLY AND YOU CANNOT COMBINE BOTH PARTS. 
- CSIT321 Part 1 has ALL the prequisites and corequisites of CSIT321. CSIT321 Part 2 only has CSIT321 Part 1 as a prerequisite. 
- Part 2 MUST be in the **immediately following** session from Part 1 (Session N then Session N + 1).
- If the student was already enrolled in Part 1 last session, Part 2 must appear in next current session.
- Prioritise starting CSIT321 in the same session as CSIT314 if possible. 
- CSIT321 Part 1 is 6 CP. CSIT321 Part 2 is 6 CP.

### Core Replacements & Alternates
- MATH255 Complete -> Satisfies CSIT205 core. If both present, CSIT205 = Core, MATH255 = Elective.
- CSIT111 satisfies CSIT110 where allowed. CSIT113 satisfies CSIT123 where allowed.

---

## (B) MAJORS (24 CP Each)

### Web Design & Development (MAJ40246)
- ISIT207 (6 CP) | Spr | Prereq: (CSIT110 OR CSIT111) AND CSIT128
- CSIT377 (6 CP) | Spr | Prereq: CSIT128 AND 6 CP at 200-level | Coreq: 12 CP at 200-level
- ISIT307 (6 CP) | Aut | Prereq: (CSIT110 OR CSIT111) AND CSIT115 AND CSIT128 AND 12 CP at 200-level
- CSIT328 (6 CP) | Aut | Prereq: (CSIT110 OR CSIT111) AND CSIT128 | Coreq: 12 CP at 200-level

### Network Design & Management (MAJ40163)
- ISIT212 (6 CP) | Aut | Prereq: ISIT105 OR CSIT127
- CSCI322 (6 CP) | Spr | Prereq: CSIT127 AND 18 CP at 200-level
- ISIT302 (6 CP) | Aut | Prereq: CSIT127 AND 6 CP at 200-level | Coreq: 12 CP at 200-level
- CSIT302 (6 CP) | Aut | Prereq: CSIT127 AND 12 CP at 100-level CSIT

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

## EXECUTION STEPS & AUDIT PROTOCOL

### STAGE 1: ANALYSIS & AUDIT
1. Identify Commencement Year & Declared Major.
   - Valid Majors: Network Design & Management (MAJ40163), Web Design & Development (MAJ40246), or No-Major Path.
   - If invalid: Trigger CIRCUIT BREAKER -> Abort immediately to Scenario A.
2. Resolve Replacements (e.g., MATH255 -> CSIT205).
3. Audit COMPLETED and ENROLLED subjects in strict priority order (Core -> Major -> Elective -> Excess):
   - Core_CP_Completed = [X] CP
   - Major_CP_Completed = [X] CP
   - Raw_Elective_CP_Taken = [X] CP
   - Valid_Elective_CP = MIN(24, Raw_Elective_CP_Taken) = [X] CP
   - Excess_CP = MAX(0, Raw_Elective_CP_Taken - 24) = [X] CP (List codes here immediately)
   - Total_Applicable_Earned = Core_CP_Completed + Major_CP_Completed + Valid_Elective_CP = [X] / 144 CP

### STAGE 2: SESSION SCRATCHPAD
1. Calculate Remaining Needed CP to reach 144 CP.
2. Run Session Scratchpad for ALL future sessions in chronological order until 144 CP is reached.
3. Apply Session Filters (Availability, Prereq <= N-1, Coreq <= N, CP level thresholds) to every uncompleted subject.
4. Enforce Session Load Limits (Standard: 4 subjects / 24 CP; Hard Cap: Max 4 subjects).
5. Proceed to Step 10 (Macro & Tool Audit) and Step 11 (Pre-Flight Verification Matrix).
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
                "card": card_path.read_text(encoding="utf-8", errors="ignore"),
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
