"""G7 — attribution from existing fields (Fable §11.2, §14.1(5)).

Wherever an actor is already recorded (``feedback_tracked[].author`` /
``.responded_by``, ``expert_decisions_needed[].asked_to``), render who + when,
distinguishing human vs agent (agent shows its model where the recorded
string carries one). No actor recorded -> the literal ``unattributed`` token,
never blank. No new schema fields — only existing, already-plumbed fields are
read.

Mirrors ``test_outcome_vocabulary.py``'s style for the classification-helper
unit tests, and ``test_feedback_tracking_render.py``'s style for the
spec-plumbing + rendered-HTML tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vivarium_workbench.lib.study_page import (
    actor_glyph,
    actor_kind,
    actor_model,
    attribution_text,
)


# ---------------------------------------------------------------------------
# Unit tests: the classification helper
# ---------------------------------------------------------------------------


def test_a_plain_human_name_classifies_as_human():
    # "Haochen" matches no known agent/automation naming token -> the
    # documented honest default (human), not a name guess about who this
    # specific person is.
    assert actor_kind("Haochen") == "human"
    assert actor_kind("Alice") == "human"


def test_a_known_agent_naming_token_classifies_as_agent():
    # Real fixture shape confirmed in feedback_tracking's own tests:
    # responses[...].by == "claude". Structural token match, not a guess.
    assert actor_kind("claude") == "agent"
    assert actor_kind("claude-opus-4-8") == "agent"
    assert actor_kind("gpt-4o") == "agent"
    assert actor_kind("ci-bot") == "agent"


def test_empty_or_none_actor_is_unattributed_never_blank_never_raises():
    assert actor_kind(None) == "unattributed"
    assert actor_kind("") == "unattributed"
    assert actor_kind("   ") == "unattributed"


def test_actor_model_for_agent_is_the_recorded_string_never_fabricated():
    assert actor_model("claude-opus-4-8") == "claude-opus-4-8"
    assert actor_model("claude") == "claude"


def test_actor_model_is_none_for_human_or_unattributed():
    assert actor_model("Haochen") is None
    assert actor_model(None) is None
    assert actor_model("") is None


def test_actor_glyph_one_glyph_per_kind():
    assert actor_glyph("Haochen") != actor_glyph("claude")
    assert actor_glyph(None) != actor_glyph("Haochen")
    # Never raises, never blank
    assert actor_glyph(None)


def test_attribution_text_renders_by_actor_and_when():
    text = attribution_text("Haochen", "2026-01-05T10:00:00Z")
    assert text.startswith("by Haochen")
    assert "2026-01-05T10:00:00Z" in text


def test_attribution_text_omits_when_if_absent():
    text = attribution_text("Haochen", None)
    assert text == "by Haochen"


def test_attribution_text_is_the_literal_unattributed_token_when_no_actor():
    assert attribution_text(None, "2026-01-05T10:00:00Z") == "unattributed"
    assert attribution_text("", None) == "unattributed"


def test_jinja_filters_registered_and_match_the_python_functions():
    import jinja2

    env = jinja2.Environment(autoescape=True)
    env.filters["actor_kind"] = actor_kind
    env.filters["actor_glyph"] = actor_glyph
    env.filters["attribution_text"] = attribution_text
    tpl = env.from_string(
        "{{ 'claude' | actor_kind }}/{{ none | actor_glyph }}/{{ none | attribution_text }}"
    )
    assert tpl.render() == "agent/○/unattributed"


# ---------------------------------------------------------------------------
# Rendering tests: expert_decisions_needed (Pre-run expert review panel)
# ---------------------------------------------------------------------------

_V3_BASE = {
    "schema_version": 3,
    "baseline": [{"name": "core", "composite": "pkg.composites.core", "params": {}}],
    "variants": [],
    "runs": [],
}


@pytest.fixture
def ws_with_expert_decision(tmp_path):
    ws = tmp_path / "ws"
    sd = ws / "studies" / "expert-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    spec = dict(
        _V3_BASE,
        name="expert-study",
        objective="test",
        status="in_progress",
        expert_decisions_needed=[
            {
                "id": "q1",
                "status": "open",
                "question": "Is media X or Y correct?",
                "asked_to": "Haochen",
            },
            {
                "id": "q2",
                "status": "open",
                "question": "No actor recorded here.",
            },
        ],
    )
    (sd / "study.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    return ws


def test_asked_to_actor_renders_with_human_glyph(ws_with_expert_decision):
    from vivarium_workbench.lib.study_spec import load_study_detail_spec
    from vivarium_workbench.lib.study_page import render_study_detail_html

    spec = load_study_detail_spec(ws_with_expert_decision, "expert-study")
    html = render_study_detail_html(ws_with_expert_decision, "expert-study", spec)

    assert "Haochen" in html
    # The human glyph must appear near the asked_to actor.
    assert actor_glyph("Haochen") in html


def test_missing_asked_to_renders_literal_unattributed(ws_with_expert_decision):
    from vivarium_workbench.lib.study_spec import load_study_detail_spec
    from vivarium_workbench.lib.study_page import render_study_detail_html

    spec = load_study_detail_spec(ws_with_expert_decision, "expert-study")
    html = render_study_detail_html(ws_with_expert_decision, "expert-study", spec)

    assert "unattributed" in html


# ---------------------------------------------------------------------------
# Rendering tests: the verdict/conclusion card — no actor/timestamp field is
# currently plumbed anywhere near conclusion_verdicts / conclusion.verdict.json
# (confirmed by reading conclusion_card.py + study_derivations.conclusion_verdicts),
# so it must ALWAYS render the literal "unattributed" token, never blank.
# ---------------------------------------------------------------------------


@pytest.fixture
def ws_v3_minimal(tmp_path):
    ws = tmp_path / "ws"
    sd = ws / "studies" / "min-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    spec = dict(_V3_BASE, name="min-study", objective="test", status="in_progress")
    (sd / "study.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    return ws


def test_verdict_renders_literal_unattributed_when_no_actor_plumbed(ws_v3_minimal):
    from vivarium_workbench.lib.study_spec import load_study_detail_spec
    from vivarium_workbench.lib.study_page import render_study_detail_html

    spec = load_study_detail_spec(ws_v3_minimal, "min-study")
    html = render_study_detail_html(ws_v3_minimal, "min-study", spec)

    assert "Verdict &amp; conclusion" in html or "Verdict & conclusion" in html
    assert "unattributed" in html
