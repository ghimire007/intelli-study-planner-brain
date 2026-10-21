"""Unit tests for mid-chat degree switch handbook invalidation."""
from __future__ import annotations

import json

from app.agents.nodes.conversation import ConversationNodes
from app.agents.state import apply_confirm_metadata
from langchain_core.messages import HumanMessage, ToolMessage


class TestApplyConfirmMetadata:
    def test_unchanged_meta_keeps_handbook(self) -> None:
        """Re-confirming the same degree/year/campus must not clear handbook."""
        meta = {"degree_code": "766", "year": 2024, "campus": "Wollongong"}
        updates = apply_confirm_metadata(meta, meta.copy())
        assert updates["meta"] == meta
        assert updates["meta_confirmed"] is True
        assert "handbook" not in updates

    def test_degree_switch_clears_handbook(self) -> None:
        """Switching degree_code must invalidate the cached handbook."""
        prior = {"degree_code": "766", "year": 2024, "campus": "Wollongong"}
        new = {"degree_code": "1807", "year": 2024, "campus": "Wollongong"}
        updates = apply_confirm_metadata(prior, new)
        assert updates["meta"] == new
        assert updates["meta_confirmed"] is True
        assert updates["handbook"] is None

    def test_campus_change_clears_handbook(self) -> None:
        """Campus change also invalidates handbook (fetch is campus-keyed)."""
        prior = {"degree_code": "1807", "year": 2024, "campus": "Wollongong"}
        new = {"degree_code": "1807", "year": 2024, "campus": "Liverpool"}
        updates = apply_confirm_metadata(prior, new)
        assert updates["handbook"] is None

    def test_first_confirm_from_empty_prior_clears_handbook(self) -> None:
        """First confirm with no prior meta still sets handbook to None (safe no-op)."""
        new = {"degree_code": "766", "year": 2024, "campus": "Wollongong"}
        updates = apply_confirm_metadata(None, new)
        assert updates["handbook"] is None
        assert updates["meta_confirmed"] is True

    def test_major_only_change_keeps_handbook(self) -> None:
        """Updating major alone must not invalidate the degree handbook cache."""
        prior = {
            "degree_code": "1807",
            "year": 2024,
            "campus": "Wollongong",
            "major": None,
        }
        new = {
            "degree_code": "1807",
            "year": 2024,
            "campus": "Wollongong",
            "major": "Web Design and Development (MAJ40246)",
        }
        updates = apply_confirm_metadata(prior, new)
        assert updates["meta"]["major"] == new["major"]
        assert "handbook" not in updates


class TestCaptureToolResults:
    def test_degree_switch_clears_handbook(self) -> None:
        """A confirmed switch drops the old handbook; ensure_handbook reloads the new one."""
        new_meta = {"degree_code": "1807", "year": 2024, "campus": "Wollongong"}
        state = {
            "messages": [
                HumanMessage(content="Please switch me to degree 1807, 2024, Wollongong"),
                ToolMessage(
                    content=json.dumps(new_meta),
                    name="confirm_metadata_tool",
                    tool_call_id="1",
                ),
            ],
            "raw_sols": "",
            "meta": {"degree_code": "766", "year": 2024, "campus": "Wollongong"},
            "meta_confirmed": True,
            "handbook": "# old 766 handbook",
        }
        updates = ConversationNodes(None, {}).capture_tool_results(state)
        assert updates["meta"]["degree_code"] == "1807"
        assert updates["meta_confirmed"] is True
        assert updates["handbook"] is None
