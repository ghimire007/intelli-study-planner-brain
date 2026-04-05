# UOW Handbook — Database Entry Template

This document defines the standard format for the `information` field in the `handbook` table.
Every handbook row must follow this template exactly. The format is designed to be:
- Human-readable markdown
- LLM-parseable with consistent section headers
- Complete enough to enforce all degree rules without needing external lookups

---

## Template (copy and fill for each entry)

```markdown
# [COURSE CODE] — [COURSE TITLE]

## Metadata
- **Handbook Year:** [e.g. 2025]
- **Faculty:** [e.g. Faculty of Engineering and Information Sciences]
- **Award Title:** [e.g. Bachelor of Computer Science]
- **Award Type:** [Undergraduate | Postgraduate | Honours]
- **Total Credit Points:** [e.g. 144]
- **Duration (Full Time):** [e.g. 3 Year(s)]
- **Duration (Part Time):** [e.g. 6 Year(s)]
- **Post Nominal:** [e.g. BCompSci]
- **CRICOS Code:** [e.g. 081145A — omit if not applicable]
- **UAC Code:** [e.g. 755300 — omit if not applicable]

## Delivery
| Campus | Mode | Intakes | Available |
|--------|------|---------|-----------|
| [e.g. Wollongong] | [On-Campus / Online / Hybrid] | [Autumn, Spring / Autumn only / Spring only] | [Yes / No] |
| [e.g. Shoalhaven] | [On-Campus] | [Autumn, Spring] | [Yes / No] |

## Course Variants
<!-- List all variant codes if the course has alternate pathways -->
| Code | Variant Name | Key Difference |
|------|-------------|----------------|
| [e.g. 344] | Standard | Default pathway |
| [e.g. Q344] | Pathway to Primary Education | Replaces 30cp electives with Foundations in Teaching minor (24cp) + 6cp elective |

## Global Rules
<!-- Hard rules enforced regardless of year/session. The Rule Validator uses these. -->
- Maximum **[X] credit points** of **[level]-level** subjects (e.g. max 60 CP of 100-level subjects)
- [Any WAM requirement for standard progression, e.g. WAM ≥ 65 to enrol in 900-level subjects in Q344]
- No more than one subject may be cross-counted towards a minor, major, or core degree requirement
- [Any other global constraints]

## Admission / WAM Requirements
<!-- Entry conditions or in-progress WAM thresholds -->
| Condition | Requirement |
|-----------|-------------|
| [e.g. Enrolment in 900-level subjects (Q344)] | WAM ≥ 65 |
| [e.g. Preferential admission to Master of Teaching (Primary)] | WAM ≥ 65 at graduation |
| [Any other threshold] | [Value] |

## Course Structure

### Year 1 — 48 Credit Points

#### Autumn Session — 24 Credit Points
<!-- IMPORTANT: mark session-locked subjects. Autumn-only / Spring-only subjects cause 1-year delays if missed. -->

**Core Subjects (must complete all):**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| [e.g. CSIT111] | 6 | [Title] | Autumn & Spring | None |
| [e.g. CSIT121] | 6 | [Title] | Autumn only | None |
| [e.g. MATH141] | 6 | [Title] | Autumn & Spring | None |
| [e.g. CSIT115] | 6 | [Title] | Autumn only | None |

#### Spring Session — 24 Credit Points

**Core Subjects:**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| [Subject] | 6 | [Title] | Spring only | [e.g. CSIT111] |

**Remaining [X] credit points from:**
- Selected major; OR
- A minor; OR
- General Schedule electives

---

### Year 2 — 48 Credit Points

#### Autumn Session — 24 Credit Points

**Core Subjects:**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| [Subject] | 6 | [Title] | Autumn & Spring | [prereq] |

**Remaining [X] credit points from:** major / minor / electives

#### Spring Session — 24 Credit Points

**Core Subjects:**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| [Subject] | 6 | [Title] | Spring only | [prereq] |

**Remaining [X] credit points from:** major / minor / electives

---

### Year 3 — 48 Credit Points

#### Autumn Session — 24 Credit Points

**Core Subjects:**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| [Subject] | 6 | [Title] | Autumn only | [prereq] |

**Remaining [X] credit points from:** major / minor / electives

#### Spring Session — 24 Credit Points
**Complete [X] credit points from:** major / minor / electives

---

## Available Majors

### [Campus Name] Campus
| Major Code | Credit Points | Title | Notes |
|------------|---------------|-------|-------|
| [e.g. MAJ01234] | 48 | [Major Title] | [e.g. recommended for AI track] |
| [e.g. MAJ05678] | 48 | [Major Title] | |

### [Other Campus] Campus
| Major Code | Credit Points | Title | Notes |
|------------|---------------|-------|-------|
| [MAJ code] | 48 | [Title] | [Subset of Wollongong offerings if applicable] |

---

## Available Minors

### [Campus Name] Campus
<!-- Minors can count toward elective requirements unless otherwise specified -->
| Minor Code | Credit Points | Title | Eligibility Restriction |
|------------|---------------|-------|------------------------|
| [e.g. MIN1225] | 24 | [Minor Title] | None |
| [e.g. MIN3079] | 24 | [Minor Title] | [e.g. Final year only; WAM ≥ 65] |

### [Other Campus] Campus
| Minor Code | Credit Points | Title | Eligibility Restriction |
|------------|---------------|-------|------------------------|
| [MIN code] | 24 | [Title] | None |

---

## Variant Pathway: [Variant Name] ([Variant Code])
<!-- Repeat this section for each course variant defined in Course Variants above -->

### Changed Rules vs Standard
- [List only what differs — e.g. "30cp elective block replaced by Foundations in Teaching minor (24cp) + 1x 6cp elective"]
- [WAM threshold changes, subject substitutions, etc.]

### Changed Structure (Year/Session level — only show what differs)

#### Year 3 — 48 Credit Points

##### Autumn Session — 30 Credit Points

**Core Subjects:**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| [Subject] | 6 | [Title] | Autumn only | [prereq] |

**Plus 12 credit points at 900-level from Foundations in Teaching minor**

##### Spring Session — 18 Credit Points
**6 credit points at 900-level from Foundations in Teaching minor + 18 cp from major / electives**

### Variant-Specific Minor
| Minor Code | Credit Points | Title | Note |
|------------|---------------|-------|------|
| [e.g. MIN3005] | 24 | Foundations in Teaching | Replaces elective block; 18cp credited toward Master of Teaching (Primary) on graduation |

---

## Articulation & Credit Transfer
<!-- Subjects from this degree that count toward postgraduate degrees, or advanced standing arrangements -->
| Arrangement | Detail |
|-------------|--------|
| [e.g. 18cp from Foundations in Teaching minor (900-level)] | Credited toward Master of Teaching (Primary) on graduation with WAM ≥ 65 |
| [Any other RPL or advanced standing] | [Details] |

---

## Discontinued Subjects & Equivalency Mappings
<!-- CRITICAL for rule validation. Students enrolled under older handbooks may hold these. -->
| Old Subject Code | Old Title | Discontinued Year | Replacement Code | Replacement Title | Notes |
|-----------------|-----------|-------------------|-----------------|-------------------|-------|
| [e.g. ISIT204] | [Old Title] | [e.g. 2024] | [e.g. CSIT305] | [New Title] | Approved direct replacement; no additional requirements |
| [e.g. ISIT207] | [Old Title] | [e.g. 2023] | [e.g. CSIT305] | [New Title] | Partial credit — check with faculty |

---

## Learning Outcomes
1. [Outcome 1]
2. [Outcome 2]
3. [Outcome 3]
<!-- Add all as numbered list -->

---

## Contact
- **Faculty enquiries:** [e.g. askuow@uow.edu.au]
- **Source URL:** [handbook URL]
- **Last verified:** [YYYY-MM-DD]
```

---

## Filled Example — Course 344, Bachelor of Social Science (2025)

The following is a complete example based on the real UOW handbook (scraped 2026-04-05).

```markdown
# 344 — Bachelor of Social Science

## Metadata
- **Handbook Year:** 2025
- **Faculty:** Faculty of the Arts, Social Sciences and Humanities
- **Award Title:** Bachelor of Social Science
- **Award Type:** Undergraduate
- **Total Credit Points:** 144
- **Duration (Full Time):** 3 Year(s)
- **Duration (Part Time):** 6 Year(s)
- **Post Nominal:** BSocSc
- **CRICOS Code:** 081145A
- **UAC Code:** 755300

## Delivery
| Campus | Mode | Intakes | Available |
|--------|------|---------|-----------|
| Wollongong | On-Campus | Autumn, Spring | Yes |
| Shoalhaven | On-Campus | Autumn, Spring | Yes |

## Course Variants
| Code | Variant Name | Key Difference |
|------|-------------|----------------|
| 344 | Standard | Default pathway |
| Q344 | Pathway to Primary Education | 30cp elective block replaced by Foundations in Teaching minor (24cp) + 1x 6cp elective; WAM ≥ 65 required for 900-level subjects and preferential PG admission |

## Global Rules
- Maximum **60 credit points** of **100-level** subjects
- No more than one subject may be cross-counted towards a minor, major, or core degree requirement
- Q344 variant: WAM ≥ 65 required to enrol in 900-level subjects in Year 3

## Admission / WAM Requirements
| Condition | Requirement |
|-----------|-------------|
| Enrolment in 900-level subjects (Q344 only) | WAM ≥ 65 |
| Preferential admission to Master of Teaching (Primary) | WAM ≥ 65 at graduation |
| Enrolment in Public Health Extension minor | Final year of study + WAM ≥ 65 |
| Course transfer from 344 → Q344 | Must request prior to commencing 300-level subjects |

## Course Structure

### Year 1 — 48 Credit Points

#### Autumn Session — 24 Credit Points

**Core Subjects (must complete all):**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| GEOG121 | 6 | Life in a Globalising World | Autumn & Spring | None |
| HAS120 | 6 | Becoming a Social Scientist: Interdisciplinary Competencies | Autumn & Spring | None |
| HAS130 | 6 | Social Determinants of Health | Autumn & Spring | None |
| SOC103 | 6 | Introduction to Sociology | Autumn & Spring | None |

#### Spring Session — 24 Credit Points

**Core Subjects:**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| CRL100 | 6 | Career Ready Learning | Spring only | None |

**Remaining 18 credit points from:** selected major; OR a minor; OR General Schedule electives

---

### Year 2 — 48 Credit Points

#### Autumn Session — 24 Credit Points

**Core Subjects:**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| GEOG221 | 6 | Population, Migration, Inequality | Autumn & Spring | None |
| HAS205 | 6 | Quantitative Research Design and Analysis | Autumn & Spring | None |

**Remaining 12 credit points from:** selected major; OR a minor; OR General Schedule electives

#### Spring Session — 24 Credit Points

**Core Subjects:**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| CRLP200 | 6 | Career Ready Learning & Practice | Spring only | CRL100 |
| GEOG123 | 6 | Indigenous Geographies: Questioning Country | Spring only | None |

**Remaining 12 credit points from:** selected major; OR a minor; OR General Schedule electives

---

### Year 3 — 48 Credit Points

#### Autumn Session — 24 Credit Points

**Core Subjects:**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| HAS302 | 6 | Community Matters: Research and Responses | Autumn only | None |
| GEOG336 | 6 | Qualitative Research Design for Social Scientists | Autumn only | None |

**Remaining 12 credit points from:** selected major; OR a minor; OR General Schedule electives

#### Spring Session — 24 Credit Points
**Complete 24 credit points from:** selected major; OR a minor; OR General Schedule electives

---

## Available Majors

### Wollongong Campus
| Major Code | Credit Points | Title | Notes |
|------------|---------------|-------|-------|
| MAJ40159 | 48 | Criminology | |
| MAJ44184 | 48 | Human Services | Also available at Shoalhaven |
| MAJ40177 | 48 | Sociology | Also available at Shoalhaven |
| MAJ44301 | 48 | Public Health | |
| MAJ44313 | 48 | Environment and Society | |

### Shoalhaven Campus
| Major Code | Credit Points | Title | Notes |
|------------|---------------|-------|-------|
| MAJ44184 | 48 | Human Services | |
| MAJ40177 | 48 | Sociology | |

---

## Available Minors

### Wollongong Campus
| Minor Code | Credit Points | Title | Eligibility Restriction |
|------------|---------------|-------|------------------------|
| MIN1331 | 24 | Criminology | None |
| MIN3033 | 24 | Human Services | None |
| MIN1292 | 24 | Introduction to Public Health | None |
| MIN1225 | 24 | Psychology | None |
| MIN3079 | 24 | Public Health Extension | Final year only; WAM ≥ 65 |
| MIN1253 | 24 | Sociology | None |

### Shoalhaven Campus
| Minor Code | Credit Points | Title | Eligibility Restriction |
|------------|---------------|-------|------------------------|
| MIN3033 | 24 | Human Services | None |
| MIN1253 | 24 | Sociology | None |

---

## Variant Pathway: Pathway to Primary Education (Q344)

### Changed Rules vs Standard
- 30cp elective block replaced by **Foundations in Teaching minor (24cp) + 1x 6cp elective**
- WAM ≥ 65 required to enrol in 900-level subjects in Year 3
- WAM ≥ 65 at graduation for preferential admission to Master of Teaching (Primary)
- Only available at **Wollongong campus**
- Transfer from 344 → Q344 must be requested **before** commencing 300-level subjects

### Changed Structure (Year 3 only — Years 1 & 2 identical to standard)

#### Year 3 — 48 Credit Points

##### Autumn Session — 30 Credit Points

**Core Subjects:**
| Subject Code | Credit Points | Title | Session Availability | Prerequisites |
|-------------|---------------|-------|---------------------|---------------|
| HAS302 | 6 | Community Matters: Research and Responses | Autumn only | None |
| GEOG336 | 6 | Qualitative Research Design for Social Scientists | Autumn only | None |

**Plus 12 credit points at 900-level from Foundations in Teaching minor (WAM ≥ 65 required)**

##### Spring Session — 18 Credit Points
**6 credit points at 900-level from Foundations in Teaching minor + 12 credit points from selected major or electives**

### Variant-Specific Minor
| Minor Code | Credit Points | Title | Note |
|------------|---------------|-------|------|
| MIN3005 | 24 | Foundations in Teaching | Replaces elective block; 18cp (900-level) credited toward Master of Teaching (Primary) upon graduation with WAM ≥ 65 |

---

## Articulation & Credit Transfer
| Arrangement | Detail |
|-------------|--------|
| 18cp from Foundations in Teaching minor (900-level subjects, Q344) | Credited toward Master of Teaching (Primary); available up to 2 years post-graduation |
| Priority admission quota for Master of Teaching (Primary) | Based on academic merit (WAM) if places are restricted |

---

## Discontinued Subjects & Equivalency Mappings
| Old Subject Code | Old Title | Discontinued Year | Replacement Code | Replacement Title | Notes |
|-----------------|-----------|-------------------|-----------------|-------------------|-------|
| — | — | — | — | — | No discontinued subjects recorded for this course as of 2025 |

---

## Learning Outcomes
1. Integrate knowledge and understanding of the interdisciplinary nature of the social sciences and social science practice.
2. Consolidate and synthesise theoretical and practical knowledge of the dynamics of social systems and practices in different settings and apply this to their chosen speciality.
3. Inquire into the dynamics of particular social problems and practices using established social science protocols consistent with their speciality.
4. Inquire into and address ongoing learning needs.
5. Analyse unpredictable, complex problems, issues and situations; apply creative, logical and critical thinking skills; and form evidence-based judgements regarding possible solutions.
6. Articulate ideas using a wide range of techniques effective with different audiences, including experts and non-experts.
7. Work collaboratively with a range of people in different cultural, cross-cultural and regional contexts to best effect desired and desirable social change.
8. Recognise the importance of ethical practice, social responsibility, social justice and civic awareness when acting to resolve conflicts, address problems and respond to social and environmental challenges.

---

## Contact
- **Faculty enquiries:** askuow@uow.edu.au
- **Source URL:** https://courses.uow.edu.au/courses/2025/344
- **Last verified:** 2026-04-05
```

---

## Edge Cases Covered by This Template

| Edge Case | Where Handled |
|-----------|--------------|
| Multiple course variants / pathways (e.g. 344 vs Q344) | `Course Variants` table + `Variant Pathway` section |
| Multiple campuses with different subject offerings | `Delivery` table + per-campus `Majors` / `Minors` tables |
| Session-locked subjects (Autumn-only / Spring-only) | `Session Availability` column in every subject table |
| Prerequisites and corequisites | `Prerequisites` column in every subject table |
| Discontinued subjects with equivalency mappings | `Discontinued Subjects & Equivalency Mappings` section |
| Credit point caps (e.g. max 60 CP at 100-level) | `Global Rules` section |
| WAM thresholds for enrolment or progression | `Admission / WAM Requirements` table |
| Cross-counting restrictions (minor/major/core overlap) | `Global Rules` section |
| Postgraduate subjects embedded in undergraduate degree (900-level in Q344) | `Variant Pathway` changed structure |
| Articulation / credit transfer to postgraduate degrees | `Articulation & Credit Transfer` section |
| Handbook year vs commencement year divergence | `Metadata.Handbook Year` + matched by `year` DB column |
| Elective flexibility (major / minor / general schedule) | "Remaining X credit points from" notes per session |
| Restricted minors (eligibility conditions) | `Eligibility Restriction` column in Minors table |
| Course transfer deadlines (variant switching) | `Changed Rules vs Standard` in Variant Pathway section |
