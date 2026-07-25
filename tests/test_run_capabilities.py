from vivarium_workbench.lib import run_capabilities as rc


def test_maps_categories_to_tags(monkeypatch):
    monkeypatch.setattr(rc.explorer_data, "list_observables",
        lambda *a, **k: {"categories": {"Mass": [1], "Bulk molecules": [1, 2]}})
    tags = rc.derive_capabilities("x.db", "run1")
    assert set(tags) == {"observables", "mass", "bulk_counts"}
    assert tags == sorted(tags)  # stable order


def test_empty_store_yields_empty(monkeypatch):
    monkeypatch.setattr(rc.explorer_data, "list_observables",
        lambda *a, **k: {"categories": {}})
    assert rc.derive_capabilities("x.db") == []


def test_read_failure_yields_empty(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("cannot open")
    monkeypatch.setattr(rc.explorer_data, "list_observables", boom)
    assert rc.derive_capabilities("x.db") == []  # never raises
