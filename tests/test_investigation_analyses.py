import yaml
from pathlib import Path
from vivarium_workbench.lib.investigation_analyses import run_investigation_analyses


def test_no_analyses_key_is_noop(tmp_path):
    (tmp_path / "investigations" / "inv").mkdir(parents=True)
    files, errors = run_investigation_analyses(tmp_path, "inv", {"name": "inv"}, [])
    assert files == [] and errors == []


def test_declared_analysis_is_dispatched(tmp_path, monkeypatch):
    import vivarium_workbench.lib.investigation_analyses as ia
    calls = []
    monkeypatch.setattr(ia, "_dispatch_analysis",
                        lambda ws, inv, entry, results: calls.append(entry["name"]) or ["out.html"])
    spec = {"name": "inv", "analyses": [{"name": "comparison_matrix", "params": {}}]}
    (tmp_path / "investigations" / "inv").mkdir(parents=True)
    files, errors = run_investigation_analyses(tmp_path, "inv", spec, [])
    assert calls == ["comparison_matrix"] and files == ["out.html"] and errors == []
