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


def test_declared_analysis_not_yet_executable_is_deferred_not_crash(tmp_path):
    # The real (un-monkeypatched) _dispatch_analysis raises NotImplementedError
    # today; it must be recorded as a soft `deferred` note, never crash, and
    # never masquerade as a genuine analysis `error`.
    spec = {"name": "inv", "analyses": [{"name": "comparison_matrix", "params": {}}]}
    (tmp_path / "investigations" / "inv").mkdir(parents=True)
    files, errors = run_investigation_analyses(tmp_path, "inv", spec, [])
    assert files == []
    assert len(errors) == 1
    assert errors[0]["analysis"] == "comparison_matrix"
    assert errors[0]["status"] == "deferred"
    assert "error" not in errors[0]
