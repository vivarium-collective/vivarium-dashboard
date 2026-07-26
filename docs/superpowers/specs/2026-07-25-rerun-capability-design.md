# Reproducible runs + full flush + rerun (Sub-project 2)

**Date:** 2026-07-25 (rev 2 — expanded from "rerun buttons" to guarantee reproducibility + a complete flush, per mid-flight requirements)
**Repo:** `vivarium-workbench` (worktree `/Users/eranagmon/code/vwb-rerun`, branch `feat/rerun-capability`, off `origin/main`).

## Problem

Users want to **rerun** an investigation / study / simulation from the workbench, and — critically — a rerun must **reproduce the original exactly** and **go all the way through the post-run flush** (visualization → analyses → report cards). Two gaps block that today:

1. **Incomplete run record (reproducibility).** `runs_meta` stores only the *override-delta* `params_json` + `n_steps` + `spec_id`. The **emitter**, **emit_paths**, and the study's **`runtime:` settings** are read *live from `study.yaml`/`workspace.yaml` at run time* and never stamped per-run. A study rerun therefore reproduces the *current* YAML, not what the original run used. (The composite path persists a near-complete `request.json`; the study path has no equivalent.)
2. **Stubbed flush.** The **study** post-run tail runs a full synchronous pipeline (viz → post-run scripts → analyses → outcomes → eval → investigation rollup; report cards ride in via a `ReportCardStep` in `spec.analyses`). But the **composite** path's flush (`composite_flush._dispatch_analyses`) only *records analysis declarations* + a thin `report.html` — it never renders real analyses/report cards (the "queued" follow-up).

## Goals

- **A. Reproducibility manifest** — stamp a **complete per-run replay manifest** (both study + composite paths) so a rerun replays *from the record*, not the live YAML → exact reproduction.
- **B. Complete the flush** — render **real analyses + report-card artifacts** in the composite-path flush (finish the stub), so every run (and rerun) goes all the way through viz → analyses → report cards.
- **C. Rerun** — investigation / study / simulation rerun that replays the manifest exactly and runs the full flush. Buttons in the investigation header, study-detail, and per-row in the Sim DB table.

## Non-goals

- Not re-architecting the run subsystem — additive: a new manifest column + finishing an existing stub + rerun orchestration.
- No overwrite — rerun always mints a new `run_id`.
- Variant-ensemble batch rerun deferred (a variant sim reruns individually).

---

## Part A — Reproducibility manifest

### What to capture
A complete, self-contained replay record for **every** run, at launch time (both paths already know all of it):
```
manifest = {
  "version": 1,
  "spec_id":     <composite id>,
  "params":      <FULL effective generator config: baseline params + overrides,
                  incl. seed/cache_dir/etc. — NOT the delta>,
  "n_steps":     <int>,
  "emitter":     <resolved emitter kind, e.g. "parquet"|"xarray"|"sqlite">,
  "emit_paths":  [<resolved emit paths>],
  "runtime":     {<the study runtime block used: subprocess_timeout_s,
                  max_generations, single_daughters, default_n_steps, emitter>},
  "origin":      "study"|"composite",
  "study":       <slug>|null,
  "pkg":         <workspace package, e.g. "v2ecoli">,
  "generation_id": <id|null>,
  "code_version":  {"git_sha": <ws git sha|null>, "package": <version|null>}  # best-effort
}
```

### Storage
- New **nullable `manifest_json TEXT` column** on `runs_meta` (additive, via `composite_runs._NEW_COLUMNS`).
- `composite_runs.save_metadata(...)` gains an optional `manifest: dict | None` param → `manifest_json = json.dumps(manifest)`.
- Both launch sites build + pass the full manifest:
  - **Study path** — `study_runs.launch_into_study` (Part C's factored helper) assembles the manifest from the resolved `spec_id`, full effective `params`, `n_steps`, `emitter`, `emit_paths`, `runtime`, `generation_id`. (These are all computed in `run_study_baseline` today at study_runs.py:169-178 before `invoke_run`.)
  - **Composite path** — `composite_test_run_views.composite_test_run` builds the manifest alongside the `request.json` it already writes (which carries `overrides`/`steps`/`emit_paths`/`pkg`/`target`).
- **Best-effort:** `code_version.git_sha` from the workspace git HEAD; `generation_id` reuses the existing advisory hook. Failures degrade to `null`, never block a run.

### Read-back
- `run_params` display is unchanged (`study.yaml runs[].provenance.params` stays the human table).
- `cli_runs.query_run_meta` / `find_run` already return the row; `resolve_rerun_target` (Task 1, done) reads `manifest_json` when present, **falling back** to `spec_id`+`params`+`n_steps` for legacy runs (so old runs still rerun, just less exactly).

---

## Part B — Complete the flush

Goal: the composite-path flush renders **real** analyses + a real report card, matching the study path's completeness.

- `lib/composite_flush.py` — `run_flush(run_dir, req, spec_id, db_file, run_id, core)` (called from `run_runner.execute`). Today `_dispatch_analyses` only records declarations; expand it to **render the composite's declared analyses over the gathered emitter outputs** (reuse the env-worker analysis dispatch that `study_run_post.run_study_analyses` uses) and write real `analyses.json` + `report_card.html` (+ verdict) artifacts into the run dir, instead of the thin summary.
- If a composite declares no analyses, it stays a graceful no-op (thin report) — no regression for analysis-less composites.
- **Study path is already complete** — verify `launch_into_study` (Part C) preserves the full 7-stage tail (viz → post-run scripts → `run_study_analyses` (report cards) → outcomes → capture-params → auto-evaluate → investigation rollup). No new study-path stage; the guarantee is that the factoring keeps all seven.

(YAGNI note: B is scoped to *finishing the existing stub* — render declared analyses + a report card — not inventing new analysis types.)

---

## Part C — Rerun (investigation / study / simulation)

### `lib/rerun.py`
- `resolve_rerun_target(ws_root, run_id)` — **done (Task 1)**; extend to prefer `manifest_json` (full replay inputs) over the delta params when present.
- `run_rerun(ws_root, run_id) -> (resp, status)`:
  - Load the target (manifest-preferred). **study origin** → `study_runs.launch_into_study(ws_root, study, spec_id, params, n_steps, emitter=…, emit_paths=…, runtime=…)` → lands in the study's `runs.db`, runs the full flush, stamps a fresh manifest. **composite origin** → `cli_runs.run_composite(... detach=True)` with the manifest's `spec_id`/`params`/`n_steps`/`emit_paths` → `composite-runs.db`, runs the completed flush.
  - New `run_id`; response `{run_id, origin, reran: <old id>, status}`.
- `rerun_investigation(ws_root, investigation)` — iterate the investigation's `studies`, `study_runs.run_study_baseline({study})` each (declared baseline, force/ignore gate); aggregate `{launched:[{study,run_id}], errors, count}`.
- Study rerun uses the existing `POST /api/study-run-baseline`.

### `launch_into_study` (factored from `run_study_baseline`)
`launch_into_study(ws_root, study, spec_id, params, n_steps, *, emitter=None, emit_paths=None, runtime=None, label=None)` — the run-launch + **full 7-stage flush** tail, taking EXPLICIT replay inputs (from the manifest) instead of re-reading `study.yaml`. It assembles + stamps the run's own manifest (Part A). `run_study_baseline` computes `spec_id`/`params`/`emitter`/`emit_paths`/`runtime` from `study.yaml` then delegates (behavior byte-identical).

### Endpoints — `api/app.py`
- `POST /api/run-rerun {run_id}` → `RerunResult`; CSRF-guarded.
- `POST /api/investigation-rerun {investigation}` → `InvestigationRerunResult`; CSRF-guarded.

### UI
- **Investigation header** (`index.html.j2` `.inv-export-actions`, ~L906): "Rerun investigation" → **confirm** → `/api/investigation-rerun`.
- **Study-detail header**: "Rerun study" → **confirm** → `/api/study-run-baseline`.
- **Sim DB row** (`sim-table.js` `_actions`, L116; global + per-study): `↻ Rerun` → **one-click** → `/api/run-rerun {run_id}` (row has `data-run-id`) → toast + refresh.
- Live-only; hidden/disabled in snapshot mode.

---

## Data flow

```
RUN (study or composite) ──> build FULL manifest ──> runs_meta.manifest_json  (A)
   study run  ── full 7-stage flush (viz→analyses→report cards→…)             (already complete)
   composite  ── run_flush renders real analyses + report card                (B: finish stub)

RERUN:
  sim ↻     → /api/run-rerun → resolve_rerun_target (manifest-preferred)
                study    → launch_into_study(spec_id,params,n_steps,emitter,emit_paths,runtime) → study runs.db + full flush + fresh manifest
                composite→ run_composite(manifest inputs, detach)              → composite-runs.db + completed flush
  study     → /api/study-run-baseline {study}                                  (declared baseline)
  invest.   → /api/investigation-rerun → run_study_baseline per study (force)
```

## Testing

- **A:** `save_metadata` writes `manifest_json`; migration adds the column; a study launch stamps a manifest with emitter+emit_paths+runtime+full params; `resolve_rerun_target` prefers manifest, falls back to delta for legacy rows.
- **B:** `run_flush` with a composite that declares an analysis renders a real `analyses.json`/`report_card.html` (env-worker mocked); an analysis-less composite stays a graceful no-op.
- **C:** `launch_into_study` uses explicit inputs + the study `runs.db` + preserves all 7 stages (stub the subprocess/flush); `run_rerun` routing (manifest → study vs composite, exact inputs passed); `rerun_investigation` iterates studies; endpoints (dashboard_client, CSRF); UI render (three buttons).
- **Reproducibility assertion:** a run → its manifest → `run_rerun` passes byte-identical replay inputs (spec_id, full params, n_steps, emitter, emit_paths, runtime) to the launcher.

## Risks

- **Manifest completeness is the crux** — the guarantee is only as good as what we stamp. The test suite asserts the manifest contains emitter/emit_paths/runtime/full-params, and that `run_rerun` forwards them verbatim.
- **Flush rendering (B)** runs real analyses via the env worker — could be slow / workspace-dependent; keep it best-effort (a failed analysis logs + degrades, never breaks the run) and behind the same env-worker path the study flush already uses.
- **Legacy runs** (no manifest) still rerun via the delta fallback — flagged in the UI as "best-effort replay" is out of scope; they simply reproduce less exactly.
- Long detached runs + `run_registry.CONCURRENCY_CAP` unchanged.
