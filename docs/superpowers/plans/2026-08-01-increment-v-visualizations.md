# Increment V — Visualizations: honest, enforced, richer

> **For agentic workers:** subagent-driven, per-task review, ONE editing subagent at a time in the shared worktree.
> **Depends on:** Increment A + G + C + the act-rail fix (all on `feat/study-design-fable-a`, tip `c680937`). Build V off that tip.
> **Design source:** `.superpowers/sdd/fable-increment-a/viz-subsystem-map.md` (the subsystem map — cite it), Fable §4.5.

**Goal:** Make the Visualizations tab (1) **honest** (no mis-named/stale empty-state), (2) **enforced** — every study is pushed to declare and produce a *qualifying* visualization via a readiness gap feeding Gate 3 · Evidence, and (3) **richer & prettier** — one clean run-captioned gallery that accepts interactive figures (Plotly, GIF, three.js), so studies rarely show an empty, boring tab.

**Tech:** Jinja `templates/study-detail.html`, vanilla JS `static/study-detail.js`, `static/style.css`; backend `lib/study_charts.py`, `lib/study_spec.py`, `lib/report_views.py`, `lib/emitters.py`, `lib/study_page.py`; FastAPI routes in `api/app.py`. pytest via the `dashboard_client` FACTORY fixture.

## Global constraints
- **In-repo only for V1–V6.** The formal schema field (`required`/`kind`) lives in the sibling `viva-template` repo — **V7 is deferred/cross-repo**; V1–V6 enforce by reading the EXISTING `visualizations:` array + discovered figures + the native gallery, so no schema change is needed to ship enforcement.
- **`db_exists` semantics are subtle** (map §1/risks): `runs.db` is created for run *metadata* regardless of emitter, so "has trajectory data" must be derived from the emitter broker (`emitters.default_emitter`/`chart_source`), not bare file existence. Get this wrong and the message flips to the opposite lie.
- **The quality bar must be explicit** (map risk): a study *passes* the viz gate iff it has **≥1 run-linked figure** (any of the 3 sources keyed to a real `run_id`) **AND ≥1 interactive figure** (Plotly HTML embed / `.gif` / three.js — NOT only a static SVG/PNG). Encode this as one shared helper so the gallery, the readiness gap, and the gate all agree.
- **Enforcement is a readiness gap + a computed gate state (SOFT), not a hard block** — same machinery as the existing "N readiness gaps"; a study is never prevented from running, it's shown the gap.
- Absent ≠ empty; reuse existing helpers (`outcome_label`, `_gotoStudyTab`, the emitter broker) — don't fork. New CSS classes fine (folded into the final CSS sweep). Test env (ONLY): `/Users/eranagmon/code/vivarium-workbench--study-declutter/.venv/bin/python -m pytest <file> -v`; `dashboard_client(ws)->client`; `node --check` after JS edits.
- **Concurrency:** ONE editing subagent at a time. Reviewers read-only. NEVER `git stash`/`reset`/`checkout`/`clean`/`restore`; FOREIGN `stash@{0}` untouched — read other revs with `git show <rev>:<path>`. Stage only specific paths (`git add <path>`), NEVER `git add -A` (unrelated modified fixtures in tree). Trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Task V1: Honest empty-state (the `runs.db`/`jsonl` fix)
**Kind:** T (frontend) + B (small). **Map §1, §6(a)/(b).**
- Frontend: replace the `db_exists`-branch string (`static/study-detail.js` ~599–601, `"No runs.db and no static charts under …/charts/"`) with a **format-agnostic** line: **"No run data or figures yet for this study."** (Do NOT substitute `runs.jsonl` — it holds no trajectory data; naming it would just move the lie.)
- Backend: fix `build_study_charts_payload`'s `db_exists` (`lib/study_charts.py` ~1541, computed ~1481) so it reflects the **emitter broker's actual store** (`emitters.default_emitter(spec, runs_db)` → `emitters.chart_source(...)` — zarr/sqlite/parquet), not a bare `runs_db.exists()`. Expose enough for the message to (optionally) distinguish "no run ever happened" from "data lives in a store no charts were rendered from." Keep the field name/back-compat; don't break existing consumers.
- Test: a study on the **xarray/zarr** emitter with run data no longer reports the sqlite-only "no data" state; a truly empty study shows the new format-agnostic line; existing sqlite studies unchanged.

## Task V2: One run-captioned gallery (Fable §4.5)
**Kind:** T (frontend + template + css). **Map §2, §6(b).** (The union empty-state is already shipped — do NOT redo it.)
- Collapse the three figure sources (native srcdoc iframes, embedded HTML iframes, inline SVG/PNG/GIF charts) into **one flowing gallery of a single `.figure-card` style**. Cut: the `Figures` h2, the per-source *visible* groupings, and per-source chrome (embed header-bar/border, native bold label, `.chart-card` box). Source becomes a muted caption chip, not a section heading.
- **Caption every figure with its run** (R6): `from run <short_id> ↗`, linking via `_gotoStudyTab('simulate', 'run-<id>')` (or the run's anchor). Requires `run_id` on each card — native gallery already returns it; V3 threads it into the other two sources, so land V2's card structure with a `run_id` slot the caption fills when present (blank/omit when absent).
- Test: render a study with figures from ≥2 sources → one gallery, one card class, no `Figures` h2, no per-source section headings; a figure with a run renders a "from run …" caption link.

## Task V3: Provenance — thread `run_id` through all figure sources
**Kind:** B (small). **Map §6(4).**
- Attach `run_id` to the embed-HTML source (`study_spec.discover_viz_html_files`) and the static-chart source (`study_charts.discover_static_study_charts` / `discover_declared_figure_charts`) records, so every gallery card can carry the "from run …" caption V2 renders. Where a figure genuinely has no run association (hand-authored `reports/figures/…`), leave `run_id` null and the caption omits.
- Test: the charts/embeds payloads carry `run_id` where derivable; a hand-authored figure has null run_id and no fabricated caption.

## Task V4: Enforce a qualifying visualization — the readiness gap
**Kind:** B. **Map §5(A), §6(c). THE ENFORCEMENT CORE.**
- Add a shared helper (e.g. `lib/viz_gate.py::study_visualization_status(ws, slug) -> {has_run_linked, has_interactive, qualifies, figures_seen}`) that probes the three sources (`build_study_native_gallery`, `build_study_charts_payload`, `discover_viz_html_files`) + the declared `visualizations:` entries, and applies the **explicit bar**: qualifies iff **≥1 run-linked figure AND ≥1 interactive** (Plotly embed / `.gif` / three.js address — NOT only static SVG/PNG). Define the interactive set explicitly (map risk).
- Add `_visualization_gap_findings(ws_root)` to `lib/report_views.py` (mirroring `_question_approach_findings`), iterating `_iter_study_slugs`, emitting one `{study, check:"visualization_gap", severity, message, field_path:"visualizations"}` per study that fails the bar; `findings.extend(...)` into `build_report_lint`. Message names WHAT's missing (no figure at all / has figures but none interactive / figures not run-linked).
- Test: a study with only a static SVG → a `visualization_gap` finding (has figures but none interactive); a study with a Plotly embed or gif linked to a run → no finding; a study with zero figures → a finding. Assert it appears in `/api/report-lint` and the readiness panel counts it.

## Task V5: Surface the viz gate on Gate 3 · Evidence
**Kind:** B + tiny T. **Map §5(B), §6(c.3).**
- Feed the V4 status into the **Evidence** gate as a computed state (alongside `derived_status`/`computed_gate_verdict` in `build_gate_ladder`/`act_gate_states`, `lib/study_page.py`): a study failing the viz bar makes Evidence's computed state not-passed (worst-of with existing signals), so the act-rail Evidence dot + the six-gate ladder reflect it and agree with the readiness gap.
- Test: a study failing the viz bar shows Evidence gate computed-not-passed + the divergence marker where authored differs; a passing study doesn't regress the Evidence dot.

## Task V6: Interactive figure types — three.js (and the address schemes)
**Kind:** T (frontend, small) + B (small). **Map §4, §6(d).**
- Accept a `threejs:` (and generic `html:`) **address scheme** in `discover_declared_figure_charts` (alongside the existing `gif:`/`png:`/`svg:`/`image:`/`file:`), rendering it as a `.figure-card` that **iframes a self-contained HTML file** (same pattern as `embed_visualizations`). This lets a study declare an interactive 3D figure that satisfies the V4 "interactive" bar. (Deep-linking the standalone parsimony viewer via `address: parsimony:<run_id>` as a card that opens out is an acceptable alternative for the 3D case — pick the iframe-embed for self-contained files.)
- Test: a `visualizations:` entry with a `threejs:`/`html:` address renders an iframe figure-card and counts as interactive for the V4 bar.

---

## Deferred / cross-repo (NOT in this increment)
- **V7 (schema):** add `required: bool` + `kind: interactive|static` to the `visualizations:` entry in `viva-template`'s `.pbg/schemas/study.schema.json` (sibling repo). Until then, V4 enforces off the existing array + discovered figures. Separate PR against viva-template.
- **mp4/`<video>`** card type (map §6(d)) — genuinely new, low priority.
- **C7 (CSS extraction)** — run AFTER all V frontend tasks as the single final inline-style sweep over settled markup (still the last task of the branch).

## Success criteria
- The empty-state never names a stale/wrong file; it's honest for zarr and sqlite studies alike.
- Visualizations is one clean gallery, every figure captioned with its run.
- Every study that lacks a qualifying (run-linked + interactive) visualization shows a **Visualization gap** in readiness AND a not-passed Evidence gate — so studies are pushed to fill it.
- A study can declare an interactive three.js/Plotly/GIF figure and have it render inline and satisfy the bar.
