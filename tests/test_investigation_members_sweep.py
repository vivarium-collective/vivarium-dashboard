"""Compatibility sweep: every reader of an investigation's member-study list
must accept both the pre-migration ``studies:`` key and the post-migration
``members:`` key (``study-registry-migration``: nested studies -> top-level
registry + investigations-as-members).

``tests/test_investigation_members_field.py`` already covers
``build_iset_summary`` (the first site fixed). This file covers:

1. The shared helper, ``investigation_members.investigation_member_slugs``.
2. A representative sample of the remaining call sites that were switched to
   use it: ``rerun._investigation_studies`` (pure extraction helper),
   ``report_views.build_iset_detail`` (iterates member studies into the
   investigation-detail payload), and ``rigor_views.build_investigation_rigor``
   (iterates member studies to build the rigor roll-up).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

from vivarium_workbench.lib.investigation_members import investigation_member_slugs
from vivarium_workbench.lib import rerun, report_views, rigor_views


# ---------------------------------------------------------------------------
# investigation_member_slugs
# ---------------------------------------------------------------------------

class TestInvestigationMemberSlugsHelper:
    def test_reads_studies_when_present(self):
        assert investigation_member_slugs({"studies": ["a", "b"]}) == ["a", "b"]

    def test_falls_back_to_members_when_studies_absent(self):
        assert investigation_member_slugs({"members": ["x", "y"]}) == ["x", "y"]

    def test_falls_back_to_members_when_studies_empty(self):
        assert investigation_member_slugs({"studies": [], "members": ["x"]}) == ["x"]

    def test_studies_wins_when_both_present(self):
        assert investigation_member_slugs({"studies": ["a"], "members": ["b"]}) == ["a"]

    def test_neither_key_present_returns_empty_list(self):
        assert investigation_member_slugs({}) == []

    def test_non_dict_spec_returns_empty_list(self):
        assert investigation_member_slugs(None) == []  # type: ignore[arg-type]
        assert investigation_member_slugs([1, 2, 3]) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# rerun._investigation_studies
# ---------------------------------------------------------------------------

class TestRerunInvestigationStudies:
    def _write_inv(self, ws: Path, slug: str, spec: dict) -> None:
        d = ws / "investigations" / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "investigation.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")

    def test_reads_members_key(self, tmp_path):
        (tmp_path / "workspace.yaml").write_text("name: t\n", encoding="utf-8")
        self._write_inv(tmp_path, "migrated", {"name": "migrated", "members": ["s1", "s2"]})
        assert rerun._investigation_studies(tmp_path, "migrated") == ["s1", "s2"]

    def test_reads_legacy_studies_key(self, tmp_path):
        (tmp_path / "workspace.yaml").write_text("name: t\n", encoding="utf-8")
        self._write_inv(tmp_path, "legacy", {"name": "legacy", "studies": ["a"]})
        assert rerun._investigation_studies(tmp_path, "legacy") == ["a"]

    def test_members_with_dict_entries(self, tmp_path):
        (tmp_path / "workspace.yaml").write_text("name: t\n", encoding="utf-8")
        self._write_inv(tmp_path, "migrated-dicts", {
            "name": "migrated-dicts",
            "members": [{"study": "s1"}, {"name": "s2"}, "s3"],
        })
        assert rerun._investigation_studies(tmp_path, "migrated-dicts") == ["s1", "s2", "s3"]


# ---------------------------------------------------------------------------
# report_views.build_iset_detail
# ---------------------------------------------------------------------------

class TestReportViewsIsetDetailMembers:
    def test_members_key_populates_studies_out(self, tmp_path):
        ws = tmp_path
        (ws / "workspace.yaml").write_text("name: t\n", encoding="utf-8")
        inv_dir = ws / "investigations" / "migrated-inv"
        inv_dir.mkdir(parents=True)
        (inv_dir / "investigation.yaml").write_text(yaml.safe_dump({
            "name": "migrated-inv",
            "title": "Migrated",
            "members": ["s1", "s2"],
        }), encoding="utf-8")

        out = report_views.build_iset_detail(ws, "migrated-inv")
        assert out is not None
        names = [s["name"] for s in out["studies"]]
        # Neither study.yaml exists on disk, so both come back "missing" —
        # what matters here is that both member slugs were iterated at all.
        assert names == ["s1", "s2"]
        assert all(s["status"] == "missing" for s in out["studies"])


# ---------------------------------------------------------------------------
# rigor_views.build_investigation_rigor
# ---------------------------------------------------------------------------

class TestRigorViewsMembers:
    def _make_workspace(self, tmp_path: Path) -> Path:
        study_dir = tmp_path / "studies" / "my-study"
        study_dir.mkdir(parents=True)
        (study_dir / "study.yaml").write_text(yaml.dump({
            "name": "my-study",
            "composite": "pbg_ws.composites.baseline",
            "runs": [],
            "simulation_set": [
                {"name": "baseline", "is_baseline": True, "status": "ready"},
            ],
        }), encoding="utf-8")

        conn = sqlite3.connect(str(study_dir / "runs.db"))
        conn.execute(
            "CREATE TABLE runs_meta (run_id TEXT, spec_id TEXT, label TEXT, "
            "params_json TEXT, started_at REAL, completed_at REAL, n_steps INTEGER, "
            "status TEXT, sim_name TEXT, generation_id TEXT)"
        )
        conn.execute(
            "INSERT INTO runs_meta VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("db-run-1", "my-study", "DB Run", "{}", 1700000000.0, 1700000010.0,
             100, "completed", "baseline", None),
        )
        conn.commit()
        conn.close()

        inv_dir = tmp_path / "investigations" / "my-inv"
        inv_dir.mkdir(parents=True)
        (inv_dir / "investigation.yaml").write_text(
            yaml.dump({
                "name": "my-inv",
                "title": "My Investigation",
                # Post-migration schema: `members:` instead of `studies:`.
                "members": ["my-study"],
            }),
            encoding="utf-8",
        )
        return tmp_path

    def test_members_key_reaches_per_study_rigor(self, tmp_path: Path) -> None:
        ws = self._make_workspace(tmp_path)
        out = rigor_views.build_investigation_rigor(ws, "my-inv")
        assert "error" not in out
        assert "my-study" in out["per_study"]
