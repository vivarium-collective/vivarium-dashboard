# Study Pipeline — Spec 1: Deterministic Execution (artifacts + registry + pipeline)

**Status:** design approved, ready to plan
**Date:** 2026-07-25
**Part of:** the "streamline the study pipeline" initiative (3 specs). This is Spec 1.

## Goal

Make the study pipeline **deterministic, reproducible, and non-redundant** at the
execution layer: studies become location-independent, reusable-across-investigations
units whose outputs are **content-addressed artifacts** (produced once, pulled
everywhere), run through one explicit **pull-or-compute pipeline**.

This is the foundation the later specs rest on:
- **Spec 2 — Evidence spine:** report cards → tests (the atomic evidence) → auto-seeded
  findings (author may enrich, keeps the link) → decisions → conclusion. *Out of scope here.*
- **Spec 3 — Graph/card UI:** auto-derived evidence chain + `decide` folded into the
  investigation card's semantic zoom; studies-tab "in N investigations" badge. *Out of scope here.*

## The problems this fixes

1. **Dual, inconsistent study layout.** 25 studies live in the canonical top-level
   `studies/<slug>/`; 26 others are nested under `investigations/<inv>/studies/<slug>/`.
   `WorkspacePaths` treats root `studies/` as canonical, so nested studies hit a class
   of bugs (e.g. the study viz-glob at `studies/<slug>/viz` misses a nested study —
   the reason a study's figure failed to publish).
2. **A study is owned by one investigation.** It cannot be shared, so identical work
   (e.g. a ParCa `sim_data` fit) is re-authored / re-run per investigation.
3. **Non-deterministic reruns.** Runs resolve inputs like `data_source: latest_run`,
   which drifts over time; nothing pins the exact inputs that produced a result.
4. **Blob duplication.** Run outputs are copied per study with no shared, deduplicated home.

## Model

### 1. Artifacts (content-addressed store)

An **artifact** is a named, immutable output of a study stage — e.g. `sim_data`,
`parca_state`, the run's `zarr`/`parquet`, report-card data. Its identity is a content hash:

```
artifact_id = H( composite_id + canonical(config) + [sorted input_artifact_ids] + workspace_git_commit )
```

- `config` is the study's full config (it **includes `seed`** — see Schema below), hashed
  as `canonical(config)`: JSON with sorted keys and normalized number formatting, so two
  logically-equal configs always hash identically. Input ids are sorted before hashing.
- `workspace_git_commit` is the v2ecoli repo commit that defines the composite/process
  code — the same commit the dashboard already stamps as the source commit. Coarse
  (any repo commit invalidates artifacts) but simple and honest; finer granularity is a
  later refinement, not part of Spec 1.
- Stored once in a workspace-level content-addressed store keyed by hash:
  ```
  .pbg/artifacts/<hash>/
    artifact.bin        # the payload (or a directory for multi-file artifacts)
    meta.json           # { producer_study, kind, inputs:[ids], composite_id, config,
                        #   seed, workspace_git_commit, created_at }
  ```
- **Pull-or-compute:** a consumer that needs an input computes the producer's
  `artifact_id` and pulls it if present, else computes it (recursing up the DAG) and
  stores it. Identical work is never repeated (dedup); same inputs → same hash → same
  bytes (reproducible).
- `studies/<slug>/runs.db` holds only **pointers** (`stage → artifact_id`), never
  duplicated blobs. The store is the single home.

### 2. Study registry + investigations as references

- **All** studies live in `studies/<slug>/`. Nothing is nested under `investigations/`.
- `study.yaml` declares an explicit **interface** (its inputs, what it computes, what it
  emits) — see Schema below.
- `investigation.yaml` becomes a **pure reference**: a `members: [slug, ...]` list. The
  same slug may appear in many investigations (true many-to-many).
- **DAG edges are derived, not hand-drawn:** an edge `parca → ko-and-media` exists
  because `ko-and-media` declares `inputs: [{artifact: sim_data, from: parca}]`. The
  investigation graph is computed from the input chain of its members.

### 3. The deterministic rerun pipeline

A study run is four explicit stages, each producing content-addressed artifacts, each
pull-or-compute:

```
1. RESOLVE INPUTS   for each declared input, compute the producer's artifact_id;
                    pull from the store if present, else run that producer first
                    (recursion up the derived DAG — e.g. sim_data from parca).
2. INITIALIZE       build composite(config) seeded from the resolved input artifacts.
3. SIMULATE         run with the study's declared emitter → run artifact (zarr/parquet).
4. FLUSH            analysis flush → analyses + visualizations + report cards.
```

- **Determinism:** a stage runs only if its `artifact_id` is not already in the store.
  Unchanged study → cached artifact returned, no recompute (rerun is a re-point).
  Change one config value → only stages downstream of it re-run.
- **Reproducibility / sharing:** `sim_data` is pulled by hash, so ParCa runs **once**
  and every investigation referencing it gets identical bytes.
- **Build strategy:** a thin resolver **wrapping the existing engine**
  (`run_runner.execute()` stays the compute). The resolver adds the hash gate + store
  read/write around each stage; it does NOT replace the run subsystem. A full
  artifact-DAG scheduler rewrite was considered and rejected for Spec 1 (YAGNI, risk).

## Study-spec schema (canonical, non-redundant)

```yaml
name: ko-and-media
composite: v2ecoli.composites.baseline.baseline
config: { seed: 0, media: minimal_plus_amino_acids }
inputs:  [{ artifact: sim_data, from: parca }]      # [] if none
outputs: [run_zarr, report_cards]                   # artifacts this study produces
emitter: parquet
# evidence blocks (tests / findings / decisions / conclusion) are Spec 2 — unchanged here
```

```yaml
# investigation.yaml
name: perturbation-demo
members: [parca, ko-and-media]                      # references; edges derived from inputs.from
```

## Migration (one-shot, part of Spec 1)

1. Move each of the 26 nested `investigations/<inv>/studies/<slug>/` into
   `studies/<slug>/` (slug collisions: none today — verified disjoint — but the migrator
   must fail loudly on any future collision).
2. Rewrite each affected `investigation.yaml` to a reference-only `members:` list.
3. Backfill `inputs:`/`outputs:` on migrated studies where derivable (e.g. anything that
   consumes `sim_data` gets `inputs: [{artifact: sim_data, from: <parca-study>}]`);
   leave a clear TODO marker where it can't be inferred rather than guessing.
4. **Guard test:** fail if any `study.yaml` exists under `investigations/` (the dual
   layout can never silently return), mirroring the tracked-symlink guard pattern.

## Out of scope (explicitly deferred)

- Evidence spine: tests/findings/decisions/conclusion derivation (Spec 2).
- Graph/card UI: evidence chain rendering, `decide` in semantic zoom, studies-tab
  "in N investigations" badge (Spec 3).
- Finer code-identity than the workspace git commit (dependency-version or recipe hashing).
- A remote/shared artifact store (mini/GovCloud). Spec 1 is the local workspace store;
  the content-address is the precondition that makes a shared store trivial later.

## Success criteria

- All studies resolve from `studies/<slug>/`; no `study.yaml` under `investigations/`;
  guard test enforces it.
- An investigation references its members by slug; a single study slug is referenced by
  ≥2 investigations in at least one worked example (proves many-to-many).
- Running a study twice with no input change performs **zero** recompute (store hit on
  every stage); changing one config value re-runs only downstream stages.
- `sim_data` produced by ParCa is stored once and pulled by a second study without
  re-running ParCa (verified by store hit + identical artifact_id).
- No run blob is duplicated outside `.pbg/artifacts/`; `runs.db` holds only pointers.
