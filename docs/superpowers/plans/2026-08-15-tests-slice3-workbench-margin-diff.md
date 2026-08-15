# Tests Slice 3 — Workbench margin + cross-iteration diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the study "Tests" panel show the agent-feedback signal — per-axis **`margin`** and a cross-iteration **diff** (fixed/broke/improved/regressed since the last run) — by (1) producing `test_diff.json` in the study run flush and (2) rendering margin + change badges in the report-card scorecard, all reusing the merged `viva_superpowers` helpers and keeping the `test_modular_tests_*` contract green.

**Architecture:** Three tasks — backend (`composite_flush` writes `run_dir/test_diff.json` via `viva_superpowers.diff_reports`), payload (`study_spec` surfaces `spec["test_diff"]` from the latest run), frontend (`study-detail.js::_renderRichReportCard` renders a margin bar + a diff change badge per axis). The `report_card_verdict/v2` axis extras (`margin/severity/knob/citation`) already pass through `report_card_urls[card].groups` verbatim (see study_spec:871-897) — no payload change needed for margin itself.

**Tech Stack:** Python 3.12 (FastAPI/lib), vanilla JS (no bundler), pytest. Re-locked onto viva-superpowers `cf6a451` (`diff_reports`/`build_report` available).

**Spec:** `docs/superpowers/specs/2026-08-15-tests-as-agent-feedback-design.md` (§8 diff, §9 flush, §10 workbench render)

## Global Constraints

- **Reuse `viva_superpowers` helpers** — `diff_reports(prev_cards, curr_cards)` (each `{card_name: verdict_doc}`) → `{schema:"test_diff/v1", per:[{card,group,id,change,margin_delta}], rollup:{...}}`. Do not reimplement diffing.
- **Best-effort flush** — every new flush stage is wrapped so a failure never raises into the run loop (matches the existing `run_flush` stages); first-run / bare-run → no diff, skip cleanly.
- **`test_modular_tests_*` must stay green** — keep `_fillReportCardModules`, the `report-card-verdict`/`report_card_urls`/`viz-embed` tokens, the `within_tol/drift/mismatch` tokens, and the `data-test-kind`/`data-card` row attributes. Every addition is additive.
- **On-disk / API shapes preserved** — `report_card_urls[card] = {url, verdict, groups, html_stub}`; `groups: None` must stay tolerated (a card verdict.json may be `{"overall": "..."}` with no groups).
- **Prev-run source is the prior `run_dir`** — there is no `history/` in the workbench; study-level `viz/report_card/*.verdict.json` are overwritten each run, so `prev_cards` MUST be read from `<ws>/.pbg/runs/<prev_run_id>/*.verdict.json` (prev run = `latest_run_row(runs.db)` taken BEFORE the current run finalizes, or the 2nd row of `runs_meta ORDER BY started_at DESC`).

---

### Task 1: Produce `run_dir/test_diff.json` in `composite_flush.run_flush`

**Files:**
- Modify: `vivarium_workbench/lib/composite_flush.py` (`run_flush` at :158, the verdict block :197-205; add a `_build_curr_cards`/`_load_prev_cards`/diff stage)
- Test: `tests/test_composite_flush_diff.py`

**Interfaces:**
- Consumes: `viva_superpowers.diff_reports`; the `vpaths` list already materialized at :197-200; run DB helpers (`composite_runs.list_runs` or `study_charts.latest_run_row`).
- Produces: `run_dir/test_diff.json` = `diff_reports(prev_cards, curr_cards)` output (or absent on first run). `run_flush`'s return dict gains `"has_diff": bool`.

**Implementation notes:**
- Build `curr_cards`: reuse the `name`-recovery already in `rollup_run_verdict` (:30-38) but load the FULL doc: `curr_cards[name] = json.loads(p.read_text())` for each `p` in `vpaths`.
- Identify prev run: on the run DB (`study_dir/runs.db` for studies, else `<ws>/.pbg/composite-runs.db`), take the run with the greatest `completed_at`/`started_at` that is NOT `run_id` (the current run may not be finalized yet, so `latest_run_row` on the pre-finalize DB IS the previous run; guard against it equaling `run_id`). Prev `run_dir = <ws>/.pbg/runs/<prev_run_id>`.
- Build `prev_cards` from `prev_run_dir.glob("**/*.verdict.json")` the same way; if the prev run_dir or its cards are missing → `prev_cards = {}` (diff yields all-`new`, still useful).
- `diff = diff_reports(prev_cards, curr_cards)`; `(run_dir/"test_diff.json").write_text(json.dumps(diff))`. Wrap in `try/except traceback.print_exc()`; set `has_diff`.

- [ ] **Step 1: Write the failing test** — construct two run_dirs with card `.verdict.json`s (run0: a card `mismatch`; run1: same card `within_tol`), a minimal runs.db with both rows, call `run_flush` (or a extracted `_write_test_diff(run_dir, prev_run_dir)` helper) for run1, assert `run_dir/test_diff.json` exists and its `per` entry for that card/axis has `change == "fixed"`.
- [ ] **Step 2: Run — FAIL** (`test_diff.json` not written / helper missing).
- [ ] **Step 3: Implement** the diff stage per notes (prefer extracting a pure `_write_test_diff(run_dir, prev_run_dir, *, diff_fn=diff_reports)` for testability, called from `run_flush`).
- [ ] **Step 4: Run — PASS.** Also run `tests/ -k "composite_flush or run_flush"` to confirm no regression.
- [ ] **Step 5: Commit** `feat(flush): write run_dir/test_diff.json (viva_superpowers.diff_reports vs prev run)`

---

### Task 2: Surface `spec["test_diff"]` in the study payload

**Files:**
- Modify: `vivarium_workbench/lib/study_spec.py` (after the `report_card_urls` block at :897)
- Test: `tests/test_study_spec_test_diff.py`

**Interfaces:**
- Consumes: `study_charts.latest_run_row(study_dir/"runs.db")`; the run's `test_diff.json`.
- Produces: `spec["test_diff"] = <parsed test_diff.json dict>` when the latest run wrote one, else absent. `report_card_urls[card].groups` axes already carry `margin/severity/knob/citation` (verify passthrough).

**Implementation notes:**
- After :897, resolve `latest = latest_run_row(study_dir(ws_root, name) / "runs.db")`; if present, read `<ws>/.pbg/runs/<latest["run_id"]>/test_diff.json`; on success `spec["test_diff"] = <dict>`. Best-effort (missing file / no runs → leave unset).

- [ ] **Step 1: Write the failing test** — a fixture study with a `runs.db` row + a `<ws>/.pbg/runs/<rid>/test_diff.json`; assert `load_study_detail_spec(...)["test_diff"]["schema"] == "test_diff/v1"`; and assert a `report_card_urls[card].groups[g].axes[0]` carries `margin` (passthrough) when the verdict.json is a `/v2` doc.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** the `test_diff` read after :897.
- [ ] **Step 4: Run — PASS.** Run `tests/testing/test_modular_tests_payload.py` + `test_modular_tests_e2e.py` — must stay green (test_diff/margin are additive).
- [ ] **Step 5: Commit** `feat(payload): surface spec[test_diff] + v2 axis margin passthrough`

---

### Task 3: Render margin bar + diff change badge in the scorecard

**Files:**
- Modify: `vivarium_workbench/static/study-detail.js` (`_renderRichReportCard` :1597-1659 — axis `<tr>` :1620-1630, header :1638-1640; thread `spec.test_diff`)
- Test: `tests/testing/test_modular_tests_render.py` or a focused `tests/test_scorecard_margin_render.py` (JS-string assertions, matching the repo's existing JS-scan test style)

**Interfaces:**
- Consumes: `window._study.report_card_urls[card].groups[g].axes[i]` (now with `margin/severity`); `window._study.test_diff.per[]` matched on `(card, group, id)`.
- Produces: each axis row gains a margin cell (a signed bar coloured by `_RC_GL[verdict]`) and, when a matching diff record exists, a small change badge (`fixed/broke/improved/regressed`) beside `_rcPill(a.verdict)`.

**Implementation notes:**
- Add a `_axisChange(card, group, id)` helper reading `window._study.test_diff` (guard undefined → null).
- In the `axes.map` row (:1620-1630): after the label + `_rcPill`, append a change badge when `_axisChange` is non-null; add a 4th `<td>` rendering the margin bar (`a.margin` scaled; sign → colour; `a.severity` may thin/grey a `directional`/`soft` bar). Add the matching `<th>Δ / Margin</th>` to the header (:1638-1640).
- Keep the existing 3 columns + all classes/attributes; the additions are purely appended.

- [ ] **Step 1: Write the failing test** — assert the `study-detail.js` source contains the new helper + markup tokens (e.g. `_axisChange`, a `margin`-bar class, and the four change labels), AND re-assert the `test_modular_tests_js.py` invariants (`_fillReportCardModules`, `report-card-verdict`, `report_card_urls`, `viz-embed`, `within_tol/drift/mismatch`).
- [ ] **Step 2: Run — FAIL** (new tokens absent).
- [ ] **Step 3: Implement** the render additions.
- [ ] **Step 4: Run — PASS.** Run the full `tests/testing/test_modular_tests_{payload,render,js,e2e}.py` suite — all green.
- [ ] **Step 5: Commit** `feat(ui): scorecard renders per-axis margin bar + since-last-run change badge`

---

## Self-Review

- §8 diff produced when a study runs → Task 1. §10 payload `test_diff` + margin passthrough → Task 2. §10 render margin/diff → Task 3.
- Prev-run sourcing (no `history/`; read prior `run_dir`) is honored in Task 1 per the map.
- `test_modular_tests_*` invariants are re-asserted in Tasks 2 + 3 (additive-only changes).
- **Deferred (not this slice):** wiring `TestReportStep` as a workflow-engine Step (the workbench flush is a non-workflow path; reusing `diff_reports` directly is the clean fit); `knob`/`citation` render (margin + diff first).

## Execution Handoff
Re-lock onto viva-superpowers `cf6a451` is done (committed). Run tasks via subagent-driven-development after `uv sync`ing the worktree venv onto the new lock.
