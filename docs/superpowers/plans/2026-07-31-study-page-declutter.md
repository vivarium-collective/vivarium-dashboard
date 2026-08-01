# Study Detail Page Declutter Implementation Plan

> ⚠️ **STALE — do not execute as-is.** The design evolved after this plan was
> written (see the spec, which is the live source of truth). Changes not yet
> reflected below: Simulations becomes a read-only runs table (no run controls);
> Tests merges Report Cards + Behavioral Tests into one concept; Readouts merges
> into Model and the Model reframe (Runs list + interventions) moves to
> **Increment 2**; explanatory paragraphs are stripped from every tab; pillars
> drop 8 → 7. This plan will be regenerated (Increment 1) once the tab walkthrough
> settles. Tasks 1–7, 10 are largely intact; Task 8/9/11/12 will change.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the study detail page lead with the science — collapse the seven-element header to three, remove the biology lean, enforce Question & Approach, and give each of the 8 tabs one job (including a saved/excluded Readouts view).

**Architecture:** The page is a server-rendered Jinja template (`templates/study-detail.html`) hydrated by `static/study-detail.js`, fed by `lib/study_spec.load_study_detail_spec` (also served at `GET /api/study/{slug}` as `window._study`) and `lib/study_page.build_study_detail_page`. Backend data changes go in `lib/` (unit-testable); presentation changes go in the template + JS (verified by fetching the rendered page via the `dashboard_client` fixture and asserting on HTML). No new endpoints except where noted; the readouts excluded-set reuses existing observable introspection.

**Tech Stack:** Python 3, FastAPI, Jinja2, vanilla JS (no bundler), pytest with a live-server `dashboard_client` fixture against `tests/_fixtures/` workspaces.

## Global Constraints

- **No new hard validation.** "Question & Approach" enforcement is a *soft* readiness gap (linter finding), never a save-blocking error.
- **Kind default is `computational`**, never silently `biological`. Values: `biological | computational | theoretical`.
- **8 pillars stay 8**; no pillar is renamed, removed, merged, or reordered.
- **Readouts is read-only** this iteration — no emitter write path.
- **Every governance fact renders once.** The question is the single allowed headline echo (header headline + Overview lead section).
- **Follow existing patterns:** new `lib/` logic is pure and unit-testable; route logic stays thin in `api/app.py`; mutating endpoints (none added here) would need `_csrf_ok()`.
- **Tests** run via `pytest`; the live-server fixture is `dashboard_client` (`tests/conftest.py`); set `VIVARIUM_WORKBENCH_DISABLE_CSRF=1` only if a test posts.
- Commit after every task with a `feat:`/`refactor:` message scoped to that task.

---

## Phase 1 — Backend data (pure, unit-testable)

### Task 1: Study `kind` field + inference

**Files:**
- Modify: `vivarium_workbench/lib/study_page.py` (the `build_study_detail_page` context builder, ~`:185`-`:220` where `_effective_status`/`epistemic_debts` are computed)
- Create: `vivarium_workbench/lib/study_kind.py`
- Test: `tests/test_study_kind.py`

**Interfaces:**
- Produces: `study_kind.infer_study_kind(spec: dict) -> str` returning one of `"biological" | "computational" | "theoretical"`. Consumed by the template as `study.kind` and by Task 4 (title tag) and Task 7 (verdict-track label).

**Rule:** if `spec.get("kind")` is an explicit valid value, use it. Else inspect `spec.get("findings")`: collect each finding's `kind`; if all present findings agree on one value, use it; if mixed or none, return `"computational"`. Never return `"biological"` unless explicitly authored or unanimously inferred.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_study_kind.py
from vivarium_workbench.lib.study_kind import infer_study_kind

def test_explicit_kind_wins():
    assert infer_study_kind({"kind": "theoretical", "findings": [{"kind": "computational"}]}) == "theoretical"

def test_infers_unanimous_finding_kind():
    assert infer_study_kind({"findings": [{"kind": "biological"}, {"kind": "biological"}]}) == "biological"

def test_mixed_findings_default_computational():
    assert infer_study_kind({"findings": [{"kind": "biological"}, {"kind": "computational"}]}) == "computational"

def test_no_findings_default_computational():
    assert infer_study_kind({}) == "computational"

def test_invalid_explicit_kind_falls_through_to_inference():
    assert infer_study_kind({"kind": "bogus", "findings": [{"kind": "theoretical"}]}) == "theoretical"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_study_kind.py -v`
Expected: FAIL (`ModuleNotFoundError: vivarium_workbench.lib.study_kind`)

- [ ] **Step 3: Write minimal implementation**

```python
# vivarium_workbench/lib/study_kind.py
"""Deterministic study `kind` resolution — biological | computational | theoretical.

Explicit `spec.kind` wins when valid; otherwise inferred from unanimous finding
kinds; otherwise defaults to `computational` (never silently `biological`).
"""
from __future__ import annotations

VALID_KINDS = ("biological", "computational", "theoretical")
DEFAULT_KIND = "computational"


def infer_study_kind(spec: dict) -> str:
    explicit = (spec.get("kind") or "").strip().lower()
    if explicit in VALID_KINDS:
        return explicit
    kinds = {
        (f.get("kind") or "").strip().lower()
        for f in (spec.get("findings") or [])
        if isinstance(f, dict) and (f.get("kind") or "").strip().lower() in VALID_KINDS
    }
    if len(kinds) == 1:
        return next(iter(kinds))
    return DEFAULT_KIND
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_study_kind.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Wire into the page context**

In `vivarium_workbench/lib/study_page.py`, where the `spec`/`study` context dict is assembled for the template (near the `_effective_status` computation, ~`:185`), add:

```python
from vivarium_workbench.lib.study_kind import infer_study_kind
# ... where the study context is built:
spec["kind"] = infer_study_kind(spec)
```

(Set it on the same dict passed to the template as `study=` so `{{ study.kind }}` resolves. Do not overwrite an author's explicit value — `infer_study_kind` already preserves it.)

- [ ] **Step 6: Add a render assertion + commit**

```python
# tests/test_study_detail_render.py  (create if absent)
def test_study_page_exposes_kind(dashboard_client):
    slug = dashboard_client.any_study_slug()  # helper: first study in fixture ws
    html = dashboard_client.get(f"/studies/{slug}").text
    assert 'data-study-kind=' in html  # tag emitted in Task 4
```

Mark this assertion `@pytest.mark.xfail(reason="tag added in Task 4")` for now, then:

```bash
git add vivarium_workbench/lib/study_kind.py vivarium_workbench/lib/study_page.py tests/test_study_kind.py tests/test_study_detail_render.py
git commit -m "feat: study kind inference (biological/computational/theoretical), default computational"
```

> If `dashboard_client` has no `any_study_slug` helper, hardcode a slug that exists in the fixture workspace under `tests/_fixtures/` (grep `tests/_fixtures -name study.yaml`).

---

### Task 2: `missing_question` readiness gap (enforce Question & Approach)

**Files:**
- Modify: `vivarium_workbench/lib/report_views.py` (`build_report_lint` at `:332`; add a sibling to `_readout_emit_plan_findings`)
- Test: `tests/test_report_lint_question.py`

**Interfaces:**
- Produces: `report_views._question_approach_findings(ws_root: Path) -> list[dict]`, each finding shaped like the existing appended findings: `{"study", "check", "severity", "message", "field_path"}`. `check == "missing_question"`. Consumed by the header gaps link (already renders any `/api/report-lint` finding for the slug).

**Rule:** for each study, if the spec has no non-empty question (checking `purpose.question` then legacy `question`), emit one `missing_question` finding at severity `warning`. Deterministic, tolerant of unreadable specs (skip them).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_lint_question.py
from pathlib import Path
from vivarium_workbench.lib.report_views import _question_approach_findings

def test_flags_study_without_question(tmp_path):
    ws = tmp_path
    sdir = ws / "studies" / "no-q"; sdir.mkdir(parents=True)
    (sdir / "study.yaml").write_text("name: no-q\ntitle: No question here\n")
    checks = [f["check"] for f in _question_approach_findings(ws)]
    assert "missing_question" in checks

def test_no_flag_when_question_present(tmp_path):
    ws = tmp_path
    sdir = ws / "studies" / "has-q"; sdir.mkdir(parents=True)
    (sdir / "study.yaml").write_text("name: has-q\npurpose:\n  question: Does X match Y?\n")
    checks = [f["check"] for f in _question_approach_findings(ws)]
    assert "missing_question" not in checks
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report_lint_question.py -v`
Expected: FAIL (`ImportError: cannot import name '_question_approach_findings'`)

- [ ] **Step 3: Write minimal implementation**

Add to `report_views.py` (mirror how `_readout_emit_plan_findings` iterates studies — reuse `workspace_paths` to resolve `studies/` and any existing study-iteration helper in that module rather than hardcoding the dir):

```python
def _question_approach_findings(ws_root: Path) -> list[dict]:
    """Deterministic 'missing_question' readiness gaps — one per study whose
    spec has no non-empty question (purpose.question or legacy question)."""
    from vivarium_workbench.lib import workspace_paths
    import yaml
    out: list[dict] = []
    studies_dir = workspace_paths.studies_dir(ws_root)
    if not studies_dir.is_dir():
        return out
    for sdir in sorted(p for p in studies_dir.iterdir() if p.is_dir()):
        spec_path = sdir / "study.yaml"
        if not spec_path.is_file():
            continue
        try:
            spec = yaml.safe_load(spec_path.read_text()) or {}
        except Exception:  # noqa: BLE001 — tolerant, skip unreadable specs
            continue
        q = ((spec.get("purpose") or {}).get("question") or spec.get("question") or "").strip()
        if not q:
            out.append({
                "study": spec.get("name") or sdir.name,
                "check": "missing_question",
                "severity": "warning",
                "message": "Study has no question — add a Question & Approach.",
                "field_path": "purpose.question",
            })
    return out
```

> Confirm the exact `workspace_paths` accessor name for the studies dir (grep `def .*studies` in `lib/workspace_paths.py`); use it instead of `ws_root / "studies"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report_lint_question.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Append to the linter aggregation**

In `build_report_lint`, after the existing `findings.extend(_readout_emit_plan_findings(ws_root))` (`:361`):

```python
    findings.extend(_question_approach_findings(ws_root))
```

- [ ] **Step 6: Commit**

```bash
git add vivarium_workbench/lib/report_views.py tests/test_report_lint_question.py
git commit -m "feat: missing_question readiness gap enforcing Question & Approach"
```

---

### Task 3: Readouts excluded-set (available − emitted)

**Files:**
- Modify: `vivarium_workbench/lib/readouts_views.py` (`build_study_readouts` at `:150`; `_merge_readouts` at `:79`)
- Test: `tests/test_readouts_excluded.py`

**Interfaces:**
- Produces: `build_study_readouts` payload gains an `excluded` list alongside `rows`: `{"composite": ref, "rows": [...], "excluded": [{"store_path", "name"}], ...}`. Each `rows` entry keeps its `emit_status`. `excluded` = observable-surface leaves NOT in the emit plan. Consumed by Task 12 (frontend ○ rows).

**Investigation first — this is the one task whose data source must be confirmed before coding:**

- [ ] **Step 0: Confirm the two surfaces differ**

`readouts_views._available_observables_for_ref(ws_root, ref)` (`:32`) returns `{leaves, catalogs}` and `_merge_readouts` currently tags every leaf `emit_status:"emitted"`. Determine whether that leaf set is the *emit plan* (selected) or the *full observable surface* (all available). Compare against `observables_views.build_observables(ws_root, ref)` (`:238`), whose `leaves` are the `available_observables` introspection.

Run against a fixture study's composite ref:
```bash
python -c "
from pathlib import Path
from vivarium_workbench.lib import readouts_views as R, observables_views as O
ws = Path('tests/_fixtures/<fixture-ws>'); ref='<composite-ref>'
print('readouts leaves:', len(R._available_observables_for_ref(ws, ref).get('leaves', [])))
print('observables leaves:', len(O.build_observables(ws, ref)[0].get('leaves', [])))
"
```

- If the two leaf sets are **equal**, the emitter emits everything available → `excluded` is genuinely empty for that study, and the surface source for "available" is the same call. Document this in the payload with `"excluded": []` and an `"emit_is_total": true` flag; the frontend then shows "all observables are saved."
- If **available ⊃ emitted**, `excluded = available_leaves − emit_plan_leaves` (set difference on lineage-stripped paths via the existing `_strip_lineage`).

Record the finding in the commit message. The steps below assume the general case (available ⊇ emitted) and degrade correctly when they're equal.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_readouts_excluded.py
from vivarium_workbench.lib.readouts_views import _split_saved_excluded

def test_excluded_is_available_minus_emitted():
    emitted = ["a.b.x", "a.b.y"]
    available = ["a.b.x", "a.b.y", "a.b.z", "a.c.w"]
    saved, excluded = _split_saved_excluded(emitted, available)
    assert {r["store_path"] for r in saved} == {"a.b.x", "a.b.y"}
    assert {r["store_path"] for r in excluded} == {"a.b.z", "a.c.w"}

def test_excluded_empty_when_emit_is_total():
    leaves = ["a.b.x", "a.b.y"]
    saved, excluded = _split_saved_excluded(leaves, leaves)
    assert excluded == []
    assert len(saved) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_readouts_excluded.py -v`
Expected: FAIL (`ImportError: cannot import name '_split_saved_excluded'`)

- [ ] **Step 3: Write minimal implementation**

```python
# in readouts_views.py
def _split_saved_excluded(emitted_leaves, available_leaves):
    """Partition the observable surface into saved (emitted) and excluded rows.

    Both args are lists of dotted store paths. Comparison is on lineage-stripped
    keys so `_strip_lineage`-equivalent paths match. Returns (saved, excluded)
    where each is a list of {store_path, name} dicts.
    """
    emitted_keys = {_strip_lineage(l) for l in emitted_leaves}
    saved = [{"store_path": l, "name": _short_name(l)} for l in sorted(emitted_leaves)]
    excluded = [
        {"store_path": l, "name": _short_name(l)}
        for l in sorted(available_leaves)
        if _strip_lineage(l) not in emitted_keys
    ]
    return saved, excluded
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_readouts_excluded.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Surface `excluded` in the payload**

In `build_study_readouts`, after `rows` are built, compute the available surface (per Step 0's finding — either the same `_available_observables_for_ref` call if it is the full surface, or `observables_views.build_observables`) and add `payload["excluded"] = excluded`. Keep `rows` unchanged so existing consumers don't break. Guard with try/except so a build failure leaves `excluded: []` (degrade, never 500).

- [ ] **Step 6: Commit**

```bash
git add vivarium_workbench/lib/readouts_views.py tests/test_readouts_excluded.py
git commit -m "feat: readouts excluded-set (available minus emitted observables)"
```

---

## Phase 2 — Header

### Task 4: Header restructure — 7 elements → 3

**Files:**
- Modify: `vivarium_workbench/templates/study-detail.html` header block (`:14`-`:48`), status stepper (`:76`-`:142`), spine placeholder (`:174`), readiness placeholder (`:74`)
- Test: `tests/test_study_detail_render.py`

**Interfaces:**
- Consumes: `study.kind` (Task 1), `study.gate_status` / `study._effective_status`, `study.purpose.question` (or legacy `question`).
- Produces: header emits `data-study-kind="<kind>"` (satisfies Task 1's xfail assertion — flip it to a normal assert here) and renders the question in an element with id `study-question-headline` above `<nav class="study-tabs">`.

Layout target (two rows + promoted question):
```
<title> [kind tag]                              [Reproduce] [Run spec]
● <status>    ⚠ N gaps  ·······  status ▾
Q  <question>
```

- [ ] **Step 1: Add the kind tag beside the title**

In the `<h1 class="study-title">` (`:16`), after the `study-name` span and before the phase pill, add:
```html
<span class="study-kind-tag study-kind-{{ study.kind }}" data-study-kind="{{ study.kind }}" title="Study kind">{{ study.kind }}</span>
```

- [ ] **Step 2: Collapse the status line & move the stepper behind `status ▾`**

Wrap the existing six-axis `<details class="status-detail-panel">` (`:120`-`:141`) so it is the `status ▾` disclosure: keep it as-is (it is already a `<details>`), but move it up next to the status pill row and change its `<summary>` label text to `status`. Keep the divergence chip (`:39`-`:42`) *inside* this disclosure rather than in the title row (cut it from the `<h1>`).

- [ ] **Step 3: Delete the "Spine at a glance" placeholder**

Remove the `<div id="spine-summary">` at `:174` (and its CSS at `:160`-`:173`). Its JS populator is removed in Task 5.

- [ ] **Step 4: Promote the question into the header**

Directly above `<nav class="study-tabs">` (`:176`), add:
```html
{% set _q = (study.purpose.question if study.purpose else none) or study.question %}
{% if _q %}<p id="study-question-headline" class="study-question-headline"><span class="q-glyph">Q</span> {{ _q }}</p>{% endif %}
```

- [ ] **Step 5: Add CSS** for `.study-kind-tag`, `.study-question-headline`, and the tightened status row (small, quiet; kind tag pill-styled; question in a readable serif-ish lead). Put it with the existing header CSS in the template `<style>` block.

- [ ] **Step 6: Render assertions**

```python
def test_header_has_kind_tag_and_question_and_no_spine(dashboard_client):
    slug = "<fixture-study-with-question>"
    html = dashboard_client.get(f"/studies/{slug}").text
    assert 'data-study-kind=' in html
    assert 'id="study-question-headline"' in html
    assert 'id="spine-summary"' not in html
```
Flip Task 1's xfail assertion to a plain assert. Run: `pytest tests/test_study_detail_render.py -v` → PASS.

- [ ] **Step 7: Commit**

```bash
git add vivarium_workbench/templates/study-detail.html tests/test_study_detail_render.py
git commit -m "feat: study header 7->3 (kind tag, promoted question, drop spine table)"
```

---

### Task 5: Readiness → inline link; remove spine-summary JS; single lint consumer

**Files:**
- Modify: `vivarium_workbench/static/study-detail.js` — `_renderSpineSummary` (`:1989`-`:2130`), `_renderReadinessPanel` (`:2218`-`:2273`), and their call sites
- Test: extend `tests/test_study_detail_render.py` (assert the readiness element is an inline link, not a banner block)

**Interfaces:**
- Consumes: `/api/report-lint` (memoized `_reportLint` at `:1975`) — now exactly one consumer.
- Produces: an inline `⚠ N readiness gaps` / `✓ ready` element rendered into the header status row (id `readiness-inline`), click-to-expand.

- [ ] **Step 1:** Delete `_renderSpineSummary` and its call site (the `#spine-summary` element is already gone from the template in Task 4). Remove any dangling reference so no console error on load.

- [ ] **Step 2:** Rewrite `_renderReadinessPanel` to render an inline link instead of the yellow banner: same `_reportLint` fetch + slug filter + severity bucketing, but output `⚠ N readiness gaps` (or `✓ ready` at zero) as a compact clickable `<a>`/`<button>` that toggles a details list below the status row. Keep the gap breakdown (`1× incomplete_summaries · …`) inside the expanded state only.

- [ ] **Step 3:** Point it at a header mount. If the template's `#readiness-panel` (`:74`) is repositioned into the status row in Task 4, reuse that id; otherwise add `id="readiness-inline"` in the status row and target it. One mount only.

- [ ] **Step 4: Render assertion**

```python
def test_readiness_is_inline_not_banner(dashboard_client):
    slug = "<fixture-study>"
    html = dashboard_client.get(f"/studies/{slug}").text
    # the banner class is gone; the inline mount exists
    assert 'readiness-panel' in html or 'readiness-inline' in html
```
(The visible ⚠/✓ text is JS-rendered post-load; assert the mount + that no `spine-summary` remains. Manual check: load the page, confirm one quiet readiness link, no yellow banner, no spine table.)

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/static/study-detail.js tests/test_study_detail_render.py
git commit -m "refactor: readiness as inline link, drop spine-at-a-glance (single report-lint consumer)"
```

---

## Phase 3 — Tabs

### Task 6: Overview — drop the sloppy biology section, fold authored summary into Question & Approach

**Files:**
- Modify: `vivarium_workbench/templates/study-detail.html` — biology block (`:373`-`:392`), counts strip (`:679`), Question & Approach section (`:340`-`:371`)
- Test: `tests/test_study_detail_render.py`

**Design intent (from the 11:27 screenshot):** "Question & Approach" is the
polished, structured lead — three color-coded cards: **Question** (blue),
**Hypothesis / Expected outcome** (green), **Mechanism / Model change**
(yellow). It already answers "what this study is about." The separate
"BIOLOGY — WHAT THIS STUDY IS ABOUT" block directly below it is redundant *and*
visually sloppy (an unstyled derived-from-findings restatement). **Delete the
biology section entirely.** Preserve an authored `biological_summary` by folding
it in as a **matching fourth card** in the Q&A group ("Summary", neutral slate
styling) — never as its own heading.

- [ ] **Step 1:** **Delete the entire biology block** (`:373`-`:392`) — both the
  authored-override branch and the `{% else %}…biology-derived-preview…` derived
  restatement. No "Biology" or "What this study is about" heading remains.

- [ ] **Step 2:** In the "Question & Approach" section (`:340`-`:371`), after the
  Mechanism/Model-change card, add a fourth card that renders **only when
  `study.biological_summary` is authored**, matching the existing card styling
  (same `.narrative-*` / left-border-callout classes the Q/Hypothesis/Mechanism
  cards use — read `:340`-`:371` to copy the exact class + inline-style pattern of
  a card, then swap the label/colour to a neutral slate):

```html
{% if study.biological_summary %}
<div class="qa-card qa-card-summary">  {# match the Q/Hypothesis/Mechanism card markup at :340-:371 #}
  <strong>Summary.</strong> {{ study.biological_summary }}
</div>
{% endif %}
```

  (Use the real card wrapper markup from `:340`-`:371`, not this schematic — the
  point is one more card in the same visual family, slate/grey border, shown only
  when authored. The `data-narrative-path="biological_summary"` editor affordance
  may be kept inside this card if inline editing is desired, styled to match.)

- [ ] **Step 3:** Delete the `<div class="study-counts-strip">` block at `:679` (noise).

- [ ] **Step 4: Render assertions**

```python
def test_overview_no_biology_lean(dashboard_client):
    slug = "<computational-fixture-study>"
    html = dashboard_client.get(f"/studies/{slug}").text
    assert "Biology — what this study is about" not in html
    assert "Derived from findings" not in html
    assert "study-counts-strip" not in html
```
Run → PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/templates/study-detail.html tests/test_study_detail_render.py
git commit -m "refactor: overview de-biology (neutral heading, drop derived preview + counts strip)"
```

---

### Task 7: Decide — kind-aware verdict-track label

**Files:**
- Modify: `vivarium_workbench/templates/study-detail.html` — verdict track label (`:1478`) and basis label (`:1485`)

- [ ] **Step 1:** Make the "Biological validation" / "Biological basis" labels kind-aware. The `data-verdict-track="biological_validation"` and `data-narrative-path="conclusion_verdicts.biological_validation.basis"` attributes **stay** (data model unchanged); only the visible label text changes:

```html
{% set _domain_label = "Biological" if study.kind == "biological" else "Domain" %}
<span class="narrative-label">{{ _domain_label }} validation</span>
...
<span class="narrative-label">{{ _domain_label }} basis</span>
```

Apply the same to the explanatory text at `:1457`/`:1519` if it hardcodes "biological" ("does the model reproduce known **biology**?" → "does the model reproduce the known **domain** behavior?" when not biological). Keep it "biological" for `study.kind == "biological"`.

- [ ] **Step 2: Render assertion**

```python
def test_decide_label_neutral_for_computational(dashboard_client):
    slug = "<computational-fixture-study>"
    html = dashboard_client.get(f"/studies/{slug}").text
    assert "Domain validation" in html
```
Run → PASS.

- [ ] **Step 3: Commit**

```bash
git add vivarium_workbench/templates/study-detail.html tests/test_study_detail_render.py
git commit -m "refactor: decide verdict-track label is kind-aware (Domain vs Biological)"
```

---

### Task 8: Model — implementation requirements → provenance; hide empty model-change

**Files:**
- Modify: `vivarium_workbench/templates/study-detail.html` — implementation requirements (`:917`-`:949`), model change (`:878`-`:915`), Plan & provenance details (`:508`-`:698`)

- [ ] **Step 1:** Read `:878`-`:949` in full first. Move the "Implementation requirements" section (`:917`-`:949`) out of the Model tab body and into the collapsed "Plan & provenance" `<details>` in Overview (`:508`-`:698`) — cut the markup block and paste it inside that details element. It is a checklist, not the model definition.

- [ ] **Step 2:** Wrap the "Model change" section (`:878`-`:915`) in `{% if study.model_change and (study.model_change.what or study.model_change.why) %}…{% endif %}` so it is hidden when empty.

- [ ] **Step 3: Render assertion**

```python
def test_model_tab_lean(dashboard_client):
    slug = "<fixture-study-no-model-change>"
    html = dashboard_client.get(f"/studies/{slug}").text
    # implementation requirements no longer in the Model (compose) panel body
    # (assert on a stable heading string you moved; adjust to the real text)
    assert html.count("Implementation requirements") <= 1
```
Run → PASS. Manual: open Model tab, confirm it leads with the composite card + conditions; open Overview → Plan & provenance, confirm the requirements list is there.

- [ ] **Step 4: Commit**

```bash
git add vivarium_workbench/templates/study-detail.html tests/test_study_detail_render.py
git commit -m "refactor: model tab leads with composite; impl-reqs to provenance; hide empty model-change"
```

---

### Task 9: Simulations — remove duplicate Reproduce card, consolidate run controls

**Files:**
- Modify: `vivarium_workbench/templates/study-detail.html` — reproduce card `#reproduce-card` (`:977`-`:979`), Configure-&-Run mount (`:1192`), remote-run form (`:1193`-`:1206`), sweep summary (`:996`-`:1190`)
- Modify: `vivarium_workbench/static/study-detail.js` — `_renderReproduceCard` (`:61`-`:84`) call site

- [ ] **Step 1:** Read `:975`-`:1208` in full first. Remove the in-tab `#reproduce-card` (`:977`-`:979`) and its `_renderReproduceCard` call — the header already has ↻ Reproduce (Task 4 keeps it). Keep the CLI/reproduce *command text* only if it is not otherwise reachable; if the header button covers it, delete the card.

- [ ] **Step 2:** Group the three run controls (Configure-&-Run mount `:1192`, remote-run form `:1193`-`:1206`, and the Pass-B sweep summary header) under one `<section class="study-run-controls">` with a single "Run" heading, placed *below* the `#study-sim-table` runs table so the table (what actually ran) leads.

- [ ] **Step 3: Render assertion**

```python
def test_simulations_single_run_panel(dashboard_client):
    slug = "<fixture-study>"
    html = dashboard_client.get(f"/studies/{slug}").text
    assert 'id="reproduce-card"' not in html
    assert 'study-run-controls' in html
```
Run → PASS. Manual: open Simulations, confirm runs table on top, one "Run" panel below, no duplicate Reproduce.

- [ ] **Step 4: Commit**

```bash
git add vivarium_workbench/templates/study-detail.html vivarium_workbench/static/study-detail.js tests/test_study_detail_render.py
git commit -m "refactor: simulations tab — runs table leads, one Run panel, drop duplicate reproduce card"
```

---

### Task 10: Visualizations — merge three mounts into one gallery

**Files:**
- Modify: `vivarium_workbench/templates/study-detail.html` — viz sections (`:1244`-`:1280`)
- Modify: `vivarium_workbench/static/study-detail.js` — `_loadCharts`/`_loadNativeGallery` (`:492`-`:540`, `:296`-`:330`)

- [ ] **Step 1:** Unify the three separate `<h4>`-headed sections — "Baseline analysis gallery" (`#native-gallery-panel`), "Embedded visualizations" (iframes), and "Latest-run charts" (`#viz-charts-panel`) — into one `<section class="study-figures">` with a single "Figures" heading. Keep all three mount ids (the loaders target them) but drop the three separate section chrome/headings; render them as one continuous gallery. The embedded-iframe loop (`:1255`-`:1275`) stays but under the unified heading.

- [ ] **Step 2:** No loader logic change needed (same mount ids); just confirm `_loadCharts`/`_loadNativeGallery` still fire on the `visualize` tab.

- [ ] **Step 3: Render assertion**

```python
def test_visualizations_single_gallery(dashboard_client):
    slug = "<fixture-study>"
    html = dashboard_client.get(f"/studies/{slug}").text
    assert 'study-figures' in html
    # the three separate section headings collapsed to one
    assert html.count('native-gallery-section') == 0
```
Run → PASS. Manual: open Visualizations, confirm one gallery flow.

- [ ] **Step 4: Commit**

```bash
git add vivarium_workbench/templates/study-detail.html vivarium_workbench/static/study-detail.js tests/test_study_detail_render.py
git commit -m "refactor: visualizations — one unified figure gallery"
```

---

### Task 11: Tests — lead with the gate result

**Files:**
- Modify: `vivarium_workbench/templates/study-detail.html` — behavioral-tests panel (`:1323`-`:1423`), report-cards mount (`:1282`-`:1293`)
- Modify: `vivarium_workbench/static/study-detail.js` — `loadTestsTab` (`:1425`+), `_fillReportCardsTab` (`:1292`)

- [ ] **Step 1:** Read `:1282`-`:1423` and `study-detail.js:1425`-`1470` first. Add a **gate-result summary strip** at the top of the Tests pillar (above the Report Cards / Behavioral Tests sub-nav): which report cards / behavioral tests gate the verdict and their pass/fail, sourced from `spec.outcome_rollup` + `spec.latest_outcomes` (already read by `loadTestsTab`). Render as `N/M gates passed` with a per-gate ✓/✗ list.

- [ ] **Step 2:** Frame the pillar as the study's audit: a one-line caption under the heading ("Audit: does this study pass its own bar — report cards + behavioral gates"). Keep both sub-tabs intact.

- [ ] **Step 3: Render/behavior assertion**

```python
def test_tests_tab_leads_with_gate_summary(dashboard_client):
    slug = "<fixture-study-with-outcomes>"
    html = dashboard_client.get(f"/studies/{slug}").text
    assert 'tests-gate-summary' in html  # the new strip's container id/class
```
(The pass/fail counts are JS-rendered; assert the container exists in markup. Manual: open Tests, confirm the gate summary is on top.)

- [ ] **Step 4: Commit**

```bash
git add vivarium_workbench/templates/study-detail.html vivarium_workbench/static/study-detail.js tests/test_study_detail_render.py
git commit -m "feat: tests tab leads with gate/audit summary"
```

---

### Task 12: Readouts — saved/excluded browsable tree (read-only)

**Files:**
- Modify: `vivarium_workbench/templates/study-detail.html` — readouts panel (`:1210`-`:1236`)
- Modify: `vivarium_workbench/static/study-detail.js` — `_loadReadouts` (`:98`-`:118`), `_renderReadoutsTable` (`:251`)
- Test: `tests/test_readouts_excluded.py` (extend with an API-shape assertion)

**Interfaces:**
- Consumes: `GET /api/study-readouts?study=<slug>` payload now carrying `rows` (saved) + `excluded` (Task 3).

- [ ] **Step 1:** Add a "Selected emitter" header line to the readouts panel. Source the emitter name/type from the study spec's emitter config (grep how the composite/emitter is named in `study_spec` / the readouts payload; if not already present, add `emitter` to the `build_study_readouts` payload in Task 3 — a small addition, note it there).

- [ ] **Step 2:** Rewrite `_renderReadoutsTable` to render a **collapsible tree grouped by store-path prefix**, not a flat table. Each leaf row shows a glyph: `●` for saved (`rows`), `○` for excluded (`excluded`), plus name/units. Group by the first 1–2 path segments into `<details>` groups.

- [ ] **Step 3:** Add a search/filter `<input>` above the tree that filters visible leaves by path or name (client-side, on `input`). No write path — rows are display-only.

- [ ] **Step 4: API-shape assertion**

```python
def test_study_readouts_api_has_excluded(dashboard_client):
    slug = "<fixture-study>"
    data = dashboard_client.get(f"/api/study-readouts?study={slug}").json()
    assert "excluded" in data
    assert isinstance(data["excluded"], list)
```
Run → PASS. Manual: open Readouts, confirm selected emitter line, ●saved + ○excluded leaves in a collapsible searchable tree.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/templates/study-detail.html vivarium_workbench/static/study-detail.js tests/test_readouts_excluded.py
git commit -m "feat: readouts saved/excluded browsable tree with emitter + search (read-only)"
```

---

## Final verification

- [ ] Run the full suite: `pytest -q`. Expected: green (fix any fixture-slug placeholders you filled).
- [ ] Serve a real workspace and eyeball the study page end-to-end:
  ```bash
  vivarium-workbench serve --workspace <a workspace with studies> --port 8799
  ```
  Confirm against the success criteria in the spec: header shows status/readiness/verdict once each; no yellow banner, no spine table; question at top; a computational study shows no "Biology" heading and a `kind` tag; Overview "What this study is about" only when authored; Readouts shows emitter + ●/○ tree; Tests leads with the gate result.
- [ ] `git log --oneline da4736f..HEAD` shows only your task commits.

## Self-review notes (author)

- **Spec coverage:** header dedup (T4/T5), kind + de-biology (T1/T6/T7), Question & Approach enforcement (T2), each tab's one job (T6–T12), Readouts saved/excluded read-only (T3/T12). All spec sections map to a task.
- **Known implementer to-dos flagged inline (not placeholders — decisions the code confirms):** exact `workspace_paths` studies-dir accessor (T2), whether emit-plan == available surface for the target workspace (T3 Step 0), real fixture study slugs (T1 Step 6). Each has a concrete command to resolve it.
- **Type consistency:** `infer_study_kind` → `study.kind` used in T4/T7; `_split_saved_excluded` → `excluded` payload key used in T12; `_question_approach_findings` → `check:"missing_question"` rendered by the existing gaps link.
