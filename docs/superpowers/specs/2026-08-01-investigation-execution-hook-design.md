# Investigation execution hook — prerequisite order + post-sim/cross-study analyses

**Date:** 2026-08-01
**Status:** design (for approval before implementation)
**Repos:** `vivarium-workbench` (core hook) + `v2ecoli` (comparison re-model)

## Purpose

Give the general runner two capabilities it lacks, so an investigation can be
self-executing in dependency order — which is what finishes the comparison
convergence (ParCa auto-runs before the configs; the cross-config matrix
aggregates across studies). Both are **backward-compatible** (no-ops / additive
for existing investigations).

## What the workbench does today (baseline to preserve)

- `prepare_investigation` (`lib/prepare_investigation.py:206`) runs studies in a
  **flat loop** — `for slug in studies: prepare_study(...)` — with **no
  prerequisite ordering**.
- `prepare_study` runs a study's `comparative_visualizations`: the `run` whose
  `sim_name == slug` is the **baseline** (`POST /api/study-run-baseline`), the
  rest are **variants** (`POST /api/study-run-variant`); it then renders each
  comparative as a time-series overlay from the study's `runs.db`.
- `pipeline_gate.prerequisites` edges are **written** (`lib/study_seed.py`) and
  **rendered** in the investigation graph (`investigation_graph_views.py`) but
  **never executed in order**. There is **no post-sim analysis phase** beyond the
  native comparative overlay, and **no cross-study output flow**.

## Design

### Part A — Workbench core (`vivarium-workbench`)

**A1. Prerequisite ordering in `prepare_investigation`.** Replace the flat study
loop with a **topological order** over each study's `pipeline_gate.prerequisites`
(the `{study, relation}` edges `study_seed` already writes). A study runs only
after its prerequisites. **Backward-compatible:** an investigation with no
prerequisites has no edges → any order is valid → the observed order is
unchanged. On a cycle, fail loud with the cycle named.

**A2. Post-sim analysis phase.** After a study's runs complete, run any analyses
the study declares (an `analyses:` list in `study.yaml` — reusing the existing
Analysis-framework naming, not a second concept), reading that study's `runs.db`;
after **all** studies complete, run any
**investigation-level** analyses declared in `investigation.yaml`, which read
member studies' analysis outputs. **Additive:** studies/investigations that
declare none behave exactly as today. This is the mechanism the comparison's rich
cards (per study) and the cross-config matrix (investigation-level) plug into.

Both A1 and A2 reuse existing pieces (`study_seed` edges, `comparative_runs`
patterns, `WorkspacePaths`, the run API) — no new run engine.

### Part B — Comparison re-model (`v2ecoli`, native baseline+variant)

Rework the Phase-2 materializer (`comparison_materialize.py`) from **paired
studies** to the workbench's **native model**:

- **Per config → ONE study.** `sim_name == slug` = the **candidate**
  (`ecoli_baseline`); a variant `sim_name` = the **reference** (`vecoli`). The key
  observables (cell/dry/protein/RNA mass, growth) become
  `comparative_visualizations` entries → the trajectory overlays render via the
  existing `prepare_study` machinery for free.
- **Rich cards + verdicts** (`summary`/`statistical`/`parca`/`distribution`/…)
  = a **per-study post-sim analysis** (`comparison_cards`, already built in
  Phase 2) declared on each config study, reading the baseline + variant runs
  from the study's `runs.db` (via the run-store adapter, already parquet-aware).
- **Cross-config matrix** = an **investigation-level analysis**
  (`comparison_matrix`, already built) declared in `investigation.yaml`, reading
  each config study's verdict output. This is A2's cross-study flow — replacing
  the Phase-2 `<run>::comparison_cards` placeholder.
- **ParCa study** = a **prerequisite** (already built, `parca_study.py`): each
  config study declares `pipeline_gate.prerequisites: [{study: parca}]`; A1 runs
  it first (pull-or-compute), so `sim_data` is produced/validated before the
  configs run.

## Backward-compatibility & rollout (the "don't break anyone" gate)

- **A1 is a no-op** for every existing investigation (none declare
  prerequisites today — verified: the edges are dashboard-render-only). Prove it:
  the existing prepare-investigation / investigation-run test suite must pass
  unchanged, and a golden run of a real no-prereq investigation must produce the
  same run set + order.
- **A2 is additive** — only fires when a study/investigation declares analyses.
- Shared surface (all investigations + the dashboard's `prepare-investigation`
  path): the change is in `lib/prepare_investigation.py` + a small ordering
  helper; the dashboard route delegates to the same function, so it inherits the
  behavior without a separate change. No feature flag (per decision) — the
  no-op/additive properties are the safety, enforced by the existing suite.

## Non-goals

- Re-running arbitrary DAGs across investigations; remote (`run-remote`)
  ordering (Phase 3); retiring `v2e-compare` (Phase 3). This spec is the
  execution hook + the comparison re-model onto it.

## Risks

- **Topological order changing an existing run order** where a latent, unintended
  prerequisite edge exists → mitigated by A1 being a no-op only when there are no
  edges; audit that no shipped investigation has stray `pipeline_gate.prerequisites`.
- **The dashboard's live `prepare-investigation` path** must stay byte-identical
  for no-prereq/no-analysis investigations — the existing suite + a golden run are
  the gate.
- The re-model (Part B) changes the comparison's study shape → its own tests +
  the gated e2e re-run confirm the native studies produce the same cards/verdicts
  as the paired-study version.
