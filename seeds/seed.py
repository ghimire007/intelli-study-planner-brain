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

from app.core.database import AsyncSessionLocal
from app.models.handbook import Handbook
from app.models.major import Major
from app.models.subject import Subject
from sqlalchemy import select

SEEDS_DIR = Path(__file__).resolve().parent
KB_COURSES = ("766", "1807", "1838", "1802", "1862")
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
- CSIT110 (6 CP) | Fundamental Programming with Python | Aut/Spr | Prereq: None
- CSIT123 (6 CP) | Computing and Cyber Security Fundamentals | Aut | Prereq: None
- CSIT114 (6 CP) | System Analysis | Aut | Prereq: None
- CSIT115 (6 CP) | Database Management Systems | Aut/Spr | Prereq: None
- CSIT121 (6 CP) | Object Oriented Design and Programming | Aut/Spr | Prereq: CSIT110 OR CSIT111 OR ENGG100
- CSIT127 (6 CP) | Networks and Communications | Spr | Prereq: None
- CSIT128 (6 CP) | Introduction to Web Technology | Aut/Spr | Prereq: None
- CSCI203 (6 CP) | Algorithms and Data Structures | Spr | Prereq: (CSIT110 or CSIT111) AND (CSIT113 or CSIT123)
- CSIT205 (6 CP) | Generative AI | Aut | Prereq: None (Replaces MATH255)
- CSIT214 (6 CP) | IT Project Management | Aut/Spr | Prereq: CSIT114
- CSIT226 (6 CP) | Human Computer Interaction | Spr | Prereq: None
- CSCI235 (6 CP) | Database Systems | Aut | Prereq: CSIT115
- CSIT314 (6 CP) | Software Development Methodologies | Aut | Prereq: CSIT214 AND 12 CP at 200-level CSCI/ISIT
- CSIT321 (12 CP) | Project | Aut/Spr | Prereq: CSIT214 AND 18 CP at 200-level CSCI/CSIT/ISIT | Coreq: CSIT226 AND CSIT314 |

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

- CSCI251 (6 CP) | Advanced Programming | Spr | Prereq: CSIT121 or CSIT213
- CSIT213 (6 CP) | Java Programming | Aut | Prereq: CSIT110 OR CSIT111

### Core Selection rules:
- CSCI251 and CSIT213 can each individually satisfy (B) Core Selection.
- Whenever BOTH CSCI251 and CSIT213 appear anywhere in the plan (scheduled or completed):
    - Whichever of the two was scheduled FIRST (earlier term, or earlier add-order if same term) is tagged "Core Selection"
    - The other one is tagged "Elective"
- This tagging must be re-evaluated every time the plan changes — including when a second course is added later, or when scheduling is edited/reordered.
- If only one of the two is in the plan, it is tagged "Core Selection" by default.

---

## (C) MAJORS (24 CP Each)

Only refer and use the student's declared major's subtable. Do not include or reference requirements from any other major subtable in the audit or plan. if the student has declared no major, skip this and use the No-Major Path below.

If no major is declared, skip this section and use the **No-Major Path** below.
For a **double major**, list requirements for BOTH majors. At most **ONE subject** may be cross-counted between the two majors.

### AI & Big Data (MAJ44204)
- CSCI218 (6 CP) | Foundations of Artificial Intelligence | Spr | Prereq: (CSIT110 OR CSIT111) AND 18 CP at 100-level 
- CSCI316 (6 CP) | Big Data Mining Techniques and Implementation | Aut | Prereq: CSCI203
- CSCI323 (6 CP) | Modern Artificial Intelligence | Aut | Prereq: (CSIT110 OR CSIT111) AND 12 CP of 200-level CSCI/CSIT
- ISIT312 (6 CP) | Big Data Management | Spr | Prereq: CSIT115 AND 18 CP at 200-level


### Cybersecurity (MAJ40516)
- CSCI262 (6 CP) | System Security | Spr | Prereq: CSIT121 AND CSIT115 AND CSIT127
- CSCI369 (6 CP) | Ethical Hacking | Spr | (CSIT110 OR CSIT111) AND 18 CP at 200-level
- CSIT302 (6 CP) | Cybersecurity | Aut | CSIT127 AND 12 CP at 100-level CSIT
- CSIT375 (6 CP) | Artificial Intelligence and Cybersecurity | Aut | CSIT121 AND CSIT127 AND 18 CP at 200-level CSCI/CSIT


### Digital Systems Security (MAJ40164)
- CSCI262 (6 CP) | System Security | Spr | Prereq: CSIT121 AND CSIT115 AND CSIT127
- CSCI361 (6 CP) | Cryptography and Secure Applications | Aut | Prereq: CSIT121 AND 12 CP of 200-level CSCI
- CSCI368 (6 CP) | Network Security | Spr | Prereq: CSIT127 AND CSIT121 AND 12 CP of 200-level CSCI/CSIT
- CSIT328 (6 CP) | Web Security | Aut | Prereq: (CSIT110 OR CSIT111) AND CSIT128 | Coreq: 12 CP at 200-level


### Game and Mobile Development (MAJ41477)
- CSCI336 (6 CP) | Interactive Computer Graphics | Spr | Prereq: CSIT121 AND 18 CP at 200-level
- CSCI356 (6 CP) | Game Engine Essentials | Spr | Prereq: CSIT121 | Coreq: CSIT214
- CSCI388 (6 CP) | Virtual and Augmented Reality | Aut | Prereq: CSIT121 AND 18 CP at 200-level
- CSIT242 (6 CP) | Mobile Application Development | Aut | Prereq: CSIT121 | Coreq: CSIT213 |


### Software Engineering (MAJ40277)
- CSCI318 (6 CP) | Software Engineering Practices & Principles | Spr | Prereq: (CSIT121 AND CSIT214) OR (ECTE250 AND CSCI291)
- CSCI334 (6 CP) | Software Design | Aut | Prereq: CSIT121 AND CSIT214
- CSIT377 (6 CP) | Enterprise Cloud Development | Spr | Prereq: CSIT128 AND 6 CP at 200-level | Coreq: 12 CP at 200-level |
- ISIT219 (6 CP) | Knowledge and Information Engineering | Aut | Prereq: CSIT128

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

--

## EXECUTION STEPS & AUDIT PROTOCOL

### STAGE 1: ANALYSIS & AUDIT
1. Identify Commencement Year & Declared Major.
   - Valid Majors: AI & Big Data (MAJ44204), Cybersecurity (MAJ40516), Digital Systems Security (MAJ40164), Game and Mobile Development (MAJ41477), Software Engineering (MAJ40277), or No-Major Path.
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
- CSIT110 (6 CP) | Fundamental Programming with Python | Aut/Spr | Prereq: None
- CSIT123 (6 CP) | Computing and Cyber Security Fundamentals | Aut | Prereq: None
- CSIT114 (6 CP) | System Analysis | Aut | Prereq: None
- CSIT115 (6 CP) | Database Management Systems | Aut/Spr | Prereq: None
- CSIT121 (6 CP) | Object Oriented Design and Programming | Aut/Spr | Prereq: CSIT110 OR CSIT111 OR ENGG100
- CSIT127 (6 CP) | Networks and Communications | Spr | Prereq: None
- CSIT128 (6 CP) | Introduction to Web Technology | Aut/Spr | Prereq: None
- CSIT205 (6 CP) | Generative AI | Aut | Prereq: None (Replaces MATH255)
- CSIT214 (6 CP) | IT Project Management | Aut/Spr | Prereq: CSIT114
- CSIT226 (6 CP) | Human Computer Interaction | Spr | Prereq: None
- CSIT305 (6 CP) | Emerging Information Technologies and their Applications | Spr | Prereq: None
- ISIT219 (6 CP) | Knowledge and Information Engineering | Aut | Prereq: CSIT128
- ISIT224 (6 CP) | Management Information Systems | Spr | Prereq: (CSIT113 OR CSIT123 OR BUS101) AND 18 CP at 100-level
- CSIT314 (6 CP) | Software Development Methodologies | Aut | Prereq: CSIT214 AND 12 CP at 200-level CSCI/ISIT
- CSIT321 (12 CP) | Project | Aut/Spr | Prereq: CSIT214 AND 18 CP at 200-level CSCI/CSIT/ISIT | Coreq: CSIT226 AND CSIT314 |

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
- ISIT207 (6 CP) | Frontend Web Programming | Spr | Prereq: (CSIT110 OR CSIT111) AND CSIT128
- CSIT377 (6 CP) | Enterprise Cloud Development | Spr | Prereq: CSIT128 AND 6 CP at 200-level | Coreq: 12 CP at 200-level
- ISIT307 (6 CP) | Web Server Programming | Aut | Prereq: (CSIT110 OR CSIT111) AND CSIT115 AND CSIT128 AND 12 CP at 200-level
- CSIT328 (6 CP) | Web Security | Aut | Prereq: (CSIT110 OR CSIT111) AND CSIT128 | Coreq: 12 CP at 200-level

### Network Design & Management (MAJ40163)
- ISIT212 (6 CP) | Corporate Network Planning and Design | Aut | Prereq: ISIT105 OR CSIT127
- CSCI322 (6 CP) | Systems Administration | Spr | Prereq: CSIT127 AND 18 CP at 200-level
- ISIT302 (6 CP) | Corporate Network Management | Aut | Prereq: CSIT127 AND 6 CP at 200-level | Coreq: 12 CP at 200-level
- CSIT302 (6 CP) | Cybersecurity | Aut | Prereq: CSIT127 AND 12 CP at 100-level CSIT

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

--

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


# Handbook data for 1807 Bachelor of Information Technology (Liverpool Campus, 2026)
HANDBOOK_1807_2026_LIVERPOOL = """# 1807 — Bachelor of Information Technology (Liverpool, 2026)

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
- CSIT110 (6 CP) | Fundamental Programming with Python | Aut/Spr | Prereq: None
- CSIT123 (6 CP) | Computing and Cyber Security Fundamentals | Aut | Prereq: None
- CSIT114 (6 CP) | System Analysis | Aut | Prereq: None
- CSIT115 (6 CP) | Database Management Systems | Aut/Spr | Prereq: None
- CSIT121 (6 CP) | Object Oriented Design and Programming | Aut/Spr | Prereq: CSIT110 OR CSIT111 OR ENGG100
- CSIT127 (6 CP) | Networks and Communications | Spr | Prereq: None
- CSIT128 (6 CP) | Introduction to Web Technology | Aut/Spr | Prereq: None
- CSIT205 (6 CP) | Generative AI | Aut | Prereq: None (Replaces MATH255)
- CSIT214 (6 CP) | IT Project Management | Aut/Spr | Prereq: CSIT114
- CSIT226 (6 CP) | Human Computer Interaction | Spr | Prereq: None
- CSIT305 (6 CP) | Emerging Information Technologies and their Applications | Spr | Prereq: None
- ISIT219 (6 CP) | Knowledge and Information Engineering | Aut | Prereq: CSIT128
- ISIT224 (6 CP) | Management Information Systems | Spr | Prereq: (CSIT113 OR CSIT123 OR BUS101) AND 18 CP at 100-level
- CSIT314 (6 CP) | Software Development Methodologies | Aut | Prereq: CSIT214 AND 12 CP at 200-level CSCI/ISIT
- CSIT321 (12 CP) | Project | Aut/Spr | Prereq: CSIT214 AND 18 CP at 200-level CSCI/CSIT/ISIT | Coreq: CSIT226 AND CSIT314 |

### Specifically for CSIT321:
- CSIT321 is split into Part 1 and Part 2 both worth 6CP each for the purpose of scheduling. They CANNOT BE TAKEN SIMULTANEOUSLY AND YOU CANNOT COMBINE BOTH PARTS.
- Part 2 MUST be in the **immediately following** session from Part 1 (Session N then Session N + 1).
- If the student was already enrolled in Part 1 last session, Part 2 must appear in next current session.
- Prioritise starting CSIT321 in the same session as CSIT314 if possible.
- CSIT321 Part 1 is 6 CP. CSIT321 Part 2 is 6 CP.

### Core Replacements & Alternates
- MATH255 Complete -> Satisfies CSIT205 core. If both present, CSIT205 = Core, MATH255 = Elective.
- CSIT111 satisfies CSIT110 where allowed. CSIT113 satisfies CSIT123 where allowed.

---

## (B) MAJOR (24 CP)

### Network Design & Management (MAJ40163)
- ISIT212 (6 CP) | Corporate Network Planning and Design | Aut | Prereq: ISIT105 OR CSIT127
- CSCI322 (6 CP) | Systems Administration | Spr | Prereq: CSIT127 AND 18 CP at 200-level
- ISIT302 (6 CP) | Corporate Network Management | Aut | Prereq: CSIT127 AND 6 CP at 200-level | Coreq: 12 CP at 200-level
- CSIT302 (6 CP) | Cybersecurity | Aut | Prereq: CSIT127 AND 12 CP at 100-level CSIT

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

--

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

Used for **Year 2** (3 x 6 CP = 18 CP) and **Year 3** (1 x 6 CP). Subjects must **not** already be counted as Core.

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
| Y3 CSIT Elective | The 4 CSIT/CSCI/ISIT electives in Year 3 (1x200/300 + 3x300 per Section C) |

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
Required CP = 144 - Total Complete CP (from Stage 1.5)

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

# Handbook data for 1802 Bachelor of Computer Science (Dean's Scholar) (Wollongong Campus, 2026)
# From https://courses.uow.edu.au/courses/2026/1802 + seeds/scraped/*_1802.json
HANDBOOK_1802_2026_WOLLONGONG = """# 1802 — Bachelor of Computer Science (Dean's Scholar) (Wollongong Campus, 2026 Handbook)

Wollongong on-campus only. 3 years full-time. Same degree structure as 766 plus a 400-level Dean's Scholar subject.

## CORE DEGREE RULES (Total: 144 CP)
- **(a) Core (96 CP):** Section A core (78 CP) + Section B Core Selection (6 CP) + CSIT321 Capstone (12 CP).
- **(b) Major (24 CP):** Complete the declared major list in Section D, or
- **(c) No-Major Path (24 CP):** 18 CP at 300-level CSCI/CSIT/ISIT + 6 CP at 200/300-level CSCI/CSIT/ISIT not in the core. Do not make up no-major subjects. Write no-major 1 (200/300 lv) etc.
- **(d) Dean's Scholar (6 CP):** One subject from Section C.
- **(e) Electives (18 CP):** Any CSIT, CSCI or ISIT subject not in the core or chosen major, or any General Schedule subject, to bring the total to 144 CP. NON-IT SUBJECTS FROM THE GENERAL SCHEDULE ARE VALID ELECTIVES.
- **Excess:** Not counted towards the total CP. Excess is any subject that would be an elective when 18 CP of electives are already counted.
- **(f) Level Cap:** Max 60 CP at 100-level overall (includes the core).
- **Double Major:** Four subjects must satisfy each major; at most ONE subject may be counted toward both majors.

## DEAN'S SCHOLAR STANDING (check whenever marks are available)
- To remain enrolled the student must **maintain an average of 80% in each year of study**.
- If a year's average falls below 80%, the case is assessed individually and the student may be transferred into the non-Dean's Scholar equivalent degree (766). Flag this in the audit; do not state the transfer as certain.
- Entry by transfer: completed 48 CP of 766 within one year with a minimum WAM of 80. ATAR-SR for direct entry: 95.
- Students are encouraged to continue into Honours and research. Advise them to consult the Academic Program Director when planning their program.

---

## (A) CORE SUBJECTS (78 CP)
- CSIT110 (6 CP) | Fundamental Programming with Python | Aut/Spr | Prereq: None
- CSIT123 (6 CP) | Computing and Cyber Security Fundamentals | Aut | Prereq: None
- CSIT114 (6 CP) | System Analysis | Aut | Prereq: None
- CSIT115 (6 CP) | Database Management Systems | Aut/Spr | Prereq: None
- CSIT121 (6 CP) | Object Oriented Design and Programming | Aut/Spr | Prereq: CSIT110 OR CSIT111 OR ENGG100
- CSIT127 (6 CP) | Networks and Communications | Spr | Prereq: None
- CSIT128 (6 CP) | Introduction to Web Technology | Aut/Spr | Prereq: None
- CSCI203 (6 CP) | Algorithms and Data Structures | Spr | Prereq: (CSIT110 or CSIT111) AND (CSIT113 or CSIT123)
- CSIT214 (6 CP) | IT Project Management | Aut/Spr | Prereq: CSIT114
- CSIT226 (6 CP) | Human Computer Interaction | Spr | Prereq: None
- CSCI235 (6 CP) | Database Systems | Aut | Prereq: CSIT115
- CSIT314 (6 CP) | Software Development Methodologies | Aut | Prereq: CSIT214 AND 12 CP at 200-level CSCI/ISIT
- MATH255 (6 CP) | Mathematics for Computing | Not offered at Wollongong in 2026 (Dubai only) | Prereq: None

### Capstone (12 CP)
- CSIT321 (12 CP) | Project | Aut/Spr | Prereq: CSIT214 AND 18 CP at 200-level CSCI/CSIT/ISIT | Coreq: CSIT226 AND CSIT314
- CSIT321 is split into Part 1 and Part 2 (6 CP each) in consecutive sessions, exactly as for 766. Part 1 carries all prerequisites/corequisites; Part 2 must be in the immediately following session.

### Specifically for MATH255:
- MATH255 is listed in the 2026 1802 core but has no 2026 Wollongong offering. Do not schedule it at Wollongong; flag it and tell the student to confirm a replacement (e.g. CSIT205, the 766 replacement) with the Academic Program Director. Do not assume the replacement is approved.

### Core Replacements & Alternates
- CSIT111 satisfies CSIT110. CSIT113 satisfies CSIT123.

---

## (B) Core Selection — (6 CP required)
- CSCI251 (6 CP) | Advanced Programming | Spr | Prereq: CSIT121 or CSIT213
- CSIT213 (6 CP) | Java Programming | Aut | Prereq: CSIT110 OR CSIT111
- Same tagging rule as 766: if both appear, the one scheduled first is "Core Selection", the other is "Elective".

---

## (C) DEAN'S SCHOLAR COMPONENT — (6 CP, choose ONE)
All are 400-level, so schedule in the final year once the 300-level prerequisite is met.
- CSCI471 (6 CP) | Modern Cryptography | Spr | Prereq: 24 CP at 300-level
- CSCI426 (6 CP) | Software Testing and Analysis | Aut | Prereq: 24 CP at 300-level
- CSCI433 (6 CP) | Machine Learning Algorithms and Applications | Aut | Prereq: 24 CP of CSCI subjects at 300-level
- CSCI435 (6 CP) | Computer Vision Algorithms and Systems | Spr | Prereq: 24 CP of CSCI at 300-level
- CSIT470 (6 CP) | Security Essentials | Aut | Prereq: 18 CP of CSCI/CSIT 300-level subjects
- CSCI427 (6 CP) | Service-Oriented Software Engineering | Spr | Prereq: 24 CP of CSCI at 300-level
- CSCI444 (6 CP) | Perception, Planning and Interactions | Spr | Prereq: 24 CP at 300-level
- A second Dean's Scholar subject counts as an Elective.

---

## (D) MAJORS (24 CP Each)
Only use the student's declared major. Majors are the same as 766: AI & Big Data (MAJ44204), Cyber Security (MAJ40516), Digital Systems Security (MAJ40164), Game and Mobile Development (MAJ41477), Software Engineering (MAJ40277). Call lookup_major_tool for the declared major's subject list — do not reproduce it from memory.
Note: 300-level major subjects may have 100/200-level prerequisites not listed in the major.

---

## Student Enrolment Record Format
Same as 766. A subject is **Complete** if Grade is one of HD, D, C, P, PS, S and Status is "Complete", or it is a Specified Credit. TF, F, N, NH, W, WF, AF or blank grades do not count. Unspecified credits count toward total CP and the 100-level cap by their listed level.

---

## EXECUTION STEPS & AUDIT PROTOCOL

### STAGE 1: ANALYSIS & AUDIT
1. Identify Commencement Year & Declared Major (or No-Major Path).
2. Check Dean's Scholar standing: if marks are present, compute each completed year's average and flag any year below 80%.
3. Audit COMPLETED and ENROLLED subjects in strict priority order (Core -> Core Selection -> Major -> Dean's Scholar -> Elective -> Excess):
   - Core_CP_Completed = [X] / 96 CP (incl. Core Selection and CSIT321)
   - Major_CP_Completed = [X] / 24 CP
   - Deans_CP_Completed = [X] / 6 CP
   - Valid_Elective_CP = MIN(18, Raw_Elective_CP_Taken) = [X] CP
   - Excess_CP = MAX(0, Raw_Elective_CP_Taken - 18) = [X] CP (list codes)
   - Total_Applicable_Earned = sum of the above (excluding excess) = [X] / 144 CP

### STAGE 2: SESSION SCRATCHPAD
1. Calculate Remaining Needed CP to reach 144 CP.
2. Plan every future session until 144 CP is reached; the Dean's Scholar subject goes after 24 CP (18 CP for CSIT470) of 300-level study.
3. Apply Session Filters (Availability, Prereq <= N-1, Coreq <= N, CP level thresholds).
4. Session Load: max 4 subjects / 24 CP.
5. Verify: total = 144, no duplicates, 100-level CP ≤ 60, exactly 6 CP Dean's Scholar, CSIT321 in two consecutive sessions, no invented codes.
"""

# Handbook data for 1862 Bachelor of Engineering (Honours) - Bachelor of Computer Science (Wollongong, 2026)
# From https://courses.uow.edu.au/courses/2026/1862 + seeds/scraped/*_1862.json
HANDBOOK_1862_2026_WOLLONGONG = """# 1862 — Bachelor of Engineering (Honours) - Bachelor of Computer Science (Wollongong Campus, 2026 Handbook)

Double degree. Wollongong on-campus only. 5.5 years full-time. Minimum 264 CP (more for some majors). Students must seek advice and approval from both Faculties, and should discuss their Engineering and Computer Science programs with the relevant Academic Program Directors.

## CORE DEGREE RULES (Total: at least 264 CP)
- **(a) Engineering — at least 162 CP:**
  - (i) 48 CP Year 1 common core (Section A).
  - (ii) Subjects leading to ONE Bachelor of Engineering (Honours) major (Section B). Only these five majors are allowed, each with its own minimum total:
    - Electrical and Electronics Engineering (MAJ44203) — min 264 CP
    - Computer and Autonomous Systems Engineering (MAJ44198) — min 264 CP
    - Telecommunications Engineering and the Internet of Things (MAJ44200) — min 270 CP
    - Mechatronic Engineering (MAJ40172) — min 282 CP
    - Biomedical Engineering (MAJ41913) — min 264 CP
- **(b) Computer Science — at least 96 CP:**
  - (i) All CS Core and Capstone subjects (Section C). CSIT110, CSIT114 and CSIT214 are NOT required. Students completing a SECTE major (Electrical and Electronics, Computer and Autonomous Systems, Telecommunications and IoT) do not complete CSIT127 — it is replaced by ECTE364; and
  - (ii) 18 CP of 300-level CSCI/CSIT/ISIT + 6 CP at 200/300-level CSCI/CSIT/ISIT not in the core; OR
  - (iii) a 24 CP Computer Science major (Section D), which may push the total above 264 CP.
- **(c) Level Cap:** No more than **90 CP** at 100-level.
- The total target is the chosen engineering major's minimum (264/270/282), not always 264.
- Depending on the Engineering major, the CS core and CS elective component may be more or less than prescribed. Always tell the student to confirm their enrolment with both Academic Program Directors.

## HONOURS
- Honours grade is calculated using **Honours Grade Method 2**: WAM over all subjects weighted by level (400-level x4, 300-level x3, 200-level x2, 100-level x1).
- Class I: 77.5-100 | Class II Div 1: 72.5-<77.5 | Class II Div 2: 67.5-<72.5.
- **Honours Class III is NOT awarded for 1862.** Below 67.5 the student graduates with Honours but no grade of Honours.
- For more detail call lookup_uow_policy_tool with topic "honours".

## PROFESSIONAL EXPERIENCE
- 12 weeks (420 hours) of work-based learning / placement is compulsory before the end of the degree.
- Professional Options (Section E, up to 18 CP) let students who work in relevant industries count that experience toward the degree.
- Part-time students in Mechatronic or Biomedical majors in approved full-time engineering employment may be exempted from up to three specified subjects.

---

## (A) ENGINEERING YEAR 1 — COMMON CORE (48 CP)
- ENGG100 (6 CP) | Engineering Computing and Analysis | Spr | Prereq: None
- ENGG102 (6 CP) | Fundamentals of Engineering Mechanics | Aut | Prereq: None
- ENGG103 (6 CP) | Materials in Design | Aut | Prereq: None
- ENGG104 (6 CP) | Electrical Systems | Spr | Prereq: None
- ENGG105 (6 CP) | Engineering Design for Sustainability | Aut | Prereq: None
- MATH141 (6 CP) | Foundations of Engineering Mathematics | Aut/Spr | Prereq: MATH140 or MATH010 or a mark of at least 65 in MATH151 OR HSC Advanced Mathematics Band 2 or better
- MATH142 (6 CP) | Essentials of Engineering Mathematics | Spr/Sum | Prereq: MATH141 or MATH161 or MATH187
- PHYS143 (6 CP) | Physics For Engineers | Spr | Prereq: None

---

## (B) ENGINEERING MAJORS (144 CP each, Years 2-4 + List A electives + Professional Experience)
Only use the student's declared engineering major. Call lookup_major_tool with its code for the year-by-year subject list — do not reproduce it from memory.

---

## (C) COMPUTER SCIENCE CORE (66 CP) + CAPSTONE (12 CP)
- CSIT115 (6 CP) | Database Management Systems | Aut/Spr | Prereq: None
- CSIT121 (6 CP) | Object Oriented Design and Programming | Aut/Spr | Prereq: CSIT110 OR CSIT111 OR ENGG100
- CSIT123 (6 CP) | Computing and Cyber Security Fundamentals | Aut | Prereq: None
- CSIT127 (6 CP) | Networks and Communications | Spr | Prereq: None | NOT required for SECTE majors (replaced by ECTE364)
- CSIT128 (6 CP) | Introduction to Web Technology | Aut/Spr | Prereq: None
- CSCI203 (6 CP) | Algorithms and Data Structures | Spr | Prereq: (CSIT110 or CSIT111) AND (CSIT113 or CSIT123)
- CSIT205 (6 CP) | Generative AI | Aut | Prereq: None
- CSIT226 (6 CP) | Human Computer Interaction | Spr | Prereq: None
- CSCI235 (6 CP) | Database Systems | Aut | Prereq: CSIT115
- CSCI251 (6 CP) | Advanced Programming | Spr | Prereq: CSIT121 or CSIT213
- CSIT314 (6 CP) | Software Development Methodologies | Aut | Prereq: CSIT214 AND 12 CP at 200-level CSCI/ISIT
- CSIT321 (12 CP) | Project (Capstone, annual) | Aut/Spr | Prereq: CSIT214 AND 18 CP at 200-level CSCI/CSIT/ISIT | Coreq: CSIT226 AND CSIT314

### Prerequisite traps (flag these, do not silently resolve)
- CSIT121 is satisfied by ENGG100 (Year 1 engineering core), so CSIT110 is not needed.
- CSIT314 and CSIT321 require CSIT214, which is NOT in the 1862 core. The student must take CSIT214 (it counts toward the CS component) or obtain a prerequisite waiver — tell them to check with the CS Academic Program Director.
- CSIT321 is split into Part 1 and Part 2 (6 CP each) in consecutive sessions, as for 766.

---

## (D) COMPUTER SCIENCE MAJORS (optional, 24 CP)
AI & Big Data (MAJ44204), Cyber Security (MAJ40516), Digital Systems Security (MAJ40164), Game and Mobile Development (MAJ41477), Software Engineering (MAJ40277). Call lookup_major_tool for the list. Without a CS major, apply rule (b)(ii).

---

## (E) PROFESSIONAL OPTIONS (up to 18 CP)
- ENGG255 (6 CP) | Professional Option 2 | Annual/Aut/Spr | Prereq: None
- ENGG355 (6 CP) | Professional Option 3 | Annual/Aut/Spr | Prereq: None
- ENGG455 (6 CP) | Professional Option 4 | Annual/Aut/Spr | Prereq: None
Only available to students working in appropriate industries.

---

## Student Enrolment Record Format
Same as 766. A subject is **Complete** if Grade is one of HD, D, C, P, PS, S and Status is "Complete", or it is a Specified Credit. TF, F, N, NH, W, WF, AF or blank grades do not count.

---

## EXECUTION STEPS & AUDIT PROTOCOL

### STAGE 1: ANALYSIS & AUDIT
1. Identify Commencement Year, Engineering major (required) and CS major (optional). If no engineering major is declared, ask for it before planning.
2. Set Target_CP = the engineering major's minimum (264 / 270 / 282).
3. Audit completed and enrolled subjects:
   - Eng_Year1_CP = [X] / 48 CP
   - Eng_Major_CP = [X] CP (from lookup_major_tool)
   - CS_Core_CP = [X] / 78 CP (66 core + 12 capstone; minus CSIT127 for SECTE majors)
   - CS_Major_or_300_level_CP = [X] / 24 CP
   - Hundred_Level_CP = [X] / max 90 CP
   - Total_Earned = [X] / Target_CP
4. If marks are available, estimate the Method 2 honours WAM and the likely class (no Class III).

### STAGE 2: SESSION SCRATCHPAD
1. Plan every future session until Target_CP is reached, following the engineering major's year order.
2. Apply Session Filters (Availability, Prereq <= N-1, Coreq <= N).
3. Session Load: max 4 subjects / 24 CP.
4. Verify: total ≥ Target_CP, 100-level CP ≤ 90, CS core complete (except exempt subjects), CSIT321 in two consecutive sessions, no invented codes.
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
    {
        "year": 2026,
        "course": "1802",
        "campus": "Wollongong",
        "information": HANDBOOK_1802_2026_WOLLONGONG,
    },
    {
        "year": 2026,
        "course": "1862",
        "campus": "Wollongong",
        "information": HANDBOOK_1862_2026_WOLLONGONG,
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


# async def seed() -> None:
#     async with AsyncSessionLocal() as session:
#         for entry in SEED_DATA:
#             result = await session.execute(
#                 select(Handbook).where(
#                     Handbook.year == entry["year"],
#                     Handbook.course == entry["course"],
#                     Handbook.campus == entry["campus"],
#                 )
#             )
#             if result.scalar_one_or_none():
#                 print(f"Skipping {entry['course']} {entry['year']} ({entry['campus']}) — already exists")
#                 continue
#             session.add(Handbook(**entry))
#             print(f"Inserted {entry['course']} {entry['year']} ({entry['campus']})")
#         for course in KB_COURSES:
#             await seed_knowledge_base(session, course)
#         await session.commit()
#     print("Seed complete.")

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
