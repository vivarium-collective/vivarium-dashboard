"""Task C3 (Fable Increment C §4.2, §6 #14): the Compose/Model tab used to
render the baseline TWICE — once as the rich Model card (``study.baseline[]``)
and again as a thinner Conditions -> Baseline block (``study.conditions.baseline``).
These tests pin the merged "Runnable models" list: one render of the baseline
composite/params, with the ``⚠ needs a value`` marker surfaced from the
model-settings ``gate: required-before-run`` signal, while the Variants table
and the editable model-settings (``cond-expert-table``) survive untouched.
"""
from pathlib import Path

from vivarium_workbench.lib.study_page import render_study_detail_html


def _panel_compose(html: str) -> str:
    i = html.index('id="panel-compose"')
    nxt = html.find('class="study-tab-panel"', i + 10)
    return html[i: nxt if nxt != -1 else len(html)]


def _render(tmp_path: Path, name: str, spec: dict) -> str:
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    full_spec = {"name": name, "status": "draft", **spec}
    return render_study_detail_html(ws, name, full_spec)


# ---------------------------------------------------------------------------
# v4 fixture: study.baseline[] AND study.conditions.baseline both present,
# same composite — plus a required-before-run model setting with no value.
# ---------------------------------------------------------------------------

_V4_SPEC = {
    "schema_version": 4,
    "baseline": [
        {"name": "baseline", "composite": "pbg_demo.composites.demo",
         "params": {"temperature": 37}},
    ],
    "conditions": {
        "baseline": {
            "composite": "pbg_demo.composites.demo",
            "params": {"temperature": 37, "ph": 7.0},
        },
        "variants": [
            {"name": "hot", "parameter_overrides": {"temperature": 42}},
        ],
        "model_settings": [
            {"name": "growth_rate", "type": "number", "default": 0.5,
             "current": None, "range": [0.1, 2.0], "gate": "required-before-run"},
            {"name": "seed_count", "type": "integer", "default": 1,
             "current": 3, "gate": "optional"},
        ],
    },
}


def test_v4_baseline_renders_exactly_once(tmp_path):
    html = _render(tmp_path, "v4-study", _V4_SPEC)
    panel = _panel_compose(html)
    # Exactly one model card is rendered for this composite — no duplicate
    # cond-block between the Model card and a separate Conditions -> Baseline
    # block. (The ref itself legitimately repeats WITHIN one card: the
    # data-model-composite attribute, the <code> chip, the explore-and-run
    # button, and the Set-composite input value all echo it.)
    assert panel.count('data-model-composite="pbg_demo.composites.demo"') == 1
    # The old separate Conditions "Baseline" sub-block is gone.
    assert '<div class="cond-block-title">Baseline</div>' not in panel
    # The un-duplicated param (ph, only on conditions.baseline) is still
    # surfaced somewhere on the merged card so it isn't silently dropped.
    assert "ph" in panel and "7.0" in panel
    # Heading renamed per Fable #14.
    assert "Runnable models" in panel


def test_v4_required_before_run_marker_renders_inline(tmp_path):
    html = _render(tmp_path, "v4-study", _V4_SPEC)
    panel = _panel_compose(html)
    assert "needs a value" in panel
    # It's attached to the unset required setting, not the already-set one.
    i_growth = panel.index("growth_rate")
    i_marker = panel.index("needs a value")
    i_seed = panel.index("seed_count")
    # marker sits between the two rows, closer to growth_rate than seed_count
    assert i_growth < i_marker < i_seed


def test_v4_variants_table_preserved(tmp_path):
    html = _render(tmp_path, "v4-study", _V4_SPEC)
    panel = _panel_compose(html)
    assert "cond-table" in panel
    assert "hot" in panel
    assert "temperature" in panel


def test_v4_editable_model_settings_table_preserved(tmp_path):
    html = _render(tmp_path, "v4-study", _V4_SPEC)
    panel = _panel_compose(html)
    assert 'cond-expert-table' in panel
    assert "cond-ei-input" in panel
    assert "_saveExpertInput" in panel
    assert "growth_rate" in panel and "seed_count" in panel


def test_v4_js_keyed_hooks_preserved(tmp_path):
    html = _render(tmp_path, "v4-study", _V4_SPEC)
    panel = _panel_compose(html)
    assert "baseline-composite-input" in panel
    assert "baseline-composite-set" in panel
    assert "model-config-mount" in panel
    assert "cond-expert-table" in panel


# ---------------------------------------------------------------------------
# non-v3 fixture: only study.baseline, no study.conditions at all.
# ---------------------------------------------------------------------------

_BASELINE_ONLY_SPEC = {
    "baseline": [
        {"name": "baseline", "composite": "pbg_demo.composites.legacy",
         "params": {"n_steps": 5}},
    ],
}


def test_baseline_only_study_still_renders_model_card(tmp_path):
    html = _render(tmp_path, "legacy-study", _BASELINE_ONLY_SPEC)
    panel = _panel_compose(html)
    assert "pbg_demo.composites.legacy" in panel
    assert "explore &amp; run" in panel or "explore & run" in panel
    assert "baseline-composite-input" in panel
    assert "baseline-composite-set" in panel
    assert "Runnable models" in panel
    # No Conditions section at all — study.conditions absent.
    assert 'id="conditions-section"' not in panel


# ---------------------------------------------------------------------------
# conditions-only fixture: only study.conditions.baseline, no top-level
# study.baseline[] list at all (the v4-redesign path).
# ---------------------------------------------------------------------------

_CONDITIONS_ONLY_SPEC = {
    "schema_version": 4,
    "conditions": {
        "baseline": {"composite": "pbg_demo.composites.x", "params": {}},
        "variants": [],
        "model_settings": [],
    },
}


def test_conditions_only_study_still_shows_baseline_model(tmp_path):
    html = _render(tmp_path, "conditions-only-study", _CONDITIONS_ONLY_SPEC)
    panel = _panel_compose(html)
    assert "pbg_demo.composites.x" in panel
    assert "Runnable models" in panel
    assert panel.count('data-model-composite="pbg_demo.composites.x"') == 1


# ---------------------------------------------------------------------------
# absent case: no baseline anywhere renders nothing (not an empty box).
# ---------------------------------------------------------------------------

def test_no_baseline_renders_no_model_section(tmp_path):
    html = _render(tmp_path, "no-model-study", {})
    panel = _panel_compose(html)
    assert 'id="model-section"' not in panel
    assert "Runnable models" not in panel
