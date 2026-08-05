"""Tests for vivarium_workbench.lib.study_findings (Pass 10A findings walk)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vivarium_workbench.lib import expert_search, study_findings as sf


@pytest.fixture(autouse=True)
def _clear_expert_cache():
    expert_search.clear_cache()
    yield
    expert_search.clear_cache()


def _make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "name": "test-ws",
                "created": "2026-05-17",
                "plugin_version": "0.9.0",
                "package_path": "pkg",
                "expert_docs": [],
            },
            sort_keys=False,
        )
    )
    return ws


def _make_study(
    ws: Path,
    slug: str,
    *,
    behavior_tests: list[dict] | None = None,
    runs: list[dict] | None = None,
    findings: list[dict] | None = None,
) -> Path:
    sd = ws / "studies" / slug
    sd.mkdir(parents=True)
    spec = {
        "name": slug,
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
    }
    if behavior_tests is not None:
        spec["behavior_tests"] = behavior_tests
    if runs is not None:
        spec["runs"] = runs
    if findings is not None:
        spec["findings"] = findings
    (sd / "study.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    return sd


# ---------------------------------------------------------------------------
# Outcome extraction
# ---------------------------------------------------------------------------


def test_extract_outcomes_handles_dict_form(tmp_path):
    ws = _make_workspace(tmp_path)
    _make_study(
        ws,
        "s1",
        behavior_tests=[{"name": "test-a"}],
        runs=[{"name": "run-1", "outcomes": {"test-a": {"result": "pass", "observed": 42}}}],
    )
    study = yaml.safe_load((ws / "studies/s1/study.yaml").read_text())
    rows = sf.extract_outcomes(study)
    assert len(rows) == 1
    r = rows[0]
    assert r.test_name == "test-a"
    assert r.run_name == "run-1"
    assert r.result == "pass"
    assert r.observed == 42


def test_extract_outcomes_handles_list_form(tmp_path):
    ws = _make_workspace(tmp_path)
    _make_study(
        ws,
        "s1",
        runs=[
            {
                "name": "run-1",
                "outcomes": [
                    {"behavior_test": "test-a", "result": "pass", "observed": 1},
                    {"behavior_test": "test-b", "result": "fail", "observed": "0.5"},
                ],
            }
        ],
    )
    study = yaml.safe_load((ws / "studies/s1/study.yaml").read_text())
    rows = sf.extract_outcomes(study)
    names = sorted(r.test_name for r in rows)
    assert names == ["test-a", "test-b"]


def test_extract_outcomes_handles_test_results_form(tmp_path):
    ws = _make_workspace(tmp_path)
    _make_study(
        ws,
        "s1",
        runs=[{"name": "run-1", "test_results": {"test-a": "pass", "test-b": "fail"}}],
    )
    study = yaml.safe_load((ws / "studies/s1/study.yaml").read_text())
    rows = sf.extract_outcomes(study)
    assert {r.test_name: r.result for r in rows} == {"test-a": "pass", "test-b": "fail"}


# ---------------------------------------------------------------------------
# Heuristic drafts
# ---------------------------------------------------------------------------


def test_pass_outcome_drafts_biological_confirms():
    row = sf.OutcomeRow(
        run_name="run-1",
        test_name="dnaA-count-in-range",
        result="pass",
        observed=500,
        description="DnaA count within literature band",
    )
    draft = sf.draft_for_outcome(row)
    assert draft.kind == "biological"
    assert draft.status == "confirms"
    assert "dnaA-count-in-range" in draft.statement
    assert draft.evidence["from_test"] == "dnaA-count-in-range"
    assert draft.evidence["observed"] == 500


def test_fail_outcome_drafts_biological_contradicts_by_default():
    row = sf.OutcomeRow(
        run_name="run-1",
        test_name="dnaA-count-in-range",
        result="fail",
        observed=115,
    )
    draft = sf.draft_for_outcome(row)
    assert draft.kind == "biological"
    assert draft.status == "contradicts"
    assert draft.next_action  # gate is held


def test_fail_outcome_with_computational_hint_drafts_novel():
    row = sf.OutcomeRow(
        run_name="run-1",
        test_name="listener-shape",
        result="fail",
    )
    draft = sf.draft_for_outcome(row, fail_kind_hint="computational")
    assert draft.kind == "computational"
    assert draft.status == "novel"


# ---------------------------------------------------------------------------
# ID auto-allocation
# ---------------------------------------------------------------------------


def test_next_finding_id_starts_at_F_01_for_empty_study():
    assert sf.next_finding_id({}) == "F-01"
    assert sf.next_finding_id({"findings": []}) == "F-01"


def test_next_finding_id_skips_used():
    study = {"findings": [{"id": "F-01"}, {"id": "F-03"}, {"id": "F-99"}]}
    # next free index = 2
    assert sf.next_finding_id(study) == "F-02"


def test_existing_finding_tests_collects_from_test():
    study = {
        "findings": [
            {"id": "F-01", "evidence": {"from_test": "test-a"}},
            {"id": "F-02"},  # no evidence
            {"id": "F-03", "evidence": {"from_test": "test-b"}},
        ]
    }
    assert sf.existing_finding_tests(study) == {"test-a", "test-b"}


# ---------------------------------------------------------------------------
# Bib-key load + cite collection
# ---------------------------------------------------------------------------


def test_load_bib_keys_parses_papers_bib(tmp_path):
    ws = _make_workspace(tmp_path)
    (ws / "references").mkdir()
    (ws / "references" / "papers.bib").write_text(
        """
        @article{Smith2020,
          title = {Foo},
        }
        @book{Jones2019,
          title = {Bar},
        }
        % comment line
        """.strip()
    )
    assert sf.load_bib_keys(ws) == {"Smith2020", "Jones2019"}


def test_load_bib_keys_missing_file_returns_empty(tmp_path):
    ws = _make_workspace(tmp_path)
    assert sf.load_bib_keys(ws) == set()


# ---------------------------------------------------------------------------
# End-to-end walk
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write(tmp_path, capsys):
    ws = _make_workspace(tmp_path)
    sd = _make_study(
        ws,
        "s1",
        behavior_tests=[{"name": "test-a", "description": "Some bio test"}],
        runs=[{"name": "run-1", "outcomes": [{"behavior_test": "test-a", "result": "pass"}]}],
    )
    before = (sd / "study.yaml").read_text()
    res = sf.run_findings_walk(sd, dry_run=True)
    after = (sd / "study.yaml").read_text()
    assert before == after, "dry_run must not modify study.yaml"
    assert res.dry_run is True
    assert len(res.proposed) == 1


def test_auto_writes_drafts(tmp_path):
    ws = _make_workspace(tmp_path)
    sd = _make_study(
        ws,
        "s1",
        behavior_tests=[
            {"name": "test-a", "description": "Some bio test"},
            {"name": "test-b", "description": "Another"},
        ],
        runs=[
            {
                "name": "run-1",
                "outcomes": [
                    {"behavior_test": "test-a", "result": "pass"},
                    {"behavior_test": "test-b", "result": "fail"},
                ],
            }
        ],
    )
    res = sf.run_findings_walk(sd, auto=True)
    assert res.wrote_path == sd / "study.yaml"
    assert len(res.appended) == 2

    study = yaml.safe_load((sd / "study.yaml").read_text())
    findings = study["findings"]
    assert len(findings) == 2
    by_test = {f["evidence"]["from_test"]: f for f in findings}
    assert by_test["test-a"]["status"] == "confirms"
    assert by_test["test-b"]["status"] == "contradicts"
    # IDs allocated cleanly:
    ids = sorted(f["id"] for f in findings)
    assert ids == ["F-01", "F-02"]


def test_walk_skips_outcomes_already_covered_by_existing_findings(tmp_path):
    ws = _make_workspace(tmp_path)
    sd = _make_study(
        ws,
        "s1",
        behavior_tests=[{"name": "test-a"}, {"name": "test-b"}],
        runs=[
            {
                "name": "run-1",
                "outcomes": [
                    {"behavior_test": "test-a", "result": "pass"},
                    {"behavior_test": "test-b", "result": "pass"},
                ],
            }
        ],
        findings=[
            {
                "id": "F-01",
                "kind": "biological",
                "status": "confirms",
                "statement": "Already covered.",
                "evidence": {"from_test": "test-a"},
            }
        ],
    )
    res = sf.run_findings_walk(sd, auto=True)
    assert "test-a" in res.skipped_existing
    appended_tests = [f.evidence["from_test"] for f in res.appended]
    assert appended_tests == ["test-b"]


def test_walk_assigns_ids_after_existing(tmp_path):
    ws = _make_workspace(tmp_path)
    sd = _make_study(
        ws,
        "s1",
        behavior_tests=[{"name": "test-b"}],
        runs=[
            {
                "name": "run-1",
                "outcomes": [{"behavior_test": "test-b", "result": "pass"}],
            }
        ],
        findings=[
            {
                "id": "F-01",
                "kind": "biological",
                "status": "confirms",
                "statement": "Existing.",
                "evidence": {"from_test": "test-other"},
            },
            {
                "id": "F-03",
                "kind": "biological",
                "status": "confirms",
                "statement": "Skip F-02.",
                "evidence": {"from_test": "test-other-2"},
            },
        ],
    )
    res = sf.run_findings_walk(sd, auto=True)
    assert len(res.appended) == 1
    assert res.appended[0].id == "F-02"


def test_walk_prompter_can_skip_or_modify(tmp_path):
    ws = _make_workspace(tmp_path)
    sd = _make_study(
        ws,
        "s1",
        behavior_tests=[{"name": "test-a"}, {"name": "test-b"}],
        runs=[
            {
                "name": "run-1",
                "outcomes": [
                    {"behavior_test": "test-a", "result": "pass"},
                    {"behavior_test": "test-b", "result": "pass"},
                ],
            }
        ],
    )

    def prompter(draft, outcome):
        if outcome.test_name == "test-a":
            return None  # skip
        draft.statement = "Curator-rewritten statement."
        return draft

    res = sf.run_findings_walk(sd, prompter=prompter)
    assert len(res.appended) == 1
    assert res.appended[0].statement == "Curator-rewritten statement."

    study = yaml.safe_load((sd / "study.yaml").read_text())
    assert len(study["findings"]) == 1


def test_walk_atomic_write_leaves_no_tmp(tmp_path):
    ws = _make_workspace(tmp_path)
    sd = _make_study(
        ws,
        "s1",
        behavior_tests=[{"name": "test-a"}],
        runs=[{"name": "run-1", "outcomes": [{"behavior_test": "test-a", "result": "pass"}]}],
    )
    sf.run_findings_walk(sd, auto=True)
    leftover = list(sd.glob("study.yaml.*"))
    assert not leftover, f"unexpected tmp files: {leftover}"


def test_walk_warns_on_unknown_bib_key(tmp_path, capsys):
    ws = _make_workspace(tmp_path)
    (ws / "references").mkdir()
    (ws / "references" / "papers.bib").write_text("@article{KnownKey, title={x}}\n")
    sd = _make_study(
        ws,
        "s1",
        behavior_tests=[{"name": "test-a"}],
        runs=[{"name": "run-1", "outcomes": [{"behavior_test": "test-a", "result": "pass"}]}],
    )

    captured: list[str] = []
    out = lambda s: captured.append(s)

    def prompter(draft, outcome):
        draft.expected["cites"] = ["UnknownKey", "KnownKey"]
        return draft

    res = sf.run_findings_walk(sd, prompter=prompter, out=out)
    assert "UnknownKey" in res.unknown_bib_keys
    assert "KnownKey" not in res.unknown_bib_keys
    assert any("UnknownKey" in line for line in captured)


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_dry_run_exits_zero(tmp_path, capsys, monkeypatch):
    ws = _make_workspace(tmp_path)
    _make_study(
        ws,
        "s1",
        behavior_tests=[{"name": "test-a"}],
        runs=[{"name": "run-1", "outcomes": [{"behavior_test": "test-a", "result": "pass"}]}],
    )
    monkeypatch.chdir(ws)
    rc = sf.main(["s1", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "summary" in out


def test_cli_missing_workspace_returns_2(tmp_path, capsys):
    rc = sf.main(["s1", "--ws", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "ERROR" in err
