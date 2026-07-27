"""Phase 2c: computed verdict artifact in the engine flush."""
import json
import types
from pathlib import Path

from vivarium_workbench.lib.composite_flush import rollup_run_verdict


def _wc(p: Path, overall):
    p.write_text(json.dumps({"overall": overall}), encoding="utf-8")


# --- Task 1: rollup_run_verdict --------------------------------------------

def test_rollup_takes_worst_and_sorts_cards(tmp_path):
    _wc(tmp_path / "standard.verdict.json", "drift")
    _wc(tmp_path / "statistical.verdict.json", "mismatch")
    _wc(tmp_path / "config.verdict.json", "within_tol")
    out = rollup_run_verdict(sorted(tmp_path.glob("*.verdict.json")))
    assert out["schema"] == "run_verdict/v1"
    assert out["overall"] == "mismatch"                 # worst wins
    assert [c["name"] for c in out["cards"]] == ["config", "standard", "statistical"]
    assert {c["name"]: c["overall"] for c in out["cards"]}["config"] == "within_tol"


def test_rollup_empty_is_ungraded(tmp_path):
    assert rollup_run_verdict([]) == {
        "schema": "run_verdict/v1", "overall": "ungraded", "cards": []}


def test_rollup_bad_file_is_ungraded_card(tmp_path):
    bad = tmp_path / "broken.verdict.json"
    bad.write_text("{not json", encoding="utf-8")
    out = rollup_run_verdict([bad])
    assert out["cards"] == [{"name": "broken", "overall": "ungraded"}]
    assert out["overall"] == "ungraded"


def test_rollup_unknown_overall_is_ungraded(tmp_path):
    _wc(tmp_path / "weird.verdict.json", "banana")
    out = rollup_run_verdict([tmp_path / "weird.verdict.json"])
    assert out["cards"] == [{"name": "weird", "overall": "ungraded"}]


# --- Task 2: run_flush writes run_dir/verdict.json -------------------------

def test_run_flush_emits_verdict(tmp_path, monkeypatch):
    from vivarium_workbench.lib import composite_flush

    # two report-card verdicts that the (faked) analyses "wrote"
    _wc(tmp_path / "standard.verdict.json", "within_tol")
    _wc(tmp_path / "statistical.verdict.json", "mismatch")
    (tmp_path / "viz.json").write_text(json.dumps({"fig1": {}}), encoding="utf-8")

    def _fake_dispatch(**kwargs):
        return [{"name": "cards", "written": [
            str(tmp_path / "standard.verdict.json"),
            str(tmp_path / "statistical.verdict.json"),
        ], "errors": []}]

    monkeypatch.setattr(composite_flush, "_dispatch_analyses", _fake_dispatch)
    req = types.SimpleNamespace(steps=1, spec_id="pkg.mod.name")
    result = composite_flush.run_flush(
        tmp_path, req=req, spec_id="pkg.mod.name",
        db_file=str(tmp_path / "runs.db"), run_id="r0", core=None)

    assert result["has_verdict"] is True
    vj = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    assert vj["overall"] == "mismatch"
    assert [c["name"] for c in vj["cards"]] == ["standard", "statistical"]


# --- Task 3: content-address the verdict via artifact_pointers --------------

def test_maybe_record_verdict_pointer(tmp_path):
    import sqlite3
    from vivarium_workbench.lib.artifacts.pipeline import _maybe_record_verdict_pointer

    (tmp_path / "verdict.json").write_text(
        json.dumps({"schema": "run_verdict/v1", "overall": "drift", "cards": []}),
        encoding="utf-8")
    db = tmp_path / "runs.db"
    _maybe_record_verdict_pointer(db, tmp_path)

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT stage, artifact_id FROM artifact_pointers").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "verdict"
    assert rows[0][1]                       # a non-empty content hash


def test_maybe_record_verdict_pointer_no_file_is_noop(tmp_path):
    from vivarium_workbench.lib.artifacts.pipeline import _maybe_record_verdict_pointer
    # no verdict.json -> must not create the db / raise
    _maybe_record_verdict_pointer(tmp_path / "runs.db", tmp_path)
    assert not (tmp_path / "runs.db").exists()           # early-return, db untouched


# --- Task 4: reader prefers computed verdict over the size heuristic --------

def test_card_html_stub_prefers_verdict(tmp_path):
    from vivarium_workbench.lib.study_spec import _card_html_stub
    tiny = tmp_path / "standard.html"
    tiny.write_text("<i>", encoding="utf-8")             # 3 bytes
    # computed verdict present -> NOT a stub despite tiny html
    assert _card_html_stub(tiny, "drift") is False
    # no verdict -> size heuristic applies
    assert _card_html_stub(tiny, None) is True
    big = tmp_path / "big.html"
    big.write_text("x" * 200, encoding="utf-8")
    assert _card_html_stub(big, None) is False


def test_discover_report_card_urls_uses_computed_verdict(tmp_path):
    from vivarium_workbench.lib.study_spec import discover_report_card_urls
    rc = tmp_path / "studies" / "s1" / "viz" / "report_card"
    rc.mkdir(parents=True)
    (rc / "standard.html").write_text("<i>", encoding="utf-8")      # tiny
    _wc(rc / "standard.verdict.json", "drift")
    (rc / "bare.html").write_text("<i>", encoding="utf-8")          # tiny, no verdict

    urls = discover_report_card_urls(tmp_path, "s1")
    assert urls["standard"]["verdict"] == "drift"
    assert urls["standard"]["html_stub"] is False       # verdict wins over size
    assert urls["bare"]["html_stub"] is True            # heuristic preserved
