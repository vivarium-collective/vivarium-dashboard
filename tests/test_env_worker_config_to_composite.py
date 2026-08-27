import os, importlib.util, pytest

FORK = os.environ.get("V2E_VECOLI_DIR", "")
_have_translator = importlib.util.find_spec("v2ecoli.library.config_to_composite") is not None

@pytest.mark.skipif(not (FORK and os.path.isdir(FORK) and _have_translator),
                    reason="needs the vEcoli fork + the v2ecoli translator (post-#605 sync)")
def test_config_to_composite_handler_returns_loom_document():
    import ecoli.processes  # noqa: F401 — fork registry first
    from vivarium_workbench.env_worker import _config_to_composite
    cfg = {"add_processes": ["pg-shape"], "topology": {}}
    out = _config_to_composite({"config": cfg})
    assert "state" in out and "schema" in out
    node = out["state"]["pg-shape"]
    assert node["_type"] == "process" and node["address"] == "local:PGShape"

def test_config_to_composite_handler_unavailable_without_translator(monkeypatch):
    # Simulate a workspace whose package has no translator: force the import to fail.
    import builtins, vivarium_workbench.env_worker as ew
    real_import = builtins.__import__
    def _boom(name, *a, **k):
        if name.startswith("v2ecoli.library.config_to_composite"):
            raise ImportError("no translator")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _boom)
    assert ew._config_to_composite({"config": {}}) == {"__unavailable__": True}
