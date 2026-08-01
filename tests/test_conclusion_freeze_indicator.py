"""G8 — frozen-record indicator for the conclusion card (Fable §11.4).

The conclusion card (``vivarium_workbench.lib.conclusion_card
.write_conclusion_card``) already freezes a study's verdict by writing
``viz/report_card/conclusion.verdict.json`` once per post-run flush — its
mere existence (parsed as a dict) IS the freeze signal; there is no separate
``frozen: true`` field and no schema change here. This makes that freeze
VISIBLE in the Decide tab: a lock glyph + "frozen <when>" (the file's own
mtime — no timestamp field is persisted inside the payload) + a short
deterministic content digest computed on the backend over the frozen
payload.

Mirrors ``test_conclusion_card.py``'s fixture style and
``test_actor_attribution.py``'s render-test style.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vivarium_workbench.lib import conclusion_card
from vivarium_workbench.lib.study_page import conclusion_digest

_V3_BASE = {
    "schema_version": 3,
    "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
    "variants": [],
}


def _write_study(ws: Path, slug: str, **fields) -> Path:
    sd = ws / "studies" / slug
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    spec = dict(_V3_BASE, name=slug, objective="test", status="in_progress", **fields)
    (sd / "study.yaml").write_text(yaml.safe_dump(spec))
    return sd


# ---------------------------------------------------------------------------
# Unit tests: the digest helper (pure, no I/O)
# ---------------------------------------------------------------------------


def test_same_payload_yields_same_digest():
    payload = {"schema": "conclusion_card/v1", "overall": "within_tol", "tracks": {"a": 1}}
    assert conclusion_digest(payload) == conclusion_digest(dict(payload))


def test_changed_payload_yields_different_digest():
    p1 = {"overall": "within_tol"}
    p2 = {"overall": "mismatch"}
    assert conclusion_digest(p1) != conclusion_digest(p2)


def test_key_order_does_not_change_digest():
    p1 = {"a": 1, "b": {"c": 2, "d": 3}}
    p2 = {"b": {"d": 3, "c": 2}, "a": 1}
    assert conclusion_digest(p1) == conclusion_digest(p2)


def test_digest_is_nonempty_hex_string():
    d = conclusion_digest({"x": 1})
    assert d
    assert all(c in "0123456789abcdef" for c in d)


def test_non_dict_payload_never_raises():
    assert conclusion_digest(None)
    assert conclusion_digest("not-a-dict")
    assert conclusion_digest([1, 2, 3])


# ---------------------------------------------------------------------------
# Rendering tests: frozen vs unfrozen
# ---------------------------------------------------------------------------


@pytest.fixture
def frozen_study(tmp_path):
    """A study whose conclusion card HAS been persisted -> frozen."""
    sd = _write_study(
        tmp_path / "ws", "frozen-study",
        pipeline_gate={"gate_evaluator": {"result": "passed"}},
        runs=[{"name": "r1", "status": "completed"}],
        findings=[{"tier": "interpretation", "statement": "X dominates"}],
    )
    assert conclusion_card.write_conclusion_card(sd) is True
    return sd


def test_frozen_study_spec_carries_when_and_payload(frozen_study):
    from vivarium_workbench.lib.study_spec import load_study_detail_spec

    ws = frozen_study.parent.parent
    spec = load_study_detail_spec(ws, "frozen-study")
    frozen = spec.get("conclusion_card_frozen")
    assert frozen is not None
    assert frozen.get("when")
    assert isinstance(frozen.get("payload"), dict)
    assert frozen["payload"].get("schema") == "conclusion_card/v1"


def test_frozen_study_renders_lock_glyph_when_and_digest(frozen_study):
    from vivarium_workbench.lib.study_spec import load_study_detail_spec
    from vivarium_workbench.lib.study_page import render_study_detail_html

    ws = frozen_study.parent.parent
    spec = load_study_detail_spec(ws, "frozen-study")
    html = render_study_detail_html(ws, "frozen-study", spec)

    assert "verdict-frozen-indicator" in html
    assert "frozen" in html
    digest = conclusion_digest(spec["conclusion_card_frozen"]["payload"])
    assert digest in html


def test_unfrozen_study_renders_no_frozen_indicator(tmp_path):
    from vivarium_workbench.lib.study_spec import load_study_detail_spec
    from vivarium_workbench.lib.study_page import render_study_detail_html

    ws = tmp_path / "ws"
    _write_study(ws, "unfrozen-study")
    spec = load_study_detail_spec(ws, "unfrozen-study")
    assert spec.get("conclusion_card_frozen") is None

    html = render_study_detail_html(ws, "unfrozen-study", spec)
    assert "verdict-frozen-indicator" not in html


def test_jinja_filter_registered_and_matches_python_function():
    import jinja2

    payload = {"z": 1, "a": 2}
    env = jinja2.Environment(autoescape=True)
    env.filters["conclusion_digest"] = conclusion_digest
    tpl = env.from_string("{{ payload | conclusion_digest }}")
    assert tpl.render(payload=payload) == conclusion_digest(payload)
