# Reproducible Rerun Spine — env-versioned, verifiable, retrievable (Spine A)

**Date:** 2026-07-27
**Repos:** `vivarium-workbench` (run/rerun/manifest machinery — primary), `pbg-superpowers`/`viva_superpowers` (run registry, study_audit, needs_attention), `v2ecoli` (consumer workspace).
**Worktree:** `/Users/eranagmon/code/vivarium-workbench--repro-spine`, branch `spec/reproducible-rerun-spine`, off `origin/main`.

**Supersedes/extends:** `2026-07-25-rerun-capability-design.md` (Sub-project 2 — the replay *manifest* + rerun orchestration; partially built). Builds on `2026-07-26-study-reproducibility-contract-design.md` (the L0–L5 audit contract).

## Framing — "The Model Must Testify"

The workbench is a chain of custody for scientific evidence: a model is put on the stand, tested, and given a defensible three-part verdict (Code / Biology / What-we-learned). This spec is the **Clerk's job**: *all artifacts are versioned and traceable*, so any run can be reproduced — or, better, retrieved — and so a change in the simulation environment is *detected*, not silently absorbed. Reproducibility is what makes the verdict admissible.

## Problem (from the rerun audit + reproducibility survey)

A rerun today does **not** reliably reproduce the original result:

1. **Environment/version is captured incompletely and never compared.** Every run builds a manifest (`composite_runs.build_run_manifest`) with a best-effort `code_version = {git_sha, package_version}` — but it is **workspace-git-only** (not the simulator/`process-bigraph` versions, not `uv.lock`, not python/platform, not the ParCa cache fingerprint), and it is **never read back or diffed** anywhere. If code or dependencies changed since a run, a rerun produces different results with **no warning**.
2. **"Rerun study" and "Rerun investigation" re-derive from the current (mutable) `study.yaml`** (`run_study_baseline`), not the recorded manifest — so a rerun after any spec edit reproduces the *new* config, not the original. Only the per-row `↻ Rerun` replays the manifest. "Rerun" ≠ "reproduce."
3. **No determinism contract / verification.** Seed is not a first-class field (survives only if embedded in `params`); nothing hashes the outputs, so a rerun can only be *launched*, never *verified* to match.
4. **No artifact reuse.** Rerun always recomputes, even when a matching completed run's outputs are already saved on disk.
5. **Four divergent run entry points** (`lib.rerun`, legacy `cli_runs.rerun`, `run_study_baseline`, and a *parallel* `viva_superpowers.run_registry` writer whose schema has **no manifest column** → bespoke `run-script` runs can never be replayed). Run-tracking is scattered across `runs.db` + `.pbg/runs.jsonl` + `_runs.yaml`.
6. **Investigation rerun is a thin fan-out** — no `inputs.from` dependency ordering, no prereq-passed gating.

## Goals

- **G1 — env-versioned runs.** Every run stamps a complete, reconstructable `env_id`.
- **G2 — rerun == reproduce.** Study/investigation/sim reruns replay from the record, with a distinct, separately-named "run current spec" action for the re-derive case.
- **G3 — drift detection + pin.** A run whose `env_id ≠ current` is flagged `env_stale` and surfaced; `pinned_env:` opts a study out. "Use the older version" = reconstruct from the recorded commit + lockfile.
- **G4 — verifiable reproduction.** A `result_fingerprint` per run; a rerun with matching `env_id`+seed asserts a matching fingerprint, surfacing nondeterminism.
- **G5 — retrieve before recompute.** A content index keyed by `(composite, canonical config, seed, env_id)` → saved artifacts; reproduction serves them when present.
- **G6 — one path.** Consolidate to a single run-record writer (manifest always present) and a single rerun path; retire the divergent ones.

## Non-goals

- Not solving all nondeterminism (Ray/FP ordering): G4 *detects and reports* it; closing specific sources is separate determinism-hardening work referenced, not owned, here.
- Not the Phase-2 structural content-addressed engine (`lib/artifacts`): this spec builds the lean index on the existing manifest; promoting-or-deleting the dead engine is a later spec.
- No overwrite — a rerun always mints a new `run_id`.

## Design

### Phase 0 — Consolidate the foundation (prereq, folded into this spec's plan)
The reproducibility program is stranded across unmerged branches. Before Phase 1, land:
- `study-registry-migration` — the data-model canonicalization (dual study layout → one; rival composite schemas → `conditions.baseline/variants`).
- `feat/study-audit-l0-l5` (viva_superpowers `study_audit.py`) + `feat/audit-ci-gate` (the `audit-gate` CI job + allowlist ratchet).
Each landed the same way as prior hardenings (per-commit onto current origin, verified). Rationale: G1/G4 stamp into a run record and G6 consolidates writers — both are unstable while the data model and audit are mid-migration.

### 1. One manifest, one writer (G6, the streamline)
- Make `composite_runs.build_run_manifest` the single source of truth, written by **one** registry writer. Fix the parallel `viva_superpowers.run_registry` DDL to carry `manifest_json` (or unify it onto the workbench writer) so **every** run — UI, CLI, and bespoke `run-script` — lands a complete manifest. This removes the manifest/no-manifest fidelity fork in `rerun.py`.
- Retire the legacy `cli_runs.rerun` (`vwb rerun`) composite-only path; the UI `lib.rerun.run_rerun` becomes the one rerun path.
- `.pbg/runs.jsonl` remains an append-only *event* log (not a rival record); `study.yaml.runs[]` stays not-appended (already true). `runs.db` `runs_meta` is the canonical durable record.

### 2. Complete the `env_id` (G1 — the core gap-fill)
Extend the manifest's `code_version` into a structured, hashed `env`:
```
env = {
  workspace_commit:  <git sha of the workspace>,
  sim_packages:      {<pkg>: {version, git_sha}}   # v2ecoli, process-bigraph, bigraph-schema, viva_superpowers, …
  lockfile_hash:     <sha256 of uv.lock>,
  python:            <X.Y.Z>,
  platform:          <os/arch/libc>,
  cache_fingerprint: <ParCa sim_data cache fp — already computed in run_condition_multigen_parquet.py>,
}
env_id = sha256(canonical(env))[:16]
```
- Best-effort capture at launch (both study + composite paths already know most of it; cache_fingerprint is computed but not threaded — thread it). Any field that can't resolve degrades to `null`; the run never blocks.
- `env_id` is stored on `runs_meta` (its own column, for cheap drift queries) *and* inside `manifest_json`.
- **Reconstructable:** `workspace_commit` + `lockfile_hash` are sufficient to recreate the env (checkout + `uv sync` the recorded lock) — the machinery for "use the older version."

### 3. Rerun == replay the manifest, always (G2)
- Route **"Rerun study"** and **"Rerun investigation"** through the manifest-replay launcher (`launch_into_study` with the stored manifest inputs), **not** `run_study_baseline`. Make **seed** a first-class manifest field threaded through `run_core.invoke_run`.
- **Two named actions, never conflated:**
  - **"Reproduce run"** — replay the recorded manifest (params, seed, emitter, emit_paths, runtime, env intent). Byte-for-byte intent.
  - **"Run current spec"** — re-derive from the (possibly edited) `study.yaml`. The legitimate "I changed the model, run it again" operation.
- The per-row `↻ Rerun` is "Reproduce run." The study/investigation headers expose **two distinct buttons** — "Reproduce" (replay manifest) and "Run current spec" (re-derive) — never a single ambiguous "Rerun." Snapshot mode hides both (live-only).

### 4. Drift detection + pin (G3)
- On any reproduce, diff the run's `env_id` vs the current environment's `env_id`. On mismatch: record a `provenance_mismatch` flag on the new run and **surface `env_stale`** through the existing `viva_superpowers.needs_attention` signals (a new signal kind) and `viva-report --audit` (the Case History). Default is *warn + record*, not block.
- `pinned_env:` on a study (or run) means "this study is intentionally pinned to env X" → drift is not flagged; a reproduce reconstructs/uses the pinned env.
- "Use the older version" workflow: from a stale run, offer **reconstruct** (checkout recorded `workspace_commit` + `uv sync` `lockfile_hash` in a throwaway env) → reproduce there; documented, not necessarily one-click in Phase 1.

### 5. Result fingerprint — verifiable reproduction (G4)
- At run completion, compute `result_fingerprint = sha256` over a **declared, stable set of key outputs** (per composite/study — e.g. final mass, doubling time, a canonical readout vector; NOT volatile fields like timestamps/paths). Store on `runs_meta` + manifest.
- On **Reproduce**, after the rerun completes, assert `new.result_fingerprint == original.result_fingerprint` when `env_id` and `seed` match. On mismatch → flag **`nondeterministic`** (surfaced like `env_stale`): either the run is nondeterministic or an uncaptured input changed. This is the Clerk's certification: "rerun of run X reproduced its fingerprint."
- The fingerprint's field set is declared (a study/composite `fingerprint_fields:`), defaulting to the study's declared observables so it's meaningful and not brittle.

### 6. Investigation rerun = execute the DAG (G2/robustness)
- Replace the thin fan-out: traverse `inputs.from` in **dependency order** (reuse the L5 topological order from `study_audit`), with **prereq-passed gating** (don't launch a downstream study until its upstreams reproduced/passed). Aggregate `{order, launched, skipped, errors}`.

### 7. Retrieve before recompute (G5 — the user's "we hold onto saved runs")
- Maintain a **content index**: key = `(composite_id, canonical(config), seed, env_id)` → `{run_id, artifact_path, result_fingerprint, status}`. This is a view/table over the consolidated `runs_meta` (no new store).
- **Reproduce logic becomes retrieve-or-compute:** on "Reproduce run X," look up the key; if a completed run with intact saved artifacts exists → **serve them** (no recompute), certified by the fingerprint; else compute. Recompute is forced only when no matching saved run exists (new `env_id` from drift, or artifacts evicted/absent).
- This is the lean bridge to the Phase-2 structural engine: the index *is* a manifest-keyed lightweight CAS. `env_id` drift naturally invalidates a cache hit (different key) → the system knows to recompute *or* reuse-old-if-pinned.

## Data model changes (additive)
- `runs_meta`: new columns `env_id TEXT`, `result_fingerprint TEXT`, `provenance_status TEXT` (`ok|env_stale|nondeterministic`), plus the existing `manifest_json` carrying the full `env` + `seed` + `fingerprint_fields`. Nullable; migrations via `composite_runs._NEW_COLUMNS`.
- `study.yaml`: optional `pinned_env:` and `fingerprint_fields:`.
- `viva_superpowers.run_registry` DDL gains `manifest_json`/`env_id`/`result_fingerprint` (writer unification).
- New `needs_attention` signal kinds: `env_stale`, `nondeterministic`.

## Testing
- **Manifest/env:** a launch stamps `env` with sim-package versions + lockfile_hash + cache_fingerprint; `env_id` stable under reordering; degrades to null without blocking.
- **Reproduce fidelity:** "Reproduce" forwards manifest inputs verbatim (spec_id, full params, seed, emitter, emit_paths, runtime); "Run current spec" re-derives — distinct paths, asserted.
- **Drift:** a run stamped at env A, reproduced under env B → `provenance_status=env_stale` + a `needs_attention` signal; `pinned_env` suppresses it.
- **Fingerprint/verify:** matching env+seed → matching fingerprint asserted; an injected nondeterminism → `nondeterministic` flag.
- **Retrieve:** a second reproduce with a saved matching artifact serves it without recompute (spy the launcher is NOT called); a drifted env forces recompute.
- **Investigation DAG:** rerun launches in topological order; a downstream is not launched before its upstream reproduces.
- **Consolidation:** a bespoke `run-script` run lands a manifest; legacy `cli_runs.rerun` path removed (or shimmed) without breaking callers.

## Risks
- **Manifest/env completeness is the crux** — the guarantee is only as strong as what's stamped; tests assert the env fields + verbatim forwarding.
- **Fingerprint brittleness** — hashing volatile fields would make every rerun "fail." Mitigate by declaring `fingerprint_fields` (default = declared observables), hashing rounded/canonical values.
- **Cross-repo surface** — writer unification touches both `vivarium_workbench` and `viva_superpowers`; land Phase 0 (branches) first so there's one moving target.
- **Reconstruct-old-env** (G3 "use older version") can be slow/heavy; Phase 1 documents + provides the mechanism, not necessarily a one-click UI.

## Phasing
- **Phase 0:** land the 3 stranded branches (data-model migration + L0–L5 audit + audit-gate CI).
- **Phase 1 (this spec):** items 1–7 above.
- **Phase 2 (separate spec):** structural content-addressing — promote or delete the dead `lib/artifacts` engine, keyed on `env_id`.

## Relationship to Spine B
Spine B (the "court officers" agent loop) consumes this substrate: the Jury/Judge read certified, env-versioned, fingerprinted runs; `env_stale`/`nondeterministic` become items the agent must address to keep the case admissible. A trustworthy Spine A is the precondition for a trustworthy Spine B.
