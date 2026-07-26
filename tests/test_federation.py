from pathlib import Path

from vivarium_workbench.lib.federation import (
    linked_workspaces,
    federated_studies,
    federated_investigation_sets,
    federated_composites,
)

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


def test_federated_studies_tagged_and_namespaced():
    studies = federated_studies(FIX)
    ds = next(s for s in studies if s["name"] == "donor_study")
    assert ds["origin_repo"] == "donor-repo"
    assert ds["read_only"] is True
    assert ds["id"] == "donor-repo::donor_study"


def test_federated_investigation_sets_member_studies_namespaced():
    isets = federated_investigation_sets(FIX)
    di = next(i for i in isets if i["name"] == "donor_inv")
    assert di["origin_repo"] == "donor-repo"
    assert di["id"] == "donor-repo::donor_inv"
    assert di["member_studies"] == ["donor-repo::donor_study"]


def test_federated_composites_tagged():
    comps = federated_composites(FIX)
    rec = next(r for r in comps.values() if r.get("name") == "donor_comp")
    assert rec["origin_repo"] == "donor-repo"
    assert rec["read_only"] is True
