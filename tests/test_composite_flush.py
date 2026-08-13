import json
from pathlib import Path
from vivarium_workbench.lib import composite_flush


class _Req:
    steps = 10
    run_id = "r1"
    spec_id = "multiscale_bats.composites.bats_fba.bats_fba"


def test_flush_writes_report_and_empty_analyses(tmp_path, monkeypatch):
    monkeypatch.setattr(composite_flush, "_dispatch_analyses", lambda **kw: [])
    out = composite_flush.run_flush(
        tmp_path, req=_Req(), spec_id=_Req.spec_id,
        db_file=str(tmp_path / "runs.db"), run_id="r1", core=object(),
    )
    assert out["has_report"] is True
    assert out["has_analyses"] is False
    assert json.loads((tmp_path / "analyses.json").read_text()) == []
    html = (tmp_path / "report.html").read_text()
    assert "bats_fba" in html and "10" in html


def test_flush_never_raises(tmp_path, monkeypatch):
    def _boom(**kw):
        raise RuntimeError("analysis exploded")
    monkeypatch.setattr(composite_flush, "_dispatch_analyses", _boom)
    out = composite_flush.run_flush(
        tmp_path, req=_Req(), spec_id=_Req.spec_id,
        db_file=str(tmp_path / "runs.db"), run_id="r1", core=object(),
    )
    assert out["has_analyses"] is False        # swallowed, not raised
    assert (tmp_path / "report.html").is_file()  # report still written


def test_flush_renders_declared_analyses(tmp_path, monkeypatch):
    # a composite that declares one analysis → _dispatch_analyses RENDERS it
    # (via _render_analysis), not just records the declaration.
    rendered = {}

    def _render(**k):
        rendered["called"] = True
        return {"name": k.get("name"), "artifact": "a.json"}

    monkeypatch.setattr(composite_flush, "_render_analysis", _render, raising=False)
    monkeypatch.setattr(
        composite_flush, "_composite_analyses",
        lambda spec_id, core: [{"name": "mass_over_time"}], raising=False)
    out = composite_flush._dispatch_analyses(
        spec_id="c", db_file=str(tmp_path / "x.db"), run_id="r1", core=object())
    assert rendered.get("called") and out and out[0]["name"] == "mass_over_time"


def test_flush_analysis_failure_is_skipped(tmp_path, monkeypatch):
    # a failing render is logged and skipped — one bad analysis doesn't
    # break the flush, and OTHER declared analyses still render.
    def _render(**k):
        if k.get("name") == "boom":
            raise RuntimeError("analysis exploded")
        return {"name": k.get("name"), "artifact": "ok.json"}
    monkeypatch.setattr(composite_flush, "_render_analysis", _render, raising=False)
    monkeypatch.setattr(
        composite_flush, "_composite_analyses",
        lambda spec_id, core: [{"name": "boom"}, {"name": "mass_over_time"}],
        raising=False)
    out = composite_flush._dispatch_analyses(
        spec_id="c", db_file=str(tmp_path / "x.db"), run_id="r1", core=object())
    assert [a["name"] for a in out] == ["mass_over_time"]


def test_flush_no_analyses_is_graceful(tmp_path, monkeypatch):
    monkeypatch.setattr(
        composite_flush, "_composite_analyses", lambda spec_id, core: [], raising=False)
    out = composite_flush._dispatch_analyses(
        spec_id="c", db_file=str(tmp_path / "x.db"), run_id="r1", core=object())
    assert out == []


# --- Auto-fire viz refresh (self-driving fix) -------------------------------

def test_flush_auto_refreshes_declared_study_viz(tmp_path, monkeypatch):
    # db_file's parent is the study dir (matches study_runs.py's
    # `db_file = study_dir / "runs.db"` convention). A study.yaml with a
    # non-empty `visualizations:` should get refreshed automatically —
    # previously this only happened via a manual UI button.
    monkeypatch.setattr(composite_flush, "_dispatch_analyses", lambda **kw: [])
    study_dir = tmp_path / "studies" / "s1"
    study_dir.mkdir(parents=True)
    (study_dir / "study.yaml").write_text(
        "visualizations:\n  - name: fig1\n    chart: viz/fig1.json\n"
        "    render: echo hi\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    calls = {}

    def _fake_refresh(study_dir_arg, spec, latest):
        calls["study_dir"] = study_dir_arg
        calls["spec"] = spec
        return [{"name": "fig1", "status": "ok"}]

    import vivarium_workbench.lib.refresh_viz as refresh_viz_mod
    monkeypatch.setattr(refresh_viz_mod, "refresh_study_viz", _fake_refresh)

    out = composite_flush.run_flush(
        run_dir, req=_Req(), spec_id=_Req.spec_id,
        db_file=str(study_dir / "runs.db"), run_id="r1", core=object(),
    )

    assert out["has_viz_refresh"] is True
    assert calls["study_dir"] == study_dir
    assert calls["spec"]["visualizations"][0]["name"] == "fig1"


def test_flush_skips_viz_refresh_when_no_visualizations_declared(tmp_path, monkeypatch):
    monkeypatch.setattr(composite_flush, "_dispatch_analyses", lambda **kw: [])
    study_dir = tmp_path / "studies" / "s1"
    study_dir.mkdir(parents=True)
    (study_dir / "study.yaml").write_text("name: s1\n", encoding="utf-8")

    import vivarium_workbench.lib.refresh_viz as refresh_viz_mod

    def _boom(*a, **k):
        raise AssertionError("refresh_study_viz should not be called")

    monkeypatch.setattr(refresh_viz_mod, "refresh_study_viz", _boom)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    out = composite_flush.run_flush(
        run_dir, req=_Req(), spec_id=_Req.spec_id,
        db_file=str(study_dir / "runs.db"), run_id="r1", core=object(),
    )
    assert out["has_viz_refresh"] is False


def test_flush_viz_refresh_failure_is_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(composite_flush, "_dispatch_analyses", lambda **kw: [])
    study_dir = tmp_path / "studies" / "s1"
    study_dir.mkdir(parents=True)
    (study_dir / "study.yaml").write_text(
        "visualizations:\n  - name: fig1\n", encoding="utf-8")

    import vivarium_workbench.lib.refresh_viz as refresh_viz_mod

    def _boom(*a, **k):
        raise RuntimeError("refresh exploded")

    monkeypatch.setattr(refresh_viz_mod, "refresh_study_viz", _boom)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    out = composite_flush.run_flush(
        run_dir, req=_Req(), spec_id=_Req.spec_id,
        db_file=str(study_dir / "runs.db"), run_id="r1", core=object(),
    )
    assert out["has_viz_refresh"] is False        # swallowed, not raised
    assert out["has_report"] is True               # rest of flush still ran
