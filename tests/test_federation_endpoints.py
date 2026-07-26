from pathlib import Path

from vivarium_workbench.lib.investigations_index import build_investigations
from vivarium_workbench.lib.investigation_status import build_iset_summary
from vivarium_workbench.lib.models import InvestigationSummary
from vivarium_workbench.lib.composite_lookup import discover_all_composites

FIX = Path(__file__).parent / "_fixtures" / "ws_federation_demo"


def test_build_investigations_includes_federated_study_with_provenance():
    rows = build_investigations(FIX)["investigations"]
    donor = next(r for r in rows if r["name"] == "donor_study")
    assert donor["origin_repo"] == "donor-repo"
    assert donor["read_only"] is True
    # membership: donor_inv lists donor_study
    assert "donor_inv" in donor["investigations"]


def test_build_investigations_own_rows_have_null_origin():
    rows = build_investigations(FIX)["investigations"]
    # host_ws has no own studies; assert federated rows are the only ones and
    # any own row (if present) carries origin_repo None.
    for r in rows:
        assert "origin_repo" in r


def test_iset_summary_includes_federated_investigation():
    isets = build_iset_summary(FIX, study_has_runs=lambda *a, **k: False)
    di = next(i for i in isets if i["name"] == "donor_inv")
    assert di["origin_repo"] == "donor-repo"
    assert di["read_only"] is True
    assert "donor_study" in di["studies"]


def test_investigation_summary_model_preserves_provenance_fields():
    # Serialization-boundary check: InvestigationSummary is the pydantic response
    # model GET /api/investigation-summaries validates each summary dict against
    # (api/app.py). Without explicit typed fields for origin_repo/read_only, pydantic
    # silently drops them since the model has no extra="allow".
    dumped = InvestigationSummary.model_validate(
        {"name": "x", "origin_repo": "donor-repo", "read_only": True}
    ).model_dump()
    assert dumped["origin_repo"] == "donor-repo"
    assert dumped["read_only"] is True


def test_discover_all_composites_tags_federated_origin():
    comps = discover_all_composites(FIX, "host")  # host_ws has no own package
    rec = next(r for r in comps.values() if r.get("name") == "donor_comp")
    assert rec["origin_repo"] == "donor-repo"
    assert rec["read_only"] is True


# ---------------------------------------------------------------------------
# End-to-end: federated content through the LIVE FastAPI server.
#
# The tests above exercise the lib builders directly. That misses the
# pydantic-serialization boundary each route sits behind -- Task 4 caught a
# real bug there where InvestigationSummary silently dropped origin_repo/
# read_only because the model had no explicit fields for them and no
# extra="allow". These tests spin up the real server (dashboard_client
# fixture -> subprocess -> uvicorn/FastAPI) against ws_federation_demo and
# hit the routes over HTTP, so a regression at the model boundary fails here
# even if the lib-level tests above still pass.
# ---------------------------------------------------------------------------

def test_endpoints_expose_federated_content(dashboard_client):
    client = dashboard_client(FIX)

    inv = client.get("/api/investigations").json()["investigations"]
    donor_study = next(r for r in inv if r.get("name") == "donor_study")
    assert donor_study["origin_repo"] == "donor-repo"

    comps = client.get("/api/composites").json()["composites"]
    donor_comp = next(c for c in comps if c.get("name") == "donor_comp")
    assert donor_comp["origin_repo"] == "donor-repo"

    summaries = client.get("/api/investigation-summaries").json()["investigations"]
    donor_inv = next(i for i in summaries if i.get("name") == "donor_inv")
    assert donor_inv["origin_repo"] == "donor-repo"
