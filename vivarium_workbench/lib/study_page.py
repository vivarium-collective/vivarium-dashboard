"""Study-detail page builder — Jinja2 render + page builder.

Extracted from ``vivarium_workbench.server`` so both the FastAPI seam
(``api/app.py``) and ``server.py``'s handler can share one implementation.
``server.py`` re-exports ``_render_study_detail_html`` as a thin shim (2-arg
``(name, spec)``) so ``publish.py`` and existing call-sites keep working
unchanged.

Public API
----------
render_study_detail_html(ws_root, name, spec)  → str
    Render the study-detail Jinja2 template for *name* against *spec*.

build_study_detail_page(ws_root, slug)  → (html, status_code)
    Full page builder: slug-validate → 404; spec-load → 404; render → 200.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import vivarium_workbench as _vd_pkg

_TEMPLATES_DIR: Path = Path(_vd_pkg.__file__).parent / "templates"

from vivarium_workbench.lib.study_spec import SLUG_RE as _SLUG_RE  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers (moved from server.py)
# ---------------------------------------------------------------------------

def _enrich_runs_with_meta(study_dir: Path, runs: list) -> list:
    """Merge per-run metadata from studies/<name>/runs.db into study.runs[].

    study.yaml's runs[] carries only the slim authoritative fields (run_id,
    variant, composite, label, status, n_steps). The runs_meta table in
    runs.db carries the rich per-run record (spec_id, params, started_at,
    completed_at, log_path). The Runs tab needs both. We copy the rich
    fields onto each entry under namespaced keys (``meta_*``) so the
    template doesn't have to know which DB they came from.

    Tolerant: if runs.db is absent, has no row for a run_id, or fails to
    open, the run entry is returned unchanged.
    """
    if not runs:
        return runs
    db = study_dir / "runs.db"
    rows: list = []
    if db.is_file():
        import sqlite3 as _sql
        try:
            conn = _sql.connect(str(db))
            conn.row_factory = _sql.Row
            rows = conn.execute(
                "SELECT run_id, spec_id, params_json, started_at, completed_at, "
                "n_steps, status, log_path FROM runs_meta"
            ).fetchall()
            conn.close()
        except _sql.Error:
            rows = []
    import json as _json
    by_id = {r["run_id"]: r for r in rows}
    enriched = []
    for r in runs:
        out = dict(r)
        # Always set meta_* keys so the Jinja template can call filters
        # against them unconditionally (None → empty cell).
        out.setdefault("meta_spec_id", None)
        out.setdefault("meta_started_at", None)
        out.setdefault("meta_completed_at", None)
        out.setdefault("meta_duration_sec", None)
        out.setdefault("meta_params", {})
        out.setdefault("meta_log_path", None)
        m = by_id.get(r.get("run_id"))
        if m is not None:
            try:
                params = _json.loads(m["params_json"] or "{}")
            except (ValueError, TypeError):
                params = {}
            started = m["started_at"]
            completed = m["completed_at"]
            duration = (completed - started) if (started and completed) else None
            out["meta_spec_id"] = m["spec_id"]
            out["meta_started_at"] = started
            out["meta_completed_at"] = completed
            out["meta_duration_sec"] = duration
            out["meta_params"] = params
            out["meta_log_path"] = m["log_path"]
        enriched.append(out)
    return enriched


def _humanize_study_name(slug: str) -> dict:
    """Mirror of JS _humanizeStudyName: peel a leading '<prefix>-NN[a-z]?-' into
    a chip and humanize the remainder. Keeps dashboard + report names identical."""
    m = re.match(r"^([a-z]+-\d+[a-z]*)-(.+)$", slug or "")
    if not m:
        return {"chip": "", "title": (slug or "").replace("-", " ")}
    rest = m.group(2).replace("-", " ")
    rest = rest[:1].upper() + rest[1:]
    if len(rest) > 60:
        rest = rest[:57] + "…"
    return {"chip": m.group(1), "title": rest}


def _jinja_fmt_ts(ts) -> str:
    """Format a unix timestamp as 'YYYY-MM-DD HH:MM' UTC, or '' if missing.

    Returns '' for None, empty values, AND undefined (Jinja's Undefined
    sentinel — e.g. when the template walks ``r.meta_started_at or
    r.started_at`` against a dict that has neither key). The previous
    ``(TypeError, ValueError)`` excludes Jinja's UndefinedError, which
    escaped here as a template-render failure for every <tr> in the
    Runs table whenever the merged run dict was missing both fields.
    """
    try:
        ts = float(ts)
    except Exception:
        return ""
    if not ts:
        return ""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _jinja_fmt_duration(seconds) -> str:
    """Format a duration in seconds as '12s', '1m 30s', '2h 15m', or '' if missing.

    Same Undefined-tolerance contract as _jinja_fmt_ts above.
    """
    try:
        seconds = float(seconds)
    except Exception:
        return ""
    if seconds < 0:
        return ""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if m else f"{h}h"


def _jinja_markdown(text):
    """Render authored prose (e.g. ``study.conclusion``) as Markdown.

    Authors often hard-wrap conclusion text at ~80 columns; rendered in a
    ``<pre>`` that produces a narrow column with wasted width. Markdown reflows
    soft-wrapped lines within a paragraph to fill the container, keeps
    blank-line paragraph breaks, and turns ``1. 2. 3.`` into an ordered list.

    Defensive: raw HTML in the source is NOT interpreted (CommonMark's default
    ``html=False``) so it is safe for study-authored content, and if
    ``markdown-it-py`` is unavailable/errors it falls back to the previous
    escaped, newline-preserving ``<pre>`` rendering.
    """
    from markupsafe import Markup, escape
    if text is None:
        return Markup("")
    s = str(text)
    if not s.strip():
        return Markup("")
    try:
        from markdown_it import MarkdownIt
        # html=False: the CommonMark preset otherwise passes raw HTML through;
        # disable it so study-authored content can't inject markup (XSS-safe).
        return Markup(MarkdownIt("commonmark", {"html": False}).render(s))
    except Exception:  # noqa: BLE001 — degrade to the old pre-wrap behavior
        return Markup(
            '<pre style="white-space:pre-wrap;font-family:inherit;margin:0">'
            + str(escape(s)) + '</pre>'
        )


# ---------------------------------------------------------------------------
# G3 — shared outcome vocabulary (Fable §10.1, §14.1(4))
# ---------------------------------------------------------------------------
# ONE display mapping from the existing verdict/test tokens onto the four-value
# audit vocabulary: met / conditional-pass / not met / not assessable. This is
# a DISPLAY-ONLY remap — it never changes a stored token or a computation, and
# every later G task (G4-G8) reuses it so the vocabulary reads identically
# everywhere on the study page.
#
# Three token families feed it (confirmed by grep, not invented):
#   - test/verdict tokens — study.tests[]/runs[].outcomes[].result,
#     conclusion_card tracks: PASS / FAIL / PARTIAL / SKIP / PENDING / GAP
#     (study_spec._latest_outcomes, study_derivations.GATE_RESULT_NORM,
#     conclusion_card._RESULT_TO_CANON).
#   - report-card verdict tokens — study_spec._REPORT_CARD_VERDICTS:
#     within_tol / drift / mismatch / ungraded.
#   - acceptance-criterion result tokens — spine_acceptance's per-criterion
#     `result` (study_enrichment.study_acceptance_criterion), sourced from
#     viva_superpowers.investigation_status's _CRIT_PASS/_CRIT_FAIL/
#     _CRIT_CAVEATS/_CRIT_PROGRESS: passing / failing /
#     passing-with-caveats / in-progress.
# Matching is case-insensitive. Anything outside these three families — an
# unknown token, empty string, or None — degrades to "not assessable" (spec
# §2 R2: absent != empty; never blank, never a crash).
_OUTCOME_TOKEN_MAP: dict[str, str] = {
    # test/verdict tokens
    "PASS": "met",
    "FAIL": "not met",
    "PARTIAL": "conditional-pass",
    "SKIP": "not assessable",
    "PENDING": "not assessable",
    "GAP": "not assessable",
    # report-card tokens (study_spec._REPORT_CARD_VERDICTS)
    "WITHIN_TOL": "met",
    "DRIFT": "conditional-pass",
    "MISMATCH": "not met",
    "UNGRADED": "not assessable",
    # acceptance-criterion tokens (viva_superpowers.investigation_status)
    "PASSING": "met",
    "FAILING": "not met",
    "PASSING-WITH-CAVEATS": "conditional-pass",
    "IN-PROGRESS": "not assessable",
}

# CSS-class-safe slug + single-character glyph per audit outcome, so every
# caller renders the same color/glyph instead of re-deriving one.
_OUTCOME_CLASS: dict[str, str] = {
    "met": "met",
    "conditional-pass": "conditional",
    "not met": "not-met",
    "not assessable": "not-assessable",
}
_OUTCOME_GLYPH: dict[str, str] = {
    "met": "✓",
    "conditional-pass": "◐",
    "not met": "✗",
    "not assessable": "○",
}


def outcome_label(token) -> str:
    """Map an existing verdict/test token to the four-value audit vocabulary.

    ``met`` / ``conditional-pass`` / ``not met`` / ``not assessable`` — see
    ``_OUTCOME_TOKEN_MAP`` above for the confirmed token set. Case-insensitive;
    ``None``/empty/unknown tokens map to ``"not assessable"`` (never raises,
    never blank). Registered as the Jinja filter ``outcome_label``.
    """
    key = str(token).strip().upper() if token is not None else ""
    return _OUTCOME_TOKEN_MAP.get(key, "not assessable")


def outcome_class(token) -> str:
    """CSS-class-safe slug for ``outcome_label(token)`` (e.g. ``"conditional"``)."""
    return _OUTCOME_CLASS[outcome_label(token)]


def outcome_glyph(token) -> str:
    """Single-character glyph for ``outcome_label(token)`` (e.g. ``"◐"``)."""
    return _OUTCOME_GLYPH[outcome_label(token)]


# ---------------------------------------------------------------------------
# G2 — the gating model (Fable §13, docs/superpowers/specs/
# 2026-08-01-study-design-fable-pass.md). The six status axes ARE the six
# gates already (design/implementation/simulation/evaluation/gate/
# expert_review) — §13's table maps them:
#   Plan ← design_status · Execution ← simulation_status ·
#   Evidence ← evaluation_status · Quality ← evaluation_status (yes, the
#   SAME axis backs both Evidence and Quality — that's the spec's table, not
#   a bug here) · Decision ← gate_status · Release ← expert_review_status.
# `implementation_status` has no gate — §13's table simply never assigns it
# one (it stays a plain authored axis, unchanged from before this task).
# ---------------------------------------------------------------------------

# §13.2 gate-state vocabulary. Axis values are free-authored strings (not a
# closed enum), so classification is a heuristic token map; anything
# unrecognized degrades to "not-assessed" rather than guessing a pass —
# mirrors outcome_label's "never invent, never blank" rule.
_GATE_STATE_TOKENS: dict[str, str] = {
    # passed — the axis (or computed evaluator) is done and clean
    "passed": "passed", "pass": "passed", "ok": "passed", "approved": "passed",
    "complete": "passed", "completed": "passed", "ran": "passed",
    "evaluated": "passed", "done": "passed", "designed": "passed",
    "implemented": "passed", "signed_off": "passed",
    # passed-with-conditions — assessed, open findings / partial credit
    "needs_calibration": "passed-with-conditions", "partial": "passed-with-conditions",
    "mixed": "passed-with-conditions", "drift": "passed-with-conditions",
    # blocked — assessed and failing
    "blocked": "blocked", "failed": "blocked", "fail": "blocked",
    "mismatch": "blocked", "stale": "blocked", "failed_evaluation": "blocked",
    # waived — explicitly accepted as residual risk (D1.3; not authored
    # anywhere on this page yet, kept for forward-compat with §13.2's vocab)
    "waived": "waived",
    # not-assessed — nothing decided yet (includes "in progress"/"pending":
    # not yet a finding, just not started or not finished)
    "not_started": "not-assessed", "not_run": "not-assessed",
    "not_evaluated": "not-assessed", "planning": "not-assessed",
    "planned": "not-assessed", "pending": "not-assessed",
    "in_progress": "not-assessed", "running": "not-assessed",
}
_GATE_STATES = ("not-assessed", "passed", "passed-with-conditions", "blocked", "waived")
# Severity rank among the states that carry a REAL assessment (higher = more
# in need of attention): a blocked/at-risk state must never hide behind a
# clean pass. "not-assessed" has no rank here — it isn't a severity, it's the
# absence of an opinion, and _worst_gate_state below treats it as neutral
# (filtered out before ranking) rather than as a value that can outrank
# "passed". See _worst_gate_state's docstring — this was Fable G2's fix-round-1
# bug: not-assessed used to outrank passed and collapsed every gate with an
# empty authored axis + a passing COMPUTED value down to grey.
_GATE_STATE_RANK = {
    "blocked": 4, "passed-with-conditions": 3, "waived": 1, "passed": 0,
}
_GATE_STATE_GLYPH = {
    "not-assessed": "○", "passed": "✓", "passed-with-conditions": "◐",
    "blocked": "✗", "waived": "⚑",
}


def gate_state(token) -> str:
    """Classify a raw axis/computed status token into the §13.2 gate-state
    vocabulary (``not-assessed`` / ``passed`` / ``passed-with-conditions`` /
    ``blocked`` / ``waived``). Unset or unrecognized tokens degrade to
    ``not-assessed``. Registered as the Jinja filter ``gate_state``."""
    if not token:
        return "not-assessed"
    return _GATE_STATE_TOKENS.get(str(token).strip().lower(), "not-assessed")


def gate_state_glyph(token) -> str:
    """Single-character glyph for ``gate_state(token)``. Registered as the
    Jinja filter ``gate_state_glyph``."""
    return _GATE_STATE_GLYPH[gate_state(token)]


def _worst_gate_state(*states: str | None) -> str:
    """Combine gate states, treating ``not-assessed`` as NEUTRAL/absorbing.

    An empty/unassessed side must defer to whichever OTHER side actually
    carries an assessment — never drag a real ``passed`` down to grey just
    because, say, the authored axis is empty while the COMPUTED value says
    ``passed``. Among states that DO carry a real assessment (``passed`` /
    ``passed-with-conditions`` / ``blocked`` / ``waived``), the worst one
    wins (§_GATE_STATE_RANK) — a blocked/at-risk state must still dominate a
    clean pass. Returns ``not-assessed`` only when every input is absent or
    itself ``not-assessed``."""
    assessed = [s for s in states if s and s != "not-assessed"]
    if not assessed:
        return "not-assessed"
    return max(assessed, key=lambda s: _GATE_STATE_RANK.get(s, 0))


# (key, gate number, gate name, backing axis) — order is lifecycle order,
# exactly §13's table.
_GATES: tuple[tuple[str, int, str, str], ...] = (
    ("plan",      1, "Plan",      "design_status"),
    ("execution", 2, "Execution", "simulation_status"),
    ("evidence",  3, "Evidence",  "evaluation_status"),
    ("quality",   4, "Quality",   "evaluation_status"),
    ("decision",  5, "Decision",  "gate_status"),
    ("release",   6, "Release",   "expert_review_status"),
)


def build_gate_ladder(spec: dict) -> list[dict]:
    """The ``status ▾`` gate ladder: the six axes relabeled as the six gates,
    each with its authored state plus — where a machine evaluator's value is
    ALREADY attached to *spec* by :func:`study_spec.load_study_detail_spec`
    (``derived_status`` from ``viva_superpowers.study_status.derive_status``;
    ``computed_gate_verdict`` from the persisted/rolled-up gate evaluator) — a
    computed state and a computed-vs-authored divergence flag.

    Plan and Release have NO computed source wired into *spec* today:
    ``study_verify`` (§13's named Plan evaluator) doesn't exist as an
    importable function in this codebase, and the report-linter's
    ``missing_question``/``undeclared_readouts`` checks are only fetched
    client-side (``GET /api/report-lint``) for the readiness panel, not
    attached to the render-time spec. The conclusion-card freeze (§13's named
    Release evaluator) isn't surfaced as a field yet either (that's task G8).
    Per the task's "don't invent a computed value" rule, both gates render
    authored-only.

    Returns a list of 6 dicts, lifecycle order, each with: ``key``, ``number``,
    ``name``, ``axis``, ``authored_value``, ``authored_state``,
    ``computed_value``, ``computed_state``, ``computed_source``, ``diverges``,
    and ``state`` (the worst of authored/computed, for a single dot/chip
    color that never hides a red gate behind a green one).
    """
    derived = spec.get("derived_status") or {}
    disagreements = {
        d.get("axis"): d for d in (spec.get("status_disagreements") or [])
        if isinstance(d, dict)
    }
    cgv = spec.get("computed_gate_verdict") or {}

    gates: list[dict] = []
    for key, number, name, axis in _GATES:
        authored_value = spec.get(axis)
        entry = {
            "key": key, "number": number, "name": name, "axis": axis,
            "authored_value": authored_value,
            "authored_state": gate_state(authored_value),
            "computed_value": None, "computed_state": None,
            "computed_source": None, "diverges": False,
        }
        if axis in derived and isinstance(derived.get(axis), dict):
            d = derived[axis]
            entry["computed_value"] = d.get("value")
            entry["computed_state"] = gate_state(d.get("value"))
            entry["computed_source"] = d.get("source") or "derived from execution state"
            entry["diverges"] = axis in disagreements
        elif axis == "gate_status" and cgv.get("result"):
            entry["computed_value"] = cgv.get("result")
            entry["computed_state"] = gate_state(cgv.get("result"))
            entry["computed_source"] = (
                "spine gate evaluator (study_verdict.roll_up_verdict / "
                "pipeline_gate.gate_evaluator)"
            )
            entry["diverges"] = bool(cgv.get("diverges_from_authored"))
        entry["state"] = _worst_gate_state(entry["authored_state"], entry["computed_state"])
        gates.append(entry)
    return gates


def act_gate_states(gates: list[dict]) -> dict[str, str]:
    """Roll the six per-gate states up into the five act-rail dot states fed
    to G1's ``.act-gate-dot[data-gate=...]`` hooks (§9.3: "six gates, five
    dots"). Per §13's Act column: Design←Plan(I); Evidence←Execution+
    Evidence(II); Assurance←Quality(III); Decision←Decision+Release(IV).
    'study' (the Overview act — §9.2 lists it as "(abstract)", outside the
    four numbered acts, so §13 assigns it no gate) is rendered here as the
    worst state across all six gates: the closest single-dot reading of
    "furthest gate passed" (§13.1) available without reimplementing the
    header pill's logic, which this task explicitly leaves alone.

    Each roll-up picks the worst state (§_GATE_STATE_RANK), never an average,
    so a dot never hides a blocked gate behind a passed one.
    """
    by_key = {g["key"]: g["state"] for g in gates}
    return {
        "study": _worst_gate_state(*by_key.values()),
        "design": by_key.get("plan", "not-assessed"),
        "evidence": _worst_gate_state(by_key.get("execution"), by_key.get("evidence")),
        "assurance": by_key.get("quality", "not-assessed"),
        "decision": _worst_gate_state(by_key.get("decision"), by_key.get("release")),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_study_detail_html(ws_root: Path, name: str, spec: dict, *, base_path: str = "") -> str:
    """Render study-detail.html via Jinja2.

    This is the implementation extracted from ``server._render_study_detail_html``.
    ``server.py`` provides a 2-arg shim ``_render_study_detail_html(name, spec)``
    that injects the module-level WORKSPACE as ``ws_root`` so ``publish.py``
    (which calls ``_render_study_detail_html(slug, spec)``) keeps working.

    ``base_path``: URL prefix for subpath hosting (e.g. ``/workbench`` behind a
    reverse proxy/ALB). Defaults to ``""`` (root hosting, unchanged behavior).
    The template's asset refs are normalized to ``/assets/<name>`` form and the
    live-server base-path shim is injected via ``lib.report``'s
    ``_normalize_asset_urls``/``_apply_live_base_path`` — the same helpers
    ``publish.py`` already uses for the static bundle.
    """
    import yaml
    import jinja2
    from vivarium_workbench.lib.investigations import effective_status
    from vivarium_workbench.lib.study_spec import study_dir

    spec = dict(spec)
    spec["runs"] = _enrich_runs_with_meta(study_dir(ws_root, name), spec.get("runs") or [])
    # Normalize implementation_requirements / gaps so the template iterates a
    # list of dicts — never a prose STRING.
    from vivarium_workbench.lib.spec_norm import normalize_requirements as _normalize_requirements
    if spec.get("implementation_requirements") is not None:
        spec["implementation_requirements"] = _normalize_requirements(
            spec.get("implementation_requirements"))
    if spec.get("gaps") is not None:
        spec["gaps"] = _normalize_requirements(spec.get("gaps"))
    # F1: compute a single headline status from the multi-axis fields.
    spec["_effective_status"] = effective_status(spec)
    # Deterministic study kind (biological/computational/theoretical), used by
    # the template to de-bias page chrome (Task 4). Never overwrites an
    # author's explicit `kind` — infer_study_kind() preserves it.
    from vivarium_workbench.lib.study_kind import infer_study_kind
    spec["kind"] = infer_study_kind(spec)
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )
    env.filters["fmt_ts"] = _jinja_fmt_ts
    env.filters["fmt_duration"] = _jinja_fmt_duration
    env.filters["markdown"] = _jinja_markdown
    env.filters["outcome_label"] = outcome_label
    env.filters["outcome_class"] = outcome_class
    env.filters["outcome_glyph"] = outcome_glyph
    env.filters["gate_state"] = gate_state
    env.filters["gate_state_glyph"] = gate_state_glyph
    tpl = env.get_template("study-detail.html")
    _hn = _humanize_study_name(name)
    # W15 — open epistemic debts, computed server-side via the deterministic
    # viva_superpowers collector. Defensive: degrade to no panel if not importable.
    epistemic_debts: list = []
    try:
        from viva_superpowers.needs_attention import open_epistemic_debts
        epistemic_debts = open_epistemic_debts(spec) or []
    except Exception:
        epistemic_debts = []
    # Composite-resolution lint: flag declared composite refs that don't resolve.
    unresolved_composites: list = []
    try:
        from vivarium_workbench.lib.composite_lookup import (
            known_composite_ids, unresolved_study_composite_refs,
        )
        unresolved_composites = unresolved_study_composite_refs(
            spec, known_composite_ids(ws_root)) or []
    except Exception:
        unresolved_composites = []
    # Fable G2: the six status axes relabeled as the six gates (§13), plus
    # the act-rail dot states they feed (G1's `.act-gate-dot[data-gate=...]`
    # hooks). Pure render-time derivation from fields load_study_detail_spec
    # already attached (derived_status, computed_gate_verdict,
    # status_disagreements) — never modifies study.yaml.
    gate_ladder = build_gate_ladder(spec)
    gate_states = act_gate_states(gate_ladder)
    html = tpl.render(study=spec, name=name,
                      display_name=spec.get("title") or _hn["title"],
                      name_chip=_hn["chip"],
                      epistemic_debts=epistemic_debts,
                      unresolved_composites=unresolved_composites,
                      gate_ladder=gate_ladder,
                      gate_states=gate_states,
                      base_path=base_path)
    from vivarium_workbench.lib.report import _apply_live_base_path, _normalize_asset_urls
    html = _normalize_asset_urls(html)
    return _apply_live_base_path(html, base_path)


def build_study_detail_page(ws_root: Path, slug: str, *, base_path: str = "") -> tuple[str, int]:
    """Full study-detail page builder: validate → load spec → render.

    Returns ``(html, status_code)`` where status_code is 200 on success
    or 404 for an invalid/unknown slug.  The 404 bodies are byte-identical
    to the legacy handler's ``_send_html`` responses.

    ``base_path``: forwarded to ``render_study_detail_html`` for subpath
    hosting; see its docstring.
    """
    from vivarium_workbench.lib.study_spec import load_study_detail_spec

    if not _SLUG_RE.match(slug):
        return "<h1>Not found</h1>", 404
    spec: Optional[dict] = load_study_detail_spec(ws_root, slug)
    if spec is None:
        return (
            f"<h1>Study not found</h1><p><code>{slug}</code> does not exist.</p>",
            404,
        )
    html = render_study_detail_html(ws_root, slug, spec, base_path=base_path)
    return html, 200
