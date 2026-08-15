"""needs_attention surfaces the severity gate's hard axes + test regressions."""
import vivarium_workbench.lib.needs_attention as na


def test_hard_gate_items_one_per_gated_axis(monkeypatch):
    monkeypatch.setattr(na, "_latest_run_json", lambda ws, wp, slug, fn: (
        {"gate": {"status": "fail", "gated_by": [
            {"card": "c1", "group": "g", "id": "a"},
            {"card": "c1", "group": "g", "id": "b"}]}} if fn == "report.json" else None))
    items = na._hard_gate_items("ws", None, "demo")
    assert len(items) == 2
    assert all(it["kind"] == "hard_gate" and it["severity"] == "high" for it in items)
    assert {it["ref"] for it in items} == {"c1:a", "c1:b"}


def test_hard_gate_items_pass_yields_nothing(monkeypatch):
    monkeypatch.setattr(na, "_latest_run_json",
                        lambda *a: {"gate": {"status": "pass", "gated_by": []}})
    assert na._hard_gate_items("ws", None, "demo") == []


def test_regression_items_broke_high_regressed_medium(monkeypatch):
    diff = {"per": [
        {"card": "c1", "group": "g", "id": "a", "change": "broke", "margin_delta": -0.5},
        {"card": "c1", "group": "g", "id": "b", "change": "regressed", "margin_delta": -0.2},
        {"card": "c1", "group": "g", "id": "c", "change": "improved", "margin_delta": 0.3},
        {"card": "c1", "group": "g", "id": "d", "change": "unchanged", "margin_delta": 0.0},
    ]}
    monkeypatch.setattr(na, "_latest_run_json",
                        lambda ws, wp, slug, fn: diff if fn == "test_diff.json" else None)
    items = na._test_regression_items("ws", None, "demo")
    byref = {it["ref"]: it for it in items}
    assert set(byref) == {"c1:a", "c1:b"}          # only broke + regressed
    assert byref["c1:a"]["severity"] == "high"     # broke
    assert byref["c1:b"]["severity"] == "medium"   # regressed
    assert all(it["kind"] == "test_regression" for it in items)
