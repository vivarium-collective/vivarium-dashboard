"""Unit tests for lib.module_stats.module_content_stats.

Uses the shared ws_federation_demo fixture (a linked "donor-repo" module with
1 composite + 1 study + 1 investigation) for the content-count assertions,
and a TEMP workspace (tmp_path) — never mutating the shared fixture — for the
n_used assertion, since that requires adding an own study that references
one of the module's items.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from vivarium_workbench.lib.module_stats import module_content_stats

FIX = Path(__file__).parent / "_fixtures" / "ws_federation_demo"


def test_module_content_stats_counts_donor_repo_content():
    stats = module_content_stats(FIX)
    assert "donor-repo" in stats
    rec = stats["donor-repo"]
    assert rec["n_composites"] == 1
    assert rec["n_studies"] == 1
    assert rec["n_investigations"] == 1
    # host_ws (the fixture's own workspace) has no own studies referencing
    # donor-repo content, so nothing is "used" yet.
    assert rec["n_used"] == 0


def test_module_content_stats_never_raises_with_no_external_dir(tmp_path):
    (tmp_path / "workspace.yaml").write_text("name: solo\n")
    assert module_content_stats(tmp_path) == {}


def test_module_content_stats_n_used_counts_own_study_reference(tmp_path):
    # Build a fresh host workspace (do NOT mutate the shared FIX fixture):
    # link the same donor-repo module, then add an own study whose baseline
    # composite references one of the module's composites.
    (tmp_path / "workspace.yaml").write_text("name: host2\n")
    ext = tmp_path / "external"
    ext.mkdir()
    shutil.copytree(FIX / "external" / "donor", ext / "donor")

    studies = tmp_path / "studies" / "my_study"
    studies.mkdir(parents=True)
    (studies / "study.yaml").write_text(
        "name: my_study\n"
        "description: References the donor module's composite.\n"
        "baseline:\n"
        "  - {name: base, composite: donor.composites.donor}\n"
    )

    stats = module_content_stats(tmp_path)
    assert "donor-repo" in stats
    rec = stats["donor-repo"]
    assert rec["n_composites"] == 1
    assert rec["n_studies"] == 1
    assert rec["n_investigations"] == 1
    assert rec["n_used"] == 1

    # The shared fixture must be untouched.
    assert not (FIX / "studies").exists()
