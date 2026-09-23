"""The allowlist projection: what must never survive it, and what must.

Both halves matter. The first stops a leak; the second stops a future privacy
tweak from quietly breaking the planner by dropping something it needs.
"""
import pathlib
import re

import pytest
from app.services.enrolment import (
    KNOWN_GRADES,
    KNOWN_SESSIONS,
    KNOWN_STATUSES,
    UnreadableRecord,
    parse_enrolment,
    project,
)

pytestmark = pytest.mark.smoke

RECORDS = sorted((pathlib.Path(__file__).parents[1] / "app" / "test_records").glob("*.md"))

# Identifiers that appear in the fixtures and must not reach a provider.
FORBIDDEN = [
    "OKONKWO", "WHITFIELD", "SHARMA", "MCALLISTER", "HASHIMOTO", "REYES",
    "DIALLO", "NGUYEN", "ODUYA",              # surnames
    "Rebecca", "TANG",                        # a supervisor: a third party
    "Keio", "TAFE NSW",                       # prior institutions, from Note lines
    "Effective Date", "Honours GPA",          # quasi-identifying / performance
    "Start Smart", "Consent Matters",         # supplementary qualifications
    "Leave of Absence.",                      # the Note sentence, not the status
]


def _fixtures():
    return [pytest.param(path, id=path.stem) for path in RECORDS]


def test_fixtures_are_present():
    """Guard against the corpus silently emptying and every test below passing."""
    assert len(RECORDS) >= 12


@pytest.mark.parametrize("path", _fixtures())
def test_no_identifiers_survive(path):
    projected = project(path.read_text())
    assert [word for word in FORBIDDEN if word in projected] == []


@pytest.mark.parametrize("path", _fixtures())
def test_no_student_number_survives(path):
    assert re.search(r"\b\d{7,8}\b", project(path.read_text())) is None


@pytest.mark.parametrize("path", _fixtures())
def test_no_marks_survive(path):
    """Marks are dropped structurally, so check the parsed rows, not the string.

    A two-digit mark can coincide with a credit-point value or a year, which
    makes searching the rendered text both noisy and unconvincing.
    """
    record = parse_enrolment(path.read_text())
    assert not any(hasattr(row, "mark") for row in record.rows)
    # Nominal CP is the only number on a row besides the year, and it is small.
    assert all(row.nom_cp <= 48 for row in record.rows)


@pytest.mark.parametrize("path", _fixtures())
def test_every_subject_survives(path):
    """Every code, CP, grade and status in the paste comes out the other side."""
    raw = path.read_text()
    record = parse_enrolment(raw)
    projected = project(raw)

    raw_codes = re.findall(r"\|\s*([A-Z]{2,4}\d{3}[A-Z]?)\s*\|", raw)
    assert raw_codes, "fixture has no subject codes to check"
    assert {row.code for row in record.rows} <= set(raw_codes)

    for row in record.rows:
        assert row.code in projected
        assert row.status in projected
        if row.grade:
            assert row.grade in KNOWN_GRADES


def test_failed_and_uncounted_rows_keep_their_meaning():
    """The rows a careless projection would flatten into "incomplete"."""
    everything = [parse_enrolment(path.read_text()) for path in RECORDS]
    for path in RECORDS:
        record = parse_enrolment(path.read_text())
        print("\n", path.name, len(record.rows))
        for row in record.rows:
            print(row.code, row.status)
    rows = [row for record in everything for row in record.rows]

    from collections import Counter

    print("\nALL SUBJECTS")
    for code, count in Counter(row.code for row in rows).items():
        print(code, count)

    for row in rows:
        if row.status == "Not Counted (Prior Course)":
            print("UNCOUNTED:", row)

    by_status = {}
    for row in rows:
        by_status.setdefault(row.status, []).append(row)

    print("\nSTATUS COUNTS")
    for status, items in by_status.items():
        print(status, len(items))

    print("\nALL ROW COUNT BY CODE")
    from collections import Counter
    for code, count in Counter(row.code for row in rows).items():
        if count > 2:
            print(code, count)

    assert len(rows) == 161
    assert len(by_status["Withdrawn"]) == 7
    assert len(by_status["Leave of Absence"]) == 4
    assert len(by_status["Not Counted (Prior Course)"]) == 3
    assert len([row for row in rows if row.grade == "F"]) == 2

    # A prior-course row passed but must not read as ordinary completion.
    prior = by_status["Not Counted (Prior Course)"]
    assert all(row.grade in {"D", "HD"} for row in prior)
    assert all(row.status != "Complete" for row in prior)


def test_double_major_keeps_both_majors():
    record = parse_enrolment((RECORDS[0].parent / "third_year_double_major.md").read_text())
    assert record.majors == ["AIBD", "CSEC"]


def test_undeclared_major_yields_none():
    record = parse_enrolment((RECORDS[0].parent / "first_year_sem_1.md").read_text())
    assert record.majors == []


@pytest.mark.parametrize("path", _fixtures())
def test_parser_metadata_still_extractable(path):
    """The projection must still carry what sols_parser reads back out of it."""
    projected = project(path.read_text())
    record = parse_enrolment(path.read_text())
    assert f"**Course:** {record.course_code}" in projected
    assert "**Campus:** Wollongong" in projected
    assert str(min(row.year for row in record.rows)) in projected


class TestFailsClosed:
    """An unreadable paste is rejected, never passed through as raw text."""

    def test_prose_with_no_table(self):
        with pytest.raises(UnreadableRecord):
            project("Hi, I'm a second year student and I want to plan my degree.")

    def test_empty(self):
        with pytest.raises(UnreadableRecord):
            project("")

    def test_unknown_grade(self):
        with pytest.raises(UnreadableRecord, match="not a known grade"):
            project(
                "| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| 2025 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 78 | ZZ | Complete |\n"
            )

    def test_unknown_status(self):
        with pytest.raises(UnreadableRecord, match="not a known enrolment status"):
            project(
                "| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| 2025 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 78 | D | Vibing |\n"
            )

    def test_misaligned_columns(self):
        with pytest.raises(UnreadableRecord, match="columns"):
            project(
                "| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| 2025 | Autumn | CSIT110 | 6 | D | Complete |\n"
            )

    def test_unrecognised_table_is_skipped_not_parsed(self):
        """A table we do not know contributes nothing, and cannot rescue a paste."""
        with pytest.raises(UnreadableRecord):
            project("| Code | Description |\n|---|---|\n| Start Smart | EAIS |\n")

# ---------------------------------------------------------------------------
# A paste that lost its table markup.
#
# Copying the record out of SOLS through a plain-text field can collapse it
# into a single run of words: no pipes, no tabs, no line breaks. Mark and grade
# are then absent on an enrolled subject rather than left blank, so there is
# nothing positional left to lean on. The tests below hold the relaxed shape to
# the same bargain as the table parser — the same fields survive, nothing else
# does, and a row that cannot be read in full is refused.
# ---------------------------------------------------------------------------

# The paste that prompted all of this, verbatim.
FLAT_PASTE = (
    "Course: 1807 Bachelor of Information Technology Instance: 1807 "
    "Campus: Wollongong Delivery: On Campus Status: Active "
    "Major: Network Design and Management "
    "Year Session Campus/ Delivery Subject Code NomCP Mark Grade Status "
    "2026 Autumn Wollongong/ On Campus CSIT110 6 100 HD Complete "
    "2026 Autumn Wollongong/ On Campus CSIT114 6 93 HD Complete "
    "2026 Autumn Wollongong/ On Campus CSIT115 6 96 HD Complete "
    "2026 Autumn Wollongong/ On Campus CSIT123 6 87 HD Complete "
    "2026 Spring Wollongong/ On Campus CSIT121 6 Enrolled "
    "2026 Spring Wollongong/ On Campus CSIT127 6 Enrolled "
    "2026 Spring Wollongong/ On Campus CSIT128 6 Enrolled "
    "2026 Spring Wollongong/ On Campus CSIT226 6 Enrolled"
)

# The same record with every identifying line SOLS puts around it.
FLAT_PASTE_WITH_IDENTIFIERS = (
    "Enrolment Record Student: Mr Liam ODUYA (8801234) Effective Date: 07 April 2026 "
    "Course: 1807 Bachelor of Information Technology Campus: Wollongong Delivery: On Campus "
    "Major: Network Design and Management Honours GPA: 3.8 "
    "Note: Leave of Absence approved 2025. Supervisor: Rebecca TANG "
    "Year Session Campus/ Delivery Subject Code NomCP Mark Grade Status "
    "2026 Autumn Wollongong/ On Campus CSIT110 6 100 HD Complete"
)

ROW = "2026 Autumn Wollongong/ On Campus CSIT110 "


def _flat(text: str) -> str:
    """Collapse a record the way a plain-text paste does."""
    return " ".join(text.split())


class TestFlatPasteIsRead:
    """The paste that started this: every subject must come out of it."""

    def test_every_row_is_recovered(self):
        record = parse_enrolment(FLAT_PASTE)
        assert [row.code for row in record.rows] == [
            "CSIT110", "CSIT114", "CSIT115", "CSIT123",
            "CSIT121", "CSIT127", "CSIT128", "CSIT226",
        ]

    def test_completed_and_enrolled_rows_keep_their_meaning(self):
        record = parse_enrolment(FLAT_PASTE)
        assert [row.status for row in record.rows] == ["Complete"] * 4 + ["Enrolled"] * 4
        assert [row.grade for row in record.rows] == ["HD"] * 4 + [None] * 4

    def test_year_session_campus_and_cp_are_recovered(self):
        record = parse_enrolment(FLAT_PASTE)
        assert all(row.year == 2026 and row.nom_cp == 6 for row in record.rows)
        assert [row.session for row in record.rows] == ["Autumn"] * 4 + ["Spring"] * 4
        # "Wollongong/ On Campus" — only the campus half is on the allowlist.
        assert {row.campus for row in record.rows} == {"Wollongong"}

    def test_projection_is_a_table_the_prompt_can_read(self):
        projected = project(FLAT_PASTE)
        assert "| Year | Session | Campus | Subject Code | Nom CP | Grade | Status |" in projected
        assert "| 2026 | Autumn | Wollongong | CSIT110 | 6 | HD | Complete |" in projected
        assert "| 2026 | Spring | Wollongong | CSIT226 | 6 |  | Enrolled |" in projected


class TestFlatRowShapes:
    """Every row shape SOLS produces once the columns are gone."""

    @pytest.mark.parametrize(
        ("tail", "expected"),
        [
            ("6 100 HD Complete", (6, "HD", "Complete")),
            ("6 HD Complete", (6, "HD", "Complete")),          # grade, no mark
            ("6 78 Complete", (6, None, "Complete")),          # mark, no grade
            ("6 Enrolled", (6, None, "Enrolled")),             # neither
            ("12 Enrolled", (12, None, "Enrolled")),           # a double-CP subject
            ("6 WD Withdrawn", (6, "WD", "Withdrawn")),
            ("6 Leave of Absence", (6, None, "Leave of Absence")),
            ("6 85 D Not Counted (Prior Course)", (6, "D", "Not Counted (Prior Course)")),
        ],
        ids=["mark+grade", "grade only", "mark only", "bare", "12cp",
             "withdrawn", "leave", "prior course"],
    )
    def test_row_shape(self, tail, expected):
        row = parse_enrolment(ROW + tail).rows[0]
        assert (row.nom_cp, row.grade, row.status) == expected

    def test_grade_e_is_not_swallowed_by_the_word_enrolled(self):
        """"E" is a real grade and "Enrolled" starts with it; both must survive."""
        assert parse_enrolment(ROW + "6 E Complete").rows[0].grade == "E"
        assert parse_enrolment(ROW + "6 Enrolled").rows[0].grade is None

    def test_two_letter_grade_wins_over_its_first_letter(self):
        """"PS" must not be read as "P" with a stray "S" left over."""
        assert parse_enrolment(ROW + "6 72 PS Complete").rows[0].grade == "PS"

    @pytest.mark.parametrize("grade", sorted(KNOWN_GRADES))
    def test_every_known_grade_is_read(self, grade):
        assert parse_enrolment(ROW + f"6 78 {grade} Complete").rows[0].grade == grade

    @pytest.mark.parametrize("status", sorted(KNOWN_STATUSES))
    def test_every_known_status_is_read(self, status):
        assert parse_enrolment(ROW + f"6 78 HD {status}").rows[0].status == status

    @pytest.mark.parametrize("session", sorted(KNOWN_SESSIONS))
    def test_every_known_session_is_read(self, session):
        record = parse_enrolment(f"2026 {session} Wollongong CSIT110 6 78 HD Complete")
        assert record.rows[0].session == session

    @pytest.mark.parametrize(
        "campus", ["Wollongong", "Wollongong/On Campus", "Wollongong/ On Campus"]
    )
    def test_delivery_mode_is_dropped_from_the_campus(self, campus):
        record = parse_enrolment(f"2026 Autumn {campus} CSIT110 6 78 HD Complete")
        assert record.rows[0].campus == "Wollongong"

    def test_consecutive_rows_do_not_bleed_into_each_other(self):
        record = parse_enrolment(
            "2024 Autumn Wollongong CSIT110 6 96 HD Complete "
            "2025 Spring Wollongong/Online CSCI203 6 F Complete "
            "2026 Annual Wollongong CSIT321 12 Enrolled"
        )
        assert [(r.year, r.session, r.code, r.nom_cp, r.grade) for r in record.rows] == [
            (2024, "Autumn", "CSIT110", 6, "HD"),
            (2025, "Spring", "CSCI203", 6, "F"),
            (2026, "Annual", "CSIT321", 12, None),
        ]

    def test_a_tab_separated_copy_is_read(self):
        """Copying the table out of the browser keeps the rows but loses the pipes."""
        record = parse_enrolment(
            "Course: 766\n"
            "Year\tSession\tCampus/Delivery\tSubject Code\tNom CP\tMark\tGrade\tStatus\n"
            "2025\tAutumn\tWollongong/On Campus\tCSIT110\t6\t78\tD\tComplete\n"
        )
        assert [(row.code, row.grade) for row in record.rows] == [("CSIT110", "D")]
        assert record.course_code == "766"

    def test_a_run_together_markdown_table_is_read(self):
        """Pipes survived the paste but the line breaks did not."""
        record = parse_enrolment(
            "| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status | "
            "| 2025 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 78 | D | Complete |"
        )
        assert [(row.code, row.grade, row.status) for row in record.rows] == [
            ("CSIT110", "D", "Complete")
        ]


class TestFlatHeader:
    """The three allowlisted header fields, with no line breaks to delimit them."""

    def test_course_campus_and_major(self):
        record = parse_enrolment(FLAT_PASTE)
        assert record.course_code == "1807"
        assert record.campus == "Wollongong"
        # SOLS gives some majors as a title with no code. The advisor needs it
        # either way — lookup_major recovers the code from the title.
        assert record.majors == ["Network Design and Management"]

    def test_instance_is_not_mistaken_for_the_course(self):
        record = parse_enrolment("Instance: 1807 Course: 766 " + ROW + "6 HD Complete")
        assert record.course_code == "766"

    def test_campus_stops_before_the_delivery_label(self):
        record = parse_enrolment(
            "Campus: Wollongong Delivery: On Campus Status: Active " + ROW + "6 HD Complete"
        )
        assert record.campus == "Wollongong"

    def test_a_major_given_as_a_code_keeps_only_the_code(self):
        record = parse_enrolment(
            "Major: AIBD — Artificial Intelligence and Big Data " + ROW + "6 HD Complete"
        )
        assert record.majors == ["AIBD"]

    def test_both_majors_of_a_double_major(self):
        record = parse_enrolment(
            "Major: AIBD Second Major: CSEC " + ROW + "6 HD Complete"
        )
        assert record.majors == ["AIBD", "CSEC"]

    def test_undeclared_is_not_a_major(self):
        record = parse_enrolment("Major: Not yet declared " + ROW + "6 HD Complete")
        assert record.majors == []

    def test_a_record_with_no_header_still_yields_its_rows(self):
        record = parse_enrolment(ROW + "6 HD Complete")
        assert record.course_code is None and record.campus is None and record.majors == []
        assert len(record.rows) == 1


class TestFlatMatchesTheTableParser:
    """The relaxed shape must not quietly disagree with the strict one."""

    @pytest.mark.parametrize("path", _fixtures())
    def test_flattening_a_fixture_changes_nothing(self, path):
        """Same record, same rows — or a refusal, where credit cannot be read."""
        record = parse_enrolment(path.read_text())
        if record.specified_credit or record.unspecified_credit:
            with pytest.raises(UnreadableRecord, match="advanced standing"):
                parse_enrolment(_flat(path.read_text()))
        else:
            assert parse_enrolment(_flat(path.read_text())).rows == record.rows

    @pytest.mark.parametrize("path", _fixtures())
    def test_the_header_survives_flattening_too(self, path):
        record = parse_enrolment(path.read_text())
        if record.specified_credit or record.unspecified_credit:
            pytest.skip("refused outright; covered above")
        flat = parse_enrolment(_flat(path.read_text()))
        assert (flat.course_code, flat.campus, flat.majors) == (
            record.course_code, record.campus, record.majors
        )


class TestFlatLeaksNothing:
    """The allowlist does not loosen to make the relaxed shape work."""

    @pytest.mark.parametrize("path", _fixtures())
    def test_no_identifier_survives_a_flattened_fixture(self, path):
        try:
            projected = project(_flat(path.read_text()))
        except UnreadableRecord:
            return  # refused outright, so nothing reaches a provider at all
        assert [word for word in FORBIDDEN if word in projected] == []
        assert re.search(r"\b\d{7,8}\b", projected) is None

    def test_name_number_and_supervisor_do_not_survive(self):
        projected = project(FLAT_PASTE_WITH_IDENTIFIERS)
        for identifier in ("ODUYA", "Liam", "8801234", "Rebecca", "TANG", "Supervisor"):
            assert identifier not in projected

    def test_dates_and_performance_do_not_survive(self):
        projected = project(FLAT_PASTE_WITH_IDENTIFIERS)
        for dropped in ("Effective", "April", "Honours", "GPA", "3.8"):
            assert dropped not in projected

    def test_marks_do_not_survive(self):
        projected = project(FLAT_PASTE)
        for mark in ("100", "93", "96", "87"):
            assert mark not in projected

    def test_unallowlisted_header_text_does_not_survive(self):
        projected = project(FLAT_PASTE)
        for dropped in ("Bachelor", "Instance", "Delivery", "Active"):
            assert dropped not in projected

    def test_a_label_we_do_not_know_drops_its_field_rather_than_over_reading(self):
        """With no known terminator the value is unbounded, so it is not taken."""
        record = parse_enrolment(
            "Major: Data Science Some Unknown Label: junk Year Session " + ROW + "6 HD Complete"
        )
        assert record.majors == []
        assert "junk" not in project(
            "Major: Data Science Some Unknown Label: junk Year Session " + ROW + "6 HD Complete"
        )


class TestFlatFailsClosed:
    """A row that cannot be read in full is refused, never half-read."""

    def test_text_between_two_rows_is_not_skipped(self):
        with pytest.raises(UnreadableRecord, match="Could not read the subject row"):
            project(
                "2025 Autumn Wollongong CSIT110 6 78 D Complete "
                "Supervisor Rebecca TANG "
                "2025 Spring Wollongong CSIT121 6 Enrolled"
            )

    @pytest.mark.parametrize(
        "row",
        [
            "2025 Autumn Wollongong CSIT110 6 78 ZZ Complete",      # unknown grade
            "2025 Autumn Wollongong CSIT110 6 78 D Vibing",         # unknown status
            "2025 Trimester Wollongong CSIT110 6 78 D Complete",    # unknown session
            "2025 Autumn Wollongong CSIT110 6 78 HD",               # no status
            "2025 Autumn Wollongong CSIT110 HD Complete",           # no nominal CP
        ],
        ids=["grade", "status", "session", "no status", "no cp"],
    )
    def test_a_row_outside_the_known_shape_is_refused(self, row):
        with pytest.raises(UnreadableRecord, match="no row could be read"):
            project(row)

    def test_a_subject_name_in_the_row_is_refused_not_guessed_past(self):
        """Nothing marks where a free-text name ends, so the row is not read."""
        with pytest.raises(UnreadableRecord):
            project(ROW.replace("CSIT110 ", "CSIT110 Introduction to Computer Science ")
                    + "6 100 HD Complete")

    @pytest.mark.parametrize("code", ["C110", "CSIT11", "CSITXYZ"])
    def test_something_that_is_not_a_subject_code_is_refused(self, code):
        with pytest.raises(UnreadableRecord):
            project(f"2025 Autumn Wollongong {code} 6 78 D Complete")

    @pytest.mark.parametrize("text", ["", "   \n\t  ", "Hi, I want to plan my degree."])
    def test_nothing_resembling_a_record_is_refused(self, text):
        with pytest.raises(UnreadableRecord, match="No enrolment history"):
            project(text)

    def test_advanced_standing_is_refused_not_dropped(self):
        """Silently losing credit would understate what the student has done."""
        raw = (RECORDS[0].parent / "tafe_transfer.md").read_text()
        with pytest.raises(UnreadableRecord, match="advanced standing"):
            project(_flat(raw))

    def test_an_empty_credit_section_is_not_mistaken_for_credit(self):
        record = parse_enrolment(_flat((RECORDS[0].parent / "first_year_sem_1.md").read_text()))
        assert record.specified_credit == [] and record.unspecified_credit == []
        assert record.rows

    def test_a_paste_that_still_has_its_table_uses_the_table_parser(self):
        """The dispatcher must not send a readable table down the relaxed path."""
        with pytest.raises(UnreadableRecord, match="not a known grade"):
            project(
                "| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| 2025 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 78 | ZZ | Complete |\n"
            )

    @pytest.mark.parametrize("status", ["Completed", "Enrolledx", "Withdrawnly"])
    def test_a_status_inside_a_longer_word_is_not_read_as_that_status(self, status):
        """"Completed" must not be read as "Complete" with a stray letter dropped."""
        with pytest.raises(UnreadableRecord, match="no row could be read"):
            project(f"2025 Autumn Wollongong CSIT110 6 78 D {status}")
