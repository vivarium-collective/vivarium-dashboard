"""Golden backward-compat test: proof that `prepare_investigation` on a real
multi-study investigation with NO prerequisites and NO investigation-level
`analyses:` visits studies in exact declared order and returns empty analysis
lists — the spec's byte-identical-behavior gate.

Uses a purpose-built on-disk fixture (`tests/_fixtures/ws_exec_hook_golden`)
rather than a synthetic tmp-built one, so this is a real end-to-end read of an
`investigation.yaml` + `study.yaml` set through `WorkspacePaths` and
`investigation_member_slugs`, not just the in-process construction other
`prepare_investigation` tests use.
"""
import shutil
from pathlib import Path

import yaml

import vivarium_workbench.lib.prepare_investigation as pi
from vivarium_workbench.lib.investigation_members import investigation_member_slugs
from vivarium_workbench.lib.workspace_paths import WorkspacePaths

FIXTURE = Path(__file__).parent / "_fixtures" / "ws_exec_hook_golden"


def test_declared_order_and_no_analyses(tmp_path, monkeypatch):
    # Copy the fixture to tmp so the on-disk fixture is never mutated.
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE, ws)

    inv = "golden_inv"
    spec = yaml.safe_load(
        (WorkspacePaths.load(ws).investigations / inv / "investigation.yaml")
        .read_text(encoding="utf-8"))
    declared = investigation_member_slugs(spec)
    assert declared == ["alpha", "beta", "gamma"]  # sanity: fixture declares 3, no analyses key
    assert "analyses" not in spec

    seq: list[str] = []
    monkeypatch.setattr(
        pi, "prepare_study",
        lambda ws_, slug, *a, **k: seq.append(slug) or {"study": slug})

    result = pi.prepare_investigation(ws, investigation=inv, render_only=True)

    expected = [s if isinstance(s, str) else (s.get("study") or s.get("name"))
                for s in declared]
    assert seq == expected == ["alpha", "beta", "gamma"]

    # Investigation-level analyses phase is a true no-op with no `analyses:`
    # key, exercised through the real `run_investigation_analyses` (not
    # monkeypatched).
    assert result["analysis_files"] == []
    assert result["analysis_errors"] == []
