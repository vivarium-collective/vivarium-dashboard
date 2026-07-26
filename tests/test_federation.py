from pathlib import Path

from vivarium_workbench.lib.federation import linked_workspaces

FIX = Path(__file__).parent / "_fixtures" / "ws_federation_demo"


def test_linked_workspaces_finds_donor_and_skips_broken():
    links = linked_workspaces(FIX)
    repos = {lw.repo for lw in links}
    assert "donor-repo" in repos          # name from workspace.yaml
    assert all(lw.root.name != "host_ws" for lw in links)  # excludes self
    # broken external dir must not raise and must not appear
    assert "broken" not in {lw.root.name for lw in links}


def test_linked_workspaces_empty_when_no_external(tmp_path):
    (tmp_path / "workspace.yaml").write_text("name: solo\n")
    assert linked_workspaces(tmp_path) == []
