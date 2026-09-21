from pathlib import Path

from app.agents.graphAPI import sols_codes_for_ranking, stage1_electives_from_advisor_state

raw = Path("app/test_records/_tmp_1807_record.md").read_text(encoding="utf-8")
completed, planned = sols_codes_for_ranking(raw)
print("parsed completed:", completed)
print("parsed planned:", planned)

stage1_electives_from_advisor_state(
    {
        "raw_sols": raw,
        # meta fields (this helper does not read Course/Campus/Major from the SOLS file):
        # - degree_code: which course's elective pools/rules to load ("766", "1807", ...).
        #   The paste can include **Course:** but it is NOT used here — set it in meta
        #   (missing falls back to "766", which is why 1807 must be set explicitly).
        # - campus: ranking/eligibility campus. Same as degree_code: not taken from raw.
        # - session: the TARGET session to fill (must be "Autumn" or "Spring").
        #   Row sessions in the SOLS table are history, not this field.
        # Choose elective mode here:
        # - If "major" is set, it automatically runs in major mode (interests are ignored).
        # - For interest/elective mode, set "major": None.
        # - Multiple interests: separate with commas, e.g. "art, psychology".
        "meta": {
            "degree_code": "1807",
            "campus": "Wollongong",
            "session": "Autumn",
            "major": None,
            "interests": "art, psychology"
        },
    }
)
