from vivarium_workbench.lib.models import ReadoutRow, StudyReadouts


def test_readout_row_defaults_and_dump():
    r = ReadoutRow(store_path="listeners.mass.cell_mass", name="cell_mass",
                   annotated=True, emit_status="emitted")
    d = r.model_dump()
    assert d["store_path"] == "listeners.mass.cell_mass"
    assert d["name"] == "cell_mass"
    assert d["description"] == "" and d["units"] == "" and d["notes"] == ""
    assert d["index_by"] is None
    assert d["annotated"] is True
    assert d["emit_status"] == "emitted"


def test_readout_row_accepts_unverified_status():
    # 'unverified' is emitted on a remote build (no ParCa cache → emit plan not
    # built); the payload model must accept it or the route 500s on validation.
    r = ReadoutRow(store_path="a.b", name="b", annotated=True, emit_status="unverified")
    assert r.model_dump()["emit_status"] == "unverified"


def test_study_readouts_wraps_rows():
    sr = StudyReadouts(composite="ecoli", rows=[
        ReadoutRow(store_path="a.b", name="b", annotated=False, emit_status="emitted"),
    ])
    payload = sr.model_dump()
    assert payload["composite"] == "ecoli"
    assert payload["note"] == ""
    assert payload["rows"][0]["name"] == "b"


def test_study_readouts_carries_excluded_three_state(monkeypatch):
    """Fable Increment A #5: the excluded/excluded_state/emit_selection fields
    must survive StudyReadouts.model_validate — without them on the model, the
    FastAPI response_model silently drops build_study_readouts' new payload
    keys (pydantic's default extra='ignore') and the fix never reaches the API."""
    body = {
        "composite": "ecoli",
        "rows": [],
        "excluded": [{"store_path": "a.c", "name": "c"}],
        "excluded_state": "computed",
        "emit_selection": "subset",
    }
    sr = StudyReadouts.model_validate(body)
    payload = sr.model_dump()
    assert payload["excluded"] == [{"store_path": "a.c", "name": "c"}]
    assert payload["excluded_state"] == "computed"
    assert payload["emit_selection"] == "subset"
