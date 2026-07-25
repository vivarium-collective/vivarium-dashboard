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

def test_run_candidates_reads_simulations_key(monkeypatch):
    monkeypatch.setattr(at, "build_simulations_data", lambda ws: {
        "simulations": [
            {"run_id": "r1", "label": "run one", "emitter_type": "XArray",
             "capabilities": ["observables", "fluxes"]},
            {"run_id": "r2", "label": "run two", "emitter_type": "SQLite",
             "capabilities": []},
        ],
        "current": None,
    })
    cands = at._run_candidates("/ws")
    assert {c["ref"] for c in cands} == {"r1", "r2"}
    assert {c["ref"] for c in cands if "observables" in c["capabilities"]} == {"r1"}

def test_data_explorer_matches_observables_run_end_to_end(monkeypatch):
    monkeypatch.setattr(at, "viewers_public", lambda ws: [])
    monkeypatch.setattr(at, "build_simulations_data", lambda ws: {
        "simulations": [{"run_id": "r1", "label": "run one",
                         "emitter_type": "XArray", "capabilities": ["observables"]}],
        "current": None})
    monkeypatch.setattr(at, "_pack_candidates", lambda ws: [])
    tools = {t["id"]: t for t in at.build_analysis_tools("/ws")}
    assert {m["ref"] for m in tools["data-explorer"]["matched"]} == {"r1"}


def test_contributed_3d_duplicate_dropped_in_favor_of_native(monkeypatch):
    # A contributed viewer whose targets are ALL 3D-pack studies duplicates the
    # native Parsimony Viewer (which always resolves a working viewer). Drop the
    # contributed one; keep the built-in — exactly one, always-working 3D card.
    monkeypatch.setattr(at, "viewers_public", lambda ws: [
        {"id": "ecoli-3d", "title": "3D E. coli viewer", "requires": [],
         "targets": [{"study": "ecoli-3d", "label": "ecoli-3d",
                      "detail": "1,302,935 molecules placed"}]},
    ])
    monkeypatch.setattr(at, "_run_candidates", lambda ws: [])
    monkeypatch.setattr(at, "_pack_candidates",
        lambda ws: [{"ref": "ecoli-3d", "label": "ecoli-3d", "capabilities": ["3d_pack"]}])
    ids = [t["id"] for t in at.build_analysis_tools("/ws")]
    assert "ecoli-3d" not in ids          # contributed duplicate dropped
    assert "parsimony-viewer" in ids      # native viewer kept


def test_non_3d_contributed_viewer_not_dropped(monkeypatch):
    # A contributed viewer targeting a NON-pack study (e.g. Omics) is not a 3D
    # duplicate and must survive.
    monkeypatch.setattr(at, "viewers_public", lambda ws: [
        {"id": "pathway-tools", "title": "Omics", "requires": [],
         "targets": [{"study": "showcase", "label": "showcase"}]},
    ])
    monkeypatch.setattr(at, "_run_candidates", lambda ws: [])
    monkeypatch.setattr(at, "_pack_candidates",
        lambda ws: [{"ref": "ecoli-3d", "label": "ecoli-3d", "capabilities": ["3d_pack"]}])
    ids = [t["id"] for t in at.build_analysis_tools("/ws")]
    assert "pathway-tools" in ids         # non-3D viewer kept
    assert "parsimony-viewer" in ids      # native 3D viewer also present


def test_parsimony_viewer_kept_when_no_contributed_3d_viewer(monkeypatch):
    # With packs but no contributed viewer covering them, the built-in Parsimony
    # Viewer is the native fallback and IS shown.
    monkeypatch.setattr(at, "viewers_public", lambda ws: [])
    monkeypatch.setattr(at, "_run_candidates", lambda ws: [])
    monkeypatch.setattr(at, "_pack_candidates",
        lambda ws: [{"ref": "ecoli-3d", "label": "ecoli-3d", "capabilities": ["3d_pack"]}])
    tools = {t["id"]: t for t in at.build_analysis_tools("/ws")}
    assert {m["ref"] for m in tools["parsimony-viewer"]["matched"]} == {"ecoli-3d"}
