"""render_report_cards_section surfaces the study's report cards — the compiled
output of its Tests (viz/report_card/<card>.html + verdict.json, the same source
the SPA Tests tab uses) — plus the since-last-run change, in the static report."""
import json

import vivarium_workbench.lib.report_card_section as rcs


def _card(tmp_path, name, html, verdict):
    rc = tmp_path / "studies" / "s" / "viz" / "report_card"
    rc.mkdir(parents=True, exist_ok=True)
    (rc / f"{name}.html").write_text(html, encoding="utf-8")
    if verdict is not None:
        (rc / f"{name}.verdict.json").write_text(json.dumps(verdict), encoding="utf-8")


def _patch_study_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("vivarium_workbench.lib.study_spec.study_dir",
                        lambda ws, slug: tmp_path / "studies" / slug)


_VERDICT = {
    "overall": "mismatch",
    "groups": {"physiology": {"verdict": "mismatch", "axes": [
        {"id": "doubling_time", "label": "Doubling time", "verdict": "within_tol", "meter": "Δ=-2%"},
        {"id": "growth_rate", "label": "Growth rate", "verdict": "mismatch", "meter": "Δ=-40%"}]}},
}


def test_reuses_report_card_output_and_change(tmp_path, monkeypatch):
    _card(tmp_path, "growth", "<b>stub</b>", _VERDICT)   # stub → verdict table
    _patch_study_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(rcs, "_latest_run_json", lambda ws, slug, fn: (
        {"per": [{"card": "growth", "id": "growth_rate", "change": "broke", "margin_delta": -0.5}]}
        if fn == "test_diff.json" else None))
    html = rcs.render_report_cards_section(tmp_path, "s")
    assert '<section id="report-cards">' in html
    assert "Report cards" in html
    assert "Doubling time" in html and "Growth rate" in html   # per-test rows
    assert "growth" in html                                     # card name
    assert "within tol" in html and "mismatch" in html         # verdict chips
    assert "broke" in html                                      # since-last-run badge
    assert "Since last run" in html                            # diff rollup line


def test_real_card_html_is_embedded(tmp_path, monkeypatch):
    rich = "<html><body>" + ("<div>chart</div>" * 10) + "</body></html>"
    _card(tmp_path, "overflow", rich, {"overall": "within_tol", "groups": {}})
    _patch_study_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(rcs, "_latest_run_json", lambda ws, slug, fn: None)
    html = rcs.render_report_cards_section(tmp_path, "s")
    assert 'class="rc-iframe"' in html          # rich render embedded as iframe
    assert "rc-iframe" in html and "<script>" in html   # + fit script


def test_no_report_cards_yields_empty(tmp_path, monkeypatch):
    (tmp_path / "studies" / "s").mkdir(parents=True)
    _patch_study_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(rcs, "_latest_run_json", lambda ws, slug, fn: None)
    assert rcs.render_report_cards_section(tmp_path, "s") == ""


def test_diff_absent_still_renders_cards(tmp_path, monkeypatch):
    _card(tmp_path, "growth", "<b>stub</b>", _VERDICT)
    _patch_study_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(rcs, "_latest_run_json", lambda ws, slug, fn: None)
    html = rcs.render_report_cards_section(tmp_path, "s")
    assert '<section id="report-cards">' in html and "Growth rate" in html
    assert "Since last run: " not in html       # no diff → no rollup line (header col still present)
