"""The aliased /api/study-* handlers must find studies in studies/, not just investigations/."""
import yaml
import pytest


@pytest.fixture
def _ws(tmp_path, monkeypatch):
    """Workspace with one study in studies/ and one legacy investigation."""
    import vivarium_dashboard.server as srv
    ws = tmp_path / "ws"
    # A v3 study under studies/
    sd = ws / "studies" / "new-study"
    sd.mkdir(parents=True)
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3, "name": "new-study", "created": "2026-05-14",
        "status": "ran", "objective": "obj",
        "baseline": {"composite": "pkg.foo", "params": {}},
        "variants": [], "runs": [], "visualizations": [],
        "conclusion": None, "parent_studies": [],
    }))
    # A legacy investigation under investigations/
    legacy = ws / "investigations" / "old-inv"
    legacy.mkdir(parents=True)
    (legacy / "spec.yaml").write_text(yaml.safe_dump({
        "schema_version": 2, "name": "old-inv", "created": "2026-04-01",
        "composites": [{"name": "main", "source": "pkg.bar"}],
    }))
    monkeypatch.setattr(srv, "WORKSPACE", ws)
    return ws


def test_study_dir_prefers_studies(_ws):
    from vivarium_dashboard.server import _study_dir
    d = _study_dir("new-study")
    assert d == _ws / "studies" / "new-study"


def test_study_dir_falls_back_to_investigations(_ws):
    from vivarium_dashboard.server import _study_dir
    d = _study_dir("old-inv")
    assert d == _ws / "investigations" / "old-inv"


def test_study_spec_path_picks_study_yaml(_ws):
    from vivarium_dashboard.server import _study_spec_path
    p = _study_spec_path("new-study")
    assert p.name == "study.yaml"
    assert p == _ws / "studies" / "new-study" / "study.yaml"


def test_study_spec_path_picks_spec_yaml_for_legacy(_ws):
    from vivarium_dashboard.server import _study_spec_path
    p = _study_spec_path("old-inv")
    assert p.name == "spec.yaml"
    assert p == _ws / "investigations" / "old-inv" / "spec.yaml"


def test_iter_study_dirs_includes_both(_ws):
    from vivarium_dashboard.server import _iter_study_dirs
    names = sorted(d.name for d in _iter_study_dirs())
    assert names == ["new-study", "old-inv"]
