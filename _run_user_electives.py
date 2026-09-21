from pathlib import Path

from app.agents.graphAPI import sols_codes_for_ranking, stage1_electives_from_advisor_state

raw = Path("app/test_records/_tmp_user_paste.md").read_text(encoding="utf-8")
completed, planned = sols_codes_for_ranking(raw)
print("parsed completed:", completed)
print("parsed planned:", planned)

stage1_electives_from_advisor_state(
    {
        "raw_sols": raw,
        "meta": {
            "degree_code": "1807",
            "campus": "Wollongong",
            "session": "Autumn",
            "major": None,
        },
    }
)
