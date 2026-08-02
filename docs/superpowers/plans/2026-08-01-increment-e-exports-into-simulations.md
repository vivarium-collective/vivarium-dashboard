# Increment E — Fold Exports into Simulations (per-run hub), drop the tab

> **For agentic workers:** subagent-driven, per-task review, ONE editing subagent at a time in the shared worktree.
> **Depends on:** everything on `feat/study-design-fable-a` (tip after Increment V). Build E off that tip.

**Goal:** Everything a reviewer wants about a run lives *with that run*. Enrich the **Simulations** per-run detail into a real hub (its figures + report cards + results inline, plus the existing downloads), relocate the two study-level pieces Exports uniquely held (Analyses **config** → Model; bulk downloads → a slim Simulations "Study artifacts" strip), then **remove the Exports tab** → 7 tabs. Simpler tab bar, no duplicated download surfaces.

**Why (verified):** the Exports tab (`data-kind="data"`) holds (1) Analysis result files + "Download all .zip", (2) Raw simulation data + "Download all raw", (3) Analyses config ("which modules to run on dispatch"). The Simulations per-run detail (`_showRunDetail`) already surfaces per-run raw-data + analysis(figures/cards) downloads + Composite-Explorer link — so the per-run downloads are already duplicated; only the study-level bits (Analyses config + bulk downloads) and Fable's future audit-package "Record" home need relocating.

**Tech:** Jinja `templates/study-detail.html`, vanilla JS `static/study-detail.js`, `static/style.css`; endpoints unchanged (only where their UI mounts moves). pytest via `dashboard_client` FACTORY fixture.

## Global constraints
- **No endpoint/schema/backend-logic changes** — this is UI relocation + per-run rendering. The existing routes (`/api/study-analysis-outputs`, `/api/study-analysis-zip`, `/api/simulation-run-download`, `/api/study-set-analyses`, `/api/study-native-gallery`, `/api/study-charts`, report-card urls) keep working; only *where* their output renders changes.
- **Lose nothing:** every artifact/affordance currently on Exports must remain reachable (per-run in the hub, study-level in the new strip / Model). A reviewer must still get: each run's raw data, analysis files, figures, report cards; the study-level bulk zips; and the Analyses config editor.
- Reuse existing helpers: the V-increment `.figure-card` gallery render, `_renderRichReportCard` (C6), `_gotoStudyTab` (C1), `SimTable`/`_showRunDetail`. Don't fork.
- **Line numbers are approximate** — grep by content/anchor.
- Test env (ONLY): `/Users/eranagmon/code/vivarium-workbench--study-declutter/.venv/bin/python -m pytest <file> -v`; `dashboard_client(ws)->client`; `node --check` after JS edits; grep `tests/` for fallout on any deletion/relabel.
- **Concurrency:** ONE editing subagent at a time. Reviewers read-only. NEVER `git stash`/`reset`/`checkout`/`clean`/`restore`; FOREIGN `stash@{0}` untouched (read via `git show <rev>:<path>`). Stage only specific paths (`git add <path>`), NEVER `git add -A`. Trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Task E1: Relocate the Analyses config → Model/Compose
**Kind:** T (template + JS mount move).
The Exports "Analyses" section (`#study-analyses-list` + `#study-analyses-status`, "post-run analysis modules to compute on dispatch", driven by `/api/study-set-analyses` via `_loadAnalyses`/the set-analyses JS) is study **setup**, not an export. Move it to the **Compose/Model** panel (`data-kind="compose"`) as an "Analyses" section (near Conditions / model settings — it's "what to compute", part of the study's plan). Move the markup + ensure its JS still binds (the loader runs on the compose tab's activation instead of the data tab's). Keep the editor fully functional (add/remove modules, Save).
- Test: the Analyses config renders + is editable under the Model/Compose tab; it no longer renders under Exports; the set-analyses save path still works (JS still finds `#study-analyses-list`).

## Task E2: Study-artifacts strip on Simulations
**Kind:** T (template + JS mount move).
Move the two **study-level** download groups off Exports onto the **Simulations** panel as one compact **"Study artifacts"** strip (above or below the runs table): Analysis result files (`#data-files` + "Download all .zip" → `/api/study-analysis-zip`) and the Raw-simulation-data bulk ("Download all raw data" → `_downloadAllRawExports`, the `#raw-data-list`/`#exports-downloads` group). Keep the loaders (`_loadDataFiles`/`_loadRawData` etc.) — just remount their targets under Simulations and trigger them on the simulate-tab activation. This is the study-wide "take the artifacts" surface (and the future audit-package home). Keep it slim — a labelled strip, not a second tab's worth of chrome.
- Test: the analysis-files zip + raw-all downloads render under Simulations and resolve; they no longer render under Exports; the loaders still populate (JS finds the remounted ids); the per-row run "⬇ Data" links + per-run detail are untouched.

## Task E3: Enrich the per-run detail into a hub
**Kind:** T (JS + template).
Extend `_showRunDetail` (`static/study-detail.js`) so clicking a run shows, **inline for that run**, in addition to the current metadata + download/Explorer buttons:
- **Figures** — that run's figures, reusing the V `.figure-card` gallery filtered to `run_id == this run` (native panels + charts + embeds whose `run_id` matches). If none, a quiet "no figures for this run" line.
- **Report cards** — that run's report cards inline, reusing `_renderRichReportCard` (C6), if the run has any.
- **Results** — a compact results summary (reuse whatever the run row / analysis-outputs already expose; do not compute anything new — surface existing values, e.g. the analysis output file list for that run if derivable, else the existing analysis-zip link).
Keep it lazy (render on row-open, as `_showRunDetail` already is) and cheap (reuse existing payloads; don't trigger heavy new fetches beyond the gallery/report-card data already loaded for the study). No new endpoints.
- Test: opening a run with figures/cards renders them inline in `#study-run-detail`; a run without them shows the quiet empty lines (no error); the existing metadata + download + Explorer affordances still render; reuses `.figure-card`/`_renderRichReportCard` (assert markup, not a forked renderer).

## Task E4: Remove the Exports tab
**Kind:** T (template + JS + css + act rail).
After E1–E3 relocate everything, delete the Exports tab: the `.study-pillar[data-kind="data"]` button, the `#panel-data` section, and the **act-rail record cluster** (`.act-cluster-record` / `data-act="record"`) so the rail is five acts with no dangling "Exports". Grep `static/study-detail.js` for any `_setStudyTab('data')` caller (e.g. the C4 readouts→Exports pointer, and E2's mount triggers) and repoint/remove them so nothing links to a dead tab. Remove now-dead CSS (`.act-cluster-record`) and any Exports-only JS left unused after E1/E2 moved its mounts. Verify no test asserts the Exports tab/8-tabs (update to 7).
- Test: the rendered page has 7 tabs (no `data-kind="data"` pillar, no `#panel-data`); the act rail shows five acts with no record cluster; no JS calls `_setStudyTab('data')`; the relocated artifacts (E2) + Analyses (E1) + per-run hub (E3) all still render; grep-updated any 8-tab/Exports test.

---

## Out of scope
- The future ordered **audit-package** export (Increment D1) — E2's "Study artifacts" strip is its designated future home, but building the 9-section package is not this increment.
- Any endpoint/schema change; renaming other tabs; the readout write-path.

## Success criteria
- Analyses config lives under Model; study-level bulk downloads live in a slim Simulations "Study artifacts" strip; nothing from Exports is lost.
- Clicking a run in Simulations shows that run's figures + report cards + results + downloads inline — the per-run hub.
- The Exports tab is gone; the tab bar is 7 tabs; the act rail is five clean acts; nothing links to a dead tab.
