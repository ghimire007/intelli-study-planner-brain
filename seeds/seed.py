"""
Seed script — inserts initial handbook data into the DB.
Run via: make seed
"""
import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.handbook import Handbook

HANDBOOK_766_2026 = """# 766 — Bachelor of Computer Science

## Metadata
- **Handbook Year:** 2026
- **Faculty:** Faculty of Engineering and Information Sciences
- **Award Title:** Bachelor of Computer Science
- **Award Type:** Undergraduate
- **Total Credit Points:** 144
- **Duration (Full Time):** 3 Year(s)
- **Duration (Part Time):** 6 Year(s)
- **Post Nominal:** BCompSci
- **Accreditation:** Australian Computer Society (ACS) — accredited until 2029

## Global Rules
- Total 144 credit points required
- Maximum **60 credit points** of **100-level** subjects (includes core)
- Core subjects: 96 credit points total (78 fixed + 6 choice + 12 capstone)
- If undertaking a major: complete 24 credit points from chosen major(s)
- If NOT undertaking a major: complete 18 credit points of 300-level CSCI/CSIT/ISIT + 6 credit points at 200/300-level CSCI/CSIT/ISIT not in the core
- Electives fill remaining credit points to reach 144 total (any CSIT/CSCI/ISIT not in core/major, or General Schedule)
- Double major available: maximum 1 subject may be cross-counted between two majors

## Course Structure

### Core Subjects — 78 Credit Points
Complete all 13 of the following subjects:

| Subject Code | Credit Points | Title |
|-------------|---------------|-------|
| CSIT110 | 6 | Fundamental Programming with Python |
| CSIT123 | 6 | Computing and Cyber Security Fundamentals |
| CSIT114 | 6 | System Analysis |
| CSIT115 | 6 | Database Management Systems |
| CSIT121 | 6 | Object Oriented Design and Programming |
| CSIT127 | 6 | Networks and Communications |
| CSIT128 | 6 | Introduction to Web Technology |
| CSCI235 | 6 | Database Systems |
| CSIT214 | 6 | IT Project Management |
| CSIT205 | 6 | Generative AI |
| CSCI203 | 6 | Algorithms and Data Structures |
| CSIT226 | 6 | Human Computer Interaction |
| CSIT314 | 6 | Software Development Methodologies |

### Core Selection — 6 Credit Points
Complete ONE of the following:

| Subject Code | Credit Points | Title |
|-------------|---------------|-------|
| CSCI251 | 6 | Advanced Programming |
| CSIT213 | 6 | Java Programming |

### Capstone — 12 Credit Points
Annual subject — completed in the final year.

| Subject Code | Credit Points | Title | Session Availability |
|-------------|---------------|-------|---------------------|
| CSIT321 | 12 | Project | Annual (full year) |

### Available Majors — 24 Credit Points each
Select one or two. Note: 300-level major subjects may have 100 and 200-level prerequisites not listed in the major.

| Major Code | Credit Points | Title | Wollongong | Liverpool |
|------------|---------------|-------|-----------|-----------|
| MAJ44204 | 24 | Artificial Intelligence and Big Data | Yes | Yes |
| MAJ40516 | 24 | Cyber Security | Yes | Yes |
| MAJ40277 | 24 | Software Engineering for Bachelor of Computer Science | Yes | Yes |
| MAJ40164 | 24 | Digital Systems Security | Yes | No |
| MAJ41477 | 24 | Game and Mobile Development | Yes | No |

### No-Major Path — 24 Credit Points
If not undertaking a major, complete:
- 18 credit points of 300-level CSCI, CSIT, or ISIT subjects not in the core
- 6 credit points at 200 or 300-level CSCI, CSIT, or ISIT not in the core

### Electives
Remaining credit points to reach 144 total:
- Any CSIT, CSCI, or ISIT subjects not already in core or major
- Or General Schedule subjects
- Maximum 60 credit points at 100-level (includes core)

## Honours Pathway
| Code | Credit Points | Title | Entry Requirement |
|------|---------------|-------|------------------|
| 765 | 48 | Bachelor of Computer Science (Honours) | Average >= 75% across major + Distinction in 2 of the 300-level major subjects. Consult Academic Program Director well in advance. |

## Discontinued Subjects & Equivalency Mappings
| Old Subject Code | Discontinued Year | Replacement Code | Notes |
|-----------------|-------------------|-----------------|-------|
| ISIT204 | 2024 | CSIT305 | Approved direct replacement |
| ISIT207 | 2023 | CSIT305 | Check with faculty for partial credit |

## Learning Outcomes
1. Demonstrate an understanding of core knowledge of computer fundamentals and the ability to apply theoretical basis of computer science to solve a range of practical problems.
2. Design and develop innovative software solutions for a variety of applications.
3. Design, develop, and employ novel approaches and algorithms in solving practical problems.
4. Deploy appropriate theory, practices, and tools for the specification, design, implementation, and maintenance as well as the evaluation of computer-based systems.
5. Function effectively as part of a team to accomplish a set of common goals and objectives and communicate with project stakeholders.
6. Adopt a professional and ethical approach to decision making and related social responsibilities.

## Contact
- **Faculty enquiries:** askuow@uow.edu.au
- **Source URL:** https://courses.uow.edu.au/courses/2026/766
- **Last verified:** 2026-04-05
"""

SEED_DATA = [
    {"year": 2026, "course": "766", "information": HANDBOOK_766_2026},
]


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        for entry in SEED_DATA:
            result = await session.execute(
                select(Handbook).where(
                    Handbook.year == entry["year"],
                    Handbook.course == entry["course"],
                )
            )
            if result.scalar_one_or_none():
                print(f"Skipping {entry['course']} {entry['year']} — already exists")
                continue
            session.add(Handbook(**entry))
            print(f"Inserted {entry['course']} {entry['year']}")
        await session.commit()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
