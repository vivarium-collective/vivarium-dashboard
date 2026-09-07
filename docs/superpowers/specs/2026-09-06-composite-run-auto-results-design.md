# Composite runs auto-run their declared analyses & visualizations

**Date:** 2026-09-06
**Status:** Design — approved in brainstorming, pending spec review
**Approach:** A (ephemeral study spec → shared results driver, wired at both completion seams, default-on)

## Problem

Today a run is a config given to a composite (e.g. `ecoli_baseline`). When the
composite finishes, it does **not** run the analyses and visualizations
associated with it — that only happens in a *study* context. So a plain
composite run lands raw output with no ptools overlays, no report card, and
nothing on the workbench.

Two concrete gaps (see the seam map for anchors):

1. **Local composite runs.** `composite_flush.run_flush`
   (`vivarium_workbench/lib/composite_flush.py:267`) already fires on completion
   (`run_runner.py:991-995`) and *would* run analyses + write `report.html`, but
   it draws its analysis list from composite-generator declarations via
   `_composite_analyses`, and the `@composite_generator` decorator + the
   dashboard `GeneratorEntry` never carry an `analyses` field
   (`process_bigraph/composite_generator.py:44,177-187`; `_entry_for`
   L71-85). So `getattr(entry, "analyses", [])` is `[]` and the flush is a
   graceful no-op for every Python-decorated composite.

2. **GovCloud composite runs (Alex).** The bare-composite deployment path
   `_execute_remote` (`run_runner.py:802`) lands `results.zip` and returns
   *before* the flush at `run_runner.py:992`, so remote composite runs produce
   **raw output only**. Studies already run analyses server-side on GovCloud —
   `remote_run_submit` injects `analysis_options` into the viva-api dispatch
   (`remote_run_views.py:384`) and the DAG runs them where the data is — but
   bare composites never do this.

## Goal

A composite run **auto-runs the analyses and visualizations declared for it**
when it completes, by default, **the same way whether it runs locally or on
GovCloud**, producing the standard results contract (`analyses.json`,
`report.html`, viz files) that lands on the workbench — **without** creating a
persisted study entity in `workspace/studies/`.

### Non-goals

- No persisted `study.yaml`, no entry in the studies list, no verdict roll-up,
  conclusion card, outcomes sync, param capture, auto-evaluate, or investigation
  roll-up. Those are study-*identity* stages that assume persistence; a composite
  run borrows only the study *results* stages.
- Not changing the study path's behavior (it keeps its full flush; it just calls
  the same shared results driver underneath).
- No new analysis engine; reuse `v2ecoli.workflow.analysis_runner.run_analyses`
  and the existing viz renderer.

## Design overview

Reuse the study flush's **results** machinery, driven by an **ephemeral**
single-composite study spec built at completion and discarded after. One shared
driver runs the results stages; two completion seams call it (local now,
GovCloud via dispatch injection); one workspace setting turns it on by default
for both.

### 1. Declaration + ephemeral spec

**What a composite declares** — two layers, config wins:

- **Composite default.** Close the `GeneratorEntry.analyses` gap so a
  `@composite_generator` (and `*.composite.yaml`) can carry default `analyses`
  and `visualizations`. `CompositeSpec` already has both fields
  (`process_bigraph/composite_spec.py:250-251`); the decorator signature and
  `_entry_for` just need to accept and copy `analyses` alongside the existing
  `visualizations`. This lets `ecoli_baseline` ship sensible defaults.
- **Run-config override.** The run request/config gains an optional `analyses`
  and `visualizations` block in the study-shaped, scale-grouped form
  (`analyses: {single: [...], multigeneration: [...]}`, mirroring
  `workspace/studies/*/study.yaml`). This is the "declared in the config"
  surface. Config entries override/extend the composite defaults (shallow merge
  per scale for analyses; config-wins for visualizations, matching how studies
  already merge over composite-generator viz in
  `study_run_post.render_study_visualizations:328`).

**The ephemeral spec.** A builder `ephemeral_study_spec(composite_ref, declared)`
synthesizes an in-memory study-shaped dict: baseline = this composite, no
variants, `analyses`/`visualizations` = the merged declaration. It is never
written to disk, never registered, never displayed. It exists only as the input
struct the results driver consumes, then is discarded. It carries **only** the
keys the results stages read — no verdicts/findings/behavior_tests.

### 2. Shared results driver

Extract the study flush's results stages —
`run_study_analyses` (`study_run_post.py:251`) +
`render_study_visualizations` (`:328`) + the report card (`render_report_card`)
— into one function:

```
run_declared_results(run_dir, spec, *, store, sim_data, core) -> ResultsArtifacts
```

It takes any study-shaped spec (real or ephemeral), builds `analysis_options`
via the existing `build_analysis_options` (`study_run_post.py:184`), runs the
declared analyses through the env worker's `run_study_analyses` capability
(`env_worker.py:3169`), renders the declared viz, and writes the existing
artifact contract: `analyses.json` + `report.html` + viz files under
`.pbg/runs/<run_id>/`.

The real study path (`study_runs._run_post_run_flush:135`) is refactored to call
`run_declared_results` for its analyses+viz+report stages, keeping its extra
persistence stages wrapped around it. Result: studies and composite runs emit
**identical-shaped** results and cannot drift.

### 3. Local seam

`composite_flush.run_flush` replaces the broken `_composite_analyses` source:
build the ephemeral spec from (composite defaults ⊕ config declaration), call
`run_declared_results`. Downstream artifacts (`analyses.json`, `report.html`)
are already exactly what that function writes, so local composite runs light up
with no new artifact plumbing.

### 4. GovCloud seam

Bring the bare-composite deployment path to study parity. At composite remote
**dispatch** (the composite branch of `_execute_remote` / the submit path used
by `remote_run.run_remote`), build the ephemeral spec → `build_analysis_options`
→ inject `analysis_options` into the viva-api submit exactly as
`remote_run_submit` does for studies (`remote_run_views.py:384`). viva-api runs
the analyses **server-side where the data lives**, and `_fold_analyses`
(`remote_run_landing.py:54`) lands the same `analyses.json` contract. Viz + the
report card render at **land** time from the folded output via the same driver
(cheap, runs on landed data). Net: analyses run where the data is; results land
identically to the local path.

### 5. Default-on switch + loom surface

A workspace `ui:`-block setting `auto_results: bool` (default `true`), mirroring
how `composite_view` is modeled and defaulted (`lib/models.py:1133`,
`lib/system_info.py:145,155`, read from `workspace.yaml`'s `ui:` block). **Both**
completion seams read it, so it governs local and GovCloud uniformly. Because it
is a workspace/run-level default rather than a frontend toggle, Alex's GovCloud
runs inherit it without ever opening the viewer.

The composite loom viewer surfaces the *same* setting as a default-on checkbox
(frontend reads it like `composite_view` in `static/walkthrough.js:515,528` /
`loom-embed.js`), so the UI reflects the behavior but is **not** the source of
truth. Toggling it in the viewer writes the workspace setting.

## Error handling

- **No analyses/viz declared** (composite defaults empty AND config empty) →
  no-op, run still completes `status="completed"`; no empty `report.html`.
  This preserves today's "plain run" behavior when nothing is declared.
- **Declared-but-unregistered analysis** → surface as a loud `PARTIAL` with the
  offending name (aligns with v2ecoli #708), never a silent OK. The results
  driver already gets per-analysis status from `run_analyses`'s summary.
- **Analysis failure on one scale/seed** must not fail the run or the other
  results — record per-item in `analyses.json`, mark the run's results
  `PARTIAL`, continue. (Matches `run_analyses` PARTIAL semantics.)
- **GovCloud dispatch injection failure** → the run still lands raw output;
  results marked failed with the dispatch error, not a crash.
- **Birth-stub / hive-read hazard.** The multigeneration reader folds birth-stub
  agent partitions in (~1% shift; one lineage's stub schema mismatch blocks the
  read entirely). The durable fix is a v2ecoli reader change restricting the
  multigeneration slice to the all-zeros lineage
  (`WHERE agent_id = repeat('0', generation)`); this spec **depends on** that
  fix landing so auto-run analyses are correct, and notes it as a cross-repo
  prerequisite rather than re-implementing a stub filter here.
- **Memory.** ptools analyses run in the env worker (out of the HTTP process);
  the driver runs analyses per-scale as the study path already does. If a single
  process OOMs on the full hive, run one analysis (view) per worker invocation —
  a driver-level knob, defaulting to per-view isolation for the ptools family.

## Testing

- **Unit:** `ephemeral_study_spec` builds the correct study-shaped dict from
  composite defaults ⊕ config; merge precedence (config wins) is covered.
- **Unit:** `GeneratorEntry.analyses` now populated from the decorator and from
  `*.composite.yaml`; `_entry_for` copies it.
- **Unit:** `run_declared_results` writes `analyses.json` + `report.html` + viz
  for a spec with declared analyses; no-op cleanly for an empty spec; returns
  PARTIAL for an unregistered analysis.
- **Integration (local):** a composite-test-run with a declared ptools analysis
  produces `analyses.json` on completion via `composite_flush.run_flush`; the
  study path produces byte-identical results shape through the same driver.
- **Integration (remote, mocked viva-api):** the composite deployment dispatch
  injects `analysis_options`; landing folds `analyses.json`; viz renders at land.
- **Default:** `auto_results` unset → default true → analyses run; set false →
  run completes with raw output only; the loom checkbox reflects and writes it.
- **Regression:** studies still run their full flush (persistence stages intact).

## Files touched (anchored)

| File | Change |
|---|---|
| `process-bigraph/process_bigraph/composite_generator.py` | decorator accepts `analyses`; `GeneratorEntry.analyses` field; `_entry_for` copies it (L44,71-85,177-187) |
| `vivarium_workbench/lib/study_run_post.py` | extract `run_declared_results` from the analyses+viz+report stages (L184,251,328) |
| `vivarium_workbench/lib/study_runs.py` | `_run_post_run_flush` calls `run_declared_results` for results stages (L135) |
| `vivarium_workbench/lib/composite_flush.py` | build ephemeral spec + call `run_declared_results`, replacing `_composite_analyses` (L162,176,267,273) |
| `vivarium_workbench/lib/run_runner.py` | composite remote path injects analysis_options at dispatch; renders viz/report at land (L802,875,992) |
| `vivarium_workbench/lib/remote_run_views.py` / `remote_run_landing.py` | reuse `build_analysis_options` injection for composite target; fold at land (L384,54) |
| `vivarium_workbench/lib/models.py`, `system_info.py`, `deploy_config.py` | `auto_results` workspace `ui:` setting, default true |
| `vivarium_workbench/static/walkthrough.js`, `loom-embed.js` | loom viewer default-on checkbox reading/writing the setting |
| config schema / run request | optional study-shaped `analyses` + `visualizations` block |
| new `vivarium_workbench/lib/ephemeral_study.py` | `ephemeral_study_spec(...)` builder |

## Cross-repo prerequisites / risks

- **process-bigraph** change (decorator/`GeneratorEntry`) must ship in the pin
  the workbench uses.
- **sms#233** (register `ptools_metabolites` + its multigeneration subclass) and
  the **all-zeros-lineage** v2ecoli reader fix must be in the analysis image for
  the auto-run results to be complete and correct on GovCloud (see the CD2 ptools
  sweep findings). This spec produces the mechanism; those land the correctness.
- The ephemeral-spec shape must stay a strict subset of the study schema so the
  extracted driver accepts both without special-casing.
