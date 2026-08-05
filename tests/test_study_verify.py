"""Tests for ``/viva-study verify`` spec verification.

Pins the workspace-agnostic checks in :mod:`vivarium_workbench.lib.study_verify`:

  - baseline shape & required fields
  - variants reference real baselines
  - simulation_set / behavior_tests cross-references
  - parent_studies resolve in the workspace
  - cite keys resolve in references.bib (soft-skipped if no bib file)
  - findings.evidence.from_test / followup_proposals.linked_finding
    resolve to real ids
  - CLI exit codes (0 = clean, 1 = errors, 1 with --strict on warnings)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from vivarium_workbench.lib import study_verify as sv


def _write_yaml(p: Path, data: dict) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


def _make_workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace with workspace.yaml + a bib file."""
    (tmp_path / "workspace.yaml").write_text("name: test-ws\n")
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "references.bib").write_text(
        "@article{boesen2024, title={DnaA-ATP regulation}, year={2024}}\n"
        "@book{kornberg1992, title={DNA Replication}, year={1992}}\n"
    )
    return tmp_path


def _make_clean_study(ws: Path, slug: str = "dnaa-01") -> Path:
    spec = {
        "name": slug,
        "phase": "Design",
        "baseline": [{"name": "wt", "composite": "pkg.composites.wt"}],
        "variants": [
            {"name": "TE-10x", "base_composite": "wt", "params": {"k": 10}},
        ],
        "simulation_set": [
            {"name": "main", "from": "wt"},
        ],
        "observables": [
            {"name": "DnaA_count", "store_path": "bulk.DnaA"},
        ],
        "behavior_tests": [
            {
                "name": "dnaA-in-range",
                "classification": "primary",
                "requires_simulation": "main",
                "measure": {"kind": "scalar", "observable": "DnaA_count"},
                "pass_if": {"op": "between", "lo": 300, "hi": 800},
                "cites": ["boesen2024"],
            },
        ],
        "findings": [
            {
                "id": "F-01",
                "kind": "biological",
                "status": "confirms",
                "statement": "ok",
                "evidence": {"from_test": "dnaA-in-range"},
                "cites": ["kornberg1992"],
            },
        ],
        "followup_proposals": [
            {
                "id": "f-up",
                "title": "follow up",
                "motivation": "next",
                "linked_finding": "F-01",
            },
        ],
    }
    return _write_yaml(ws / "studies" / slug / "study.yaml", spec)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_clean_study_has_no_findings(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    findings = sv.verify_study(sy)
    assert findings == [], (
        "expected no findings on a clean study but got: "
        + "\n".join(f.message for f in findings)
    )


# ---------------------------------------------------------------------------
# Baseline checks
# ---------------------------------------------------------------------------


def test_missing_baseline_errors(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    del spec["baseline"]
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert any(f.check == "baseline-missing" for f in findings)
    assert all(f.level == "error" for f in findings if f.check.startswith("baseline-"))


def test_baseline_entry_missing_name_errors(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["baseline"] = [{"composite": "pkg.composites.x"}]
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert any(f.check == "baseline-name" for f in findings)


def test_baseline_entry_missing_composite_errors(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["baseline"] = [{"name": "wt"}]
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert any(f.check == "baseline-composite" for f in findings)


def test_baseline_accepts_legacy_dict_shape(tmp_path):
    """A single baseline as a dict (not list) is the legacy v2 shape; still valid."""
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["baseline"] = {"name": "wt", "composite": "pkg.composites.wt"}
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert not any(f.check.startswith("baseline-") for f in findings)


# ---------------------------------------------------------------------------
# Variant + simulation_set
# ---------------------------------------------------------------------------


def test_variant_with_unknown_base_errors(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["variants"][0]["base_composite"] = "ghost"
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert any(f.check == "variant-base-unknown" for f in findings)


def test_simulation_set_with_unknown_from_warns(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["simulation_set"][0]["from"] = "ghost"
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    matched = [f for f in findings if f.check == "simulation-from-unknown"]
    assert matched
    assert all(f.level == "warning" for f in matched)


# ---------------------------------------------------------------------------
# behavior_tests
# ---------------------------------------------------------------------------


def test_behavior_test_with_unknown_simulation_errors(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["behavior_tests"][0]["requires_simulation"] = "ghost-sim"
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert any(f.check == "behavior-test-requires-sim" for f in findings)


def test_behavior_test_with_unknown_observable_errors(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["behavior_tests"][0]["measure"]["observable"] = "ghost-obs"
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert any(f.check == "behavior-test-observable" for f in findings)


def test_behavior_test_observable_check_skipped_without_observables_block(tmp_path):
    """If no observables[] is declared, we can't validate measure.observable
    refs — they may be inlined paths. The check must be soft-skipped."""
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    del spec["observables"]
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert not any(f.check == "behavior-test-observable" for f in findings)


def test_behavior_test_can_reference_variant_name(tmp_path):
    """A behavior_test.requires_simulation referencing a variant by name is valid."""
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["behavior_tests"][0]["requires_simulation"] = "TE-10x"
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert not any(f.check == "behavior-test-requires-sim" for f in findings)


# ---------------------------------------------------------------------------
# parent_studies
# ---------------------------------------------------------------------------


def test_parent_study_not_in_workspace_errors(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["parent_studies"] = ["ghost-parent"]
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert any(f.check == "parent-study-not-found" for f in findings)


def test_parent_study_resolves_when_sibling_exists(tmp_path):
    ws = _make_workspace(tmp_path)
    _make_clean_study(ws, slug="dnaa-00-prereq")
    sy = _make_clean_study(ws, slug="dnaa-01")
    spec = yaml.safe_load(sy.read_text())
    spec["parent_studies"] = ["dnaa-00-prereq"]
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert not any(f.check.startswith("parent-study-") for f in findings)


def test_parent_study_object_shape_resolves(tmp_path):
    """parent_studies accepts {study, condition} dicts; the slug still resolves."""
    ws = _make_workspace(tmp_path)
    _make_clean_study(ws, slug="dnaa-00-prereq")
    sy = _make_clean_study(ws, slug="dnaa-01")
    spec = yaml.safe_load(sy.read_text())
    spec["parent_studies"] = [{"study": "dnaa-00-prereq", "condition": "tests-passed"}]
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert not any(f.check.startswith("parent-study-") for f in findings)


# ---------------------------------------------------------------------------
# cites
# ---------------------------------------------------------------------------


def test_unknown_cite_key_warns(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["behavior_tests"][0]["cites"] = ["ghost-paper"]
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    matched = [f for f in findings if f.check == "cite-key-not-in-bib"]
    assert matched
    assert matched[0].level == "warning"


def test_cite_check_skipped_when_no_bib_file(tmp_path):
    """When references.bib doesn't exist, cite checks are soft-skipped."""
    (tmp_path / "workspace.yaml").write_text("name: test-ws\n")
    sy = _make_clean_study(tmp_path)
    spec = yaml.safe_load(sy.read_text())
    spec["behavior_tests"][0]["cites"] = ["any-key-at-all"]
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    assert not any(f.check == "cite-key-not-in-bib" for f in findings)


# ---------------------------------------------------------------------------
# findings.evidence + followup_proposals.linked_finding
# ---------------------------------------------------------------------------


def test_finding_from_test_unknown_warns(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["findings"][0]["evidence"]["from_test"] = "ghost-test"
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    matched = [f for f in findings if f.check == "finding-from-test-unknown"]
    assert matched
    assert matched[0].level == "warning"


def test_proposal_linked_finding_unknown_errors(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["followup_proposals"][0]["linked_finding"] = "F-99"
    sy.write_text(yaml.safe_dump(spec))
    findings = sv.verify_study(sy)
    matched = [f for f in findings if f.check == "proposal-linked-finding-unknown"]
    assert matched
    assert matched[0].level == "error"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_clean_study_exits_zero(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    cp = subprocess.run(
        [sys.executable, "-m", "vivarium_workbench.lib.study_verify", str(sy)],
        capture_output=True, text=True,
    )
    assert cp.returncode == 0, cp.stderr
    assert "OK" in cp.stdout


def test_cli_error_study_exits_one(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["behavior_tests"][0]["requires_simulation"] = "ghost"
    sy.write_text(yaml.safe_dump(spec))
    cp = subprocess.run(
        [sys.executable, "-m", "vivarium_workbench.lib.study_verify", str(sy)],
        capture_output=True, text=True,
    )
    assert cp.returncode == 1
    assert "behavior-test-requires-sim" in cp.stdout


def test_cli_strict_promotes_warnings_to_failure(tmp_path):
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["behavior_tests"][0]["cites"] = ["ghost"]  # warning, not error
    sy.write_text(yaml.safe_dump(spec))
    cp_default = subprocess.run(
        [sys.executable, "-m", "vivarium_workbench.lib.study_verify", str(sy)],
        capture_output=True, text=True,
    )
    assert cp_default.returncode == 0  # warnings don't fail by default
    cp_strict = subprocess.run(
        [sys.executable, "-m", "vivarium_workbench.lib.study_verify", str(sy), "--strict"],
        capture_output=True, text=True,
    )
    assert cp_strict.returncode == 1


def test_cli_json_output_is_machine_readable(tmp_path):
    import json
    ws = _make_workspace(tmp_path)
    sy = _make_clean_study(ws)
    spec = yaml.safe_load(sy.read_text())
    spec["behavior_tests"][0]["requires_simulation"] = "ghost"
    sy.write_text(yaml.safe_dump(spec))
    cp = subprocess.run(
        [sys.executable, "-m", "vivarium_workbench.lib.study_verify", str(sy),
         "--json"],
        capture_output=True, text=True,
    )
    payload = json.loads(cp.stdout)
    assert payload["summary"]["error"] >= 1
    assert any(
        f["check"] == "behavior-test-requires-sim"
        for f in payload["findings"]
    )


def test_cli_missing_file_exits_two(tmp_path):
    cp = subprocess.run(
        [sys.executable, "-m", "vivarium_workbench.lib.study_verify",
         str(tmp_path / "nonexistent.yaml")],
        capture_output=True, text=True,
    )
    assert cp.returncode == 2
    assert "nonexistent.yaml" in cp.stderr
