# tests/test_analysis_tools.py
from vivarium_workbench.lib import analysis_tools as at

def test_match_requires_subset():
    cands = [
        {"ref": "r1", "capabilities": ["observables", "fluxes"]},
        {"ref": "r2", "capabilities": ["observables"]},
        {"ref": "r3", "capabilities": []},
    ]
    got = at.match(["observables"], cands)
    assert {m["ref"] for m in got} == {"r1", "r2"}
    got2 = at.match(["fluxes"], cands)
    assert {m["ref"] for m in got2} == {"r1"}

def test_builtin_tools_declare_requires():
    ids = {t["id"]: t for t in at.builtin_tools()}
    assert ids["data-explorer"]["requires"] == ["observables"]
    assert ids["parsimony-viewer"]["requires"] == ["3d_pack"]

def test_build_composes_external_and_builtin(monkeypatch):
    monkeypatch.setattr(at, "viewers_public",
        lambda ws: [{"id": "omics", "title": "Omics", "requires": [],
                     "targets": [{"study": "s1", "label": "s1"}]}])
    monkeypatch.setattr(at, "_run_candidates",
        lambda ws: [{"ref": "run1", "label": "run1", "capabilities": ["observables"]}])
    monkeypatch.setattr(at, "_pack_candidates",
        lambda ws: [{"ref": "ecoli-3d", "label": "ecoli-3d", "capabilities": ["3d_pack"]}])
    tools = {t["id"]: t for t in at.build_analysis_tools("/ws")}
    # external tool with no requires keeps its targets verbatim
    assert tools["omics"]["matched"] == [] and tools["omics"]["targets"]
    # data explorer matched the observables run
    assert {m["ref"] for m in tools["data-explorer"]["matched"]} == {"run1"}
    # parsimony matched the 3d_pack study
    assert {m["ref"] for m in tools["parsimony-viewer"]["matched"]} == {"ecoli-3d"}
