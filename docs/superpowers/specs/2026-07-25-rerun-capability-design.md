# Rerun capability — investigation / study / simulation (Sub-project 2)

**Date:** 2026-07-25
**Repo:** `vivarium-workbench` (worktree `/Users/eranagmon/code/vwb-rerun`, branch `feat/rerun-capability`, off `origin/main`).

## Problem

A recorded run can be replayed only from the CLI (`cli_runs.rerun`), and even that replays a study-originated run as a plain composite run — it lands in `.pbg/composite-runs.db`, not the study's `runs.db`, losing study fidelity. There is no API or UI. Users want to rerun at three granularities from the workbench: a whole **investigation**, a **study**, and a single **simulation** in the DB.

## Goals

1. **Rerun a simulation** — replay its *exact recorded* `spec_id` + `params` as a **new** run, landing in its **origin DB** (study run → that study's `runs.db`; composite run → `composite-runs.db`).
2. **Rerun a study** — re-launch its declared baseline (`study.yaml`) as a new run.
3. **Rerun an investigation** — re-launch every study's baseline (force; ignore the pipeline gate).
4. UI: a **"Rerun investigation"** button in the investigation header, a **"Rerun study"** button on study-detail, and a per-row **"↻ Rerun"** in the Simulations DB table (global + per-study).

## Non-goals

- No overwrite semantics — rerun always mints a **new** `run_id` (runs are immutable records).
- No rerun of *variants* as a batch in v1 (a variant sim reruns individually via the sim-level path; "Rerun study" covers the baseline). Variant-ensemble rerun is a follow-up.
- No change to how runs execute (detached subprocess, `run_runner`) — rerun only re-dispatches recorded/declared inputs.

## Semantics (confirmed)

Rerun = reproduce with recorded/declared inputs → a new run.
- **Sim** → exact recorded `spec_id` + `params`, into the origin DB.
- **Study** → current declared baseline from `study.yaml`.
- **Investigation** → every study's declared baseline, forced (ignore gate).
- **Confirmation:** investigation + study reruns confirm first (batch/long); a single-sim rerun is one-click with a toast.

## Architecture

### Backend — `vivarium_workbench/lib/rerun.py` (new)
Thin orchestration over the existing run subsystem; each function returns `(response_dict, status_code)`.

- `resolve_rerun_target(ws_root, run_id) -> dict | None`
  - Uses `cli_runs.find_run(ws_root, run_id) -> (db_file, row)`. `row` carries the deserialized `spec_id`, `params`, `n_steps`.
  - **Origin from `db_file`:** if `db_file` is a study's `runs.db` (i.e. `Path(db_file).parent` is a study dir under `WorkspacePaths.studies`), origin = `"study"`, `study = Path(db_file).parent.name`; if `db_file` endswith `.pbg/composite-runs.db`, origin = `"composite"`.
  - Returns `{run_id, origin, study?, spec_id, params, n_steps}` (or `None` if not found).

- `run_rerun(ws_root, run_id) -> (resp, status)`
  - `resolve_rerun_target`; 404 if not found.
  - **study origin:** launch the recorded `spec_id` + `params` (+ `n_steps`) into `studies/<study>/runs.db`. Implementation: reuse the study run's core invocation so it lands in the study DB with study emit-paths/runtime — factor the run-launch tail of `study_runs.run_study_baseline` into a helper `study_runs.launch_into_study(ws_root, study, spec_id, params, n_steps)` (mints run_id, resolves state, runs into the study's `runs.db`, post-run stages), and call it with the RECORDED `spec_id`/`params` (not re-read from `study.yaml`, so it's faithful even if the study was edited).
  - **composite origin:** `cli_runs.run_composite(ws_root, spec_id, steps=n_steps, params=params, detach=True)` → `.pbg/composite-runs.db` (the existing path).
  - Returns `{run_id: <new>, origin, status: "running"}`.

- `rerun_investigation(ws_root, investigation) -> (resp, status)`
  - Load the investigation (`investigations`/`scaffold_mutations`), read its `studies:` list; for each study, call `study_runs.run_study_baseline(ws_root, {study})` (declared baseline, ignore gate). Collect `{study, run_id | error}` per study.
  - Returns `{investigation, launched: [{study, run_id}], errors: [...], count}`.

- **Study rerun needs no new backend** — the frontend calls the existing `POST /api/study-run-baseline {study}`.

### Endpoints — `vivarium_workbench/api/app.py`
- `POST /api/run-rerun` — body `{run_id}` → `rerun.run_rerun`. CSRF-guarded (mutating). Model `RerunResult`.
- `POST /api/investigation-rerun` — body `{investigation}` (or `{name}`) → `rerun.rerun_investigation`. CSRF-guarded. Model `InvestigationRerunResult`.

### Frontend
- **Investigation header** — `templates/index.html.j2` `.inv-export-actions` span (line 906). Add `<button id="investigation-rerun">Rerun investigation</button>`. Handler in `static/walkthrough.js` near `_openInvestigationDetail` (~5983) / `_runUnblockedSimulations` (~6188): confirm dialog → `POST /api/investigation-rerun {investigation: <current>}` → toast + reuse `#investigation-run-progress` panel to show launched runs.
- **Study-detail header** — `templates/study-detail.html` + `static/study-detail.js`. Add a "Rerun study" button → confirm → `POST /api/study-run-baseline {study}` → toast. (Place beside the existing run/report actions.)
- **Sim DB table** — `static/sim-table.js` `_actions(row)` (line 116; rendered into the actions `<td>` at line 151, present in both the global `#sim-table` and per-study `#study-sim-table`). Add `↻ Rerun` → one-click `POST /api/run-rerun {run_id: row.run_id}` (each `<tr>` already carries `data-run-id`) → toast; on success, refresh the table. No confirm (single sim).

## Data flow

```
Sim "↻ Rerun" (row.run_id) → POST /api/run-rerun
   rerun.run_rerun → find_run → origin from db_file
     study origin  → study_runs.launch_into_study(study, spec_id, params, n_steps) → studies/<study>/runs.db
     composite     → cli_runs.run_composite(spec_id, params, n_steps, detach)      → .pbg/composite-runs.db
   → new run_id (detached, status running)

Study "Rerun study" → POST /api/study-run-baseline {study}   (existing; declared baseline)

Investigation "Rerun investigation" → POST /api/investigation-rerun {investigation}
   for study in investigation.studies: run_study_baseline({study})   (force, ignore gate)
   → [{study, run_id}]
```

## Testing

- **`resolve_rerun_target` (unit):** given a run in a study `runs.db` → origin study + slug + recorded spec_id/params; given a run in `composite-runs.db` → origin composite. Not found → None. (Build tiny fixture DBs via `composite_runs.save_metadata`.)
- **`run_rerun` routing (unit, mocked launch):** monkeypatch `study_runs.launch_into_study` + `cli_runs.run_composite`; assert a study-origin run calls `launch_into_study(study, recorded_spec_id, recorded_params, n_steps)` and a composite-origin run calls `run_composite(recorded_spec_id, …)`; new run_id returned.
- **`rerun_investigation` (unit):** fixture investigation with 2 studies → calls `run_study_baseline` twice with each study; aggregates run_ids; a failing study lands in `errors`, doesn't abort the rest.
- **Endpoints (dashboard_client):** `POST /api/run-rerun` and `/api/investigation-rerun` return the documented shapes; CSRF enforced on both.
- **Frontend (render):** investigation header contains `#investigation-rerun`; a sim-table row renders a Rerun action carrying its run_id; study-detail has a Rerun-study control. (Behavior via the existing subprocess `dashboard_client` fixture where feasible.)

## Risks / notes

- **`launch_into_study` factoring:** the cleanest fidelity path needs a small extraction from `run_study_baseline` (its run-launch tail) so a rerun can pass an explicit `spec_id`+`params` into the study DB. Keep `run_study_baseline` behavior byte-identical (it calls the extracted helper with the study-derived spec_id/params).
- **Long runs:** a rerun launches real compute (some studies run to division — tens of minutes). All reruns are **detached**; the UI shows "running" and polls, never blocks. Investigation rerun can launch several at once — respect the existing `CONCURRENCY_CAP` (run_registry) so they queue rather than overwhelm.
- **Snapshot/publish:** rerun buttons are live-only actions; in the read-only bundle they should be hidden/disabled (mirror how existing run buttons degrade in snapshot mode).
