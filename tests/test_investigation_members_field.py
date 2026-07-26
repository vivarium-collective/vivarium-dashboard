"""Regression: investigation study lists live under `members` after the
`study-registry-migration` (nested studies -> top-level registry +
investigations-as-members). `build_iset_summary` must read the member-study
list from either `studies:` (pre-migration) or `members:` (post-migration), or
the studies sidebar/counts render 0 for every migrated investigation.
"""
from pathlib import Path

import yaml

from vivarium_workbench.lib.investigation_status import build_iset_summary


def _write_investigation(ws: Path, slug: str, spec: dict) -> None:
    d = ws / "investigations" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "investigation.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")


def test_build_iset_summary_reads_members_or_studies(tmp_path):
    (tmp_path / "workspace.yaml").write_text("name: t\n", encoding="utf-8")
    # Post-migration schema: member-study list under `members`.
    _write_investigation(tmp_path, "migrated", {"name": "migrated", "members": ["s1", "s2", "s3"]})
    # Pre-migration schema: still under `studies`.
    _write_investigation(tmp_path, "legacy", {"name": "legacy", "studies": ["a", "b"]})

    rows = build_iset_summary(tmp_path, study_has_runs=lambda *a, **k: False)
    by_name = {r.get("name"): r for r in rows}

    assert by_name["migrated"]["n_studies"] == 3
    assert by_name["migrated"]["studies"] == ["s1", "s2", "s3"]
    assert by_name["legacy"]["n_studies"] == 2
    assert by_name["legacy"]["studies"] == ["a", "b"]


def test_studies_wins_when_both_present(tmp_path):
    # `members` is only a fallback: a spec that (transitionally) has both keeps
    # `studies` as the authoritative list.
    (tmp_path / "workspace.yaml").write_text("name: t\n", encoding="utf-8")
    _write_investigation(tmp_path, "both", {"name": "both", "studies": ["x"], "members": ["y", "z"]})

    rows = build_iset_summary(tmp_path, study_has_runs=lambda *a, **k: False)
    both = next(r for r in rows if r.get("name") == "both")
    assert both["studies"] == ["x"]
