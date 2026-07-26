import yaml
from pathlib import Path
from vivarium_workbench.lib.investigation_graph_views import build_investigation_graph


def _write_study(ws: Path, slug: str, spec: dict) -> None:
    d = ws / "studies" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "study.yaml").write_text(yaml.safe_dump(spec))


def _write_investigation(ws: Path, slug: str, spec: dict) -> None:
    d = ws / "investigations" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "investigation.yaml").write_text(yaml.safe_dump(spec))


def _base_ws(tmp_path: Path) -> Path:
    _write_study(tmp_path, "parca", {"name": "parca", "composite": "parca_builder",
                                     "outputs": ["sim_data"]})
    _write_study(tmp_path, "ko", {"name": "ko", "composite": "baseline",
                                  "inputs": [{"artifact": "sim_data", "from": "parca"}]})
    return tmp_path


def test_members_yield_study_nodes_and_derived_edge(tmp_path):
    ws = _base_ws(tmp_path)
    _write_investigation(ws, "invX", {"title": "X", "members": ["parca", "ko"]})
    body, status = build_investigation_graph(ws, "invX")
    assert status == 200
    assert {s["id"] for s in body["studies"]} == {"study/parca", "study/ko"}
    assert len(body["study_edges"]) == 1
    edge = body["study_edges"][0]
    assert edge["source"] == "study/parca"
    assert edge["target"] == "study/ko"
    assert edge["rel"] == "input"


def test_edge_only_when_from_is_a_member(tmp_path):
    ws = _base_ws(tmp_path)
    _write_investigation(ws, "invY", {"title": "Y", "members": ["ko"]})
    body, status = build_investigation_graph(ws, "invY")
    assert status == 200
    assert {s["id"] for s in body["studies"]} == {"study/ko"}
    assert body["study_edges"] == []


def test_member_shared_across_two_investigations(tmp_path):
    ws = _base_ws(tmp_path)
    _write_investigation(ws, "invA", {"title": "A", "members": ["parca", "ko"]})
    _write_investigation(ws, "invB", {"title": "B", "members": ["ko"]})
    body_a, status_a = build_investigation_graph(ws, "invA")
    body_b, status_b = build_investigation_graph(ws, "invB")
    assert status_a == 200 and status_b == 200
    assert "study/ko" in {s["id"] for s in body_a["studies"]}
    assert "study/ko" in {s["id"] for s in body_b["studies"]}
