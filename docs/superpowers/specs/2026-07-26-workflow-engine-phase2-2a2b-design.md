# Phase 2 (2a + 2b) — Typed-Node Resolver + Topological Investigation Execution — Design

- **Date:** 2026-07-26
- **Status:** Draft for review
- **Repo:** vivarium-workbench (the artifacts engine lives here); consumes v2ecoli study data
- **Branch:** `feat/workflow-engine-phase2`
- **Program context:** Phase 1 (data-model canonicalization) MERGED — viva-superpowers #181, v2ecoli #390, workbench #606. The workflow model this builds toward is §4 of the v2ecoli spec `docs/superpowers/specs/2026-07-26-study-reproducibility-contract-design.md` ("the knowledge graph as a workflow"). Spec-1 execution seam: `docs/superpowers/specs/2026-07-25-study-pipeline-spec1-execution.md`.

## 1. Motivation & scope

The first message of this program asked for exactly this: **"studies should run in the order declared by an investigation, so the analysis outputs and results of one study can feed into the next study if there is a dependency … formalize how this is done so it is reproducible."**

Phase 1 made `inputs.from` the single, typed ordering source and left the content-addressed pull-or-compute engine (`lib/artifacts/*`) correct but **wired to nothing**. Phase 2 (2a+2b) delivers the headline: run an investigation's studies in **topological order over `inputs.from`**, forwarding each study's output artifact to its consumers, with **content-addressed caching** so a rerun recomputes only what changed.

**In scope (2a + 2b):**
- **2a** — complete + generalize the resolver so it runs *real* study nodes and resolves a whole investigation's DAG topologically. Offline/library, fully tested. No endpoint wiring.
- **2b** — wire an **opt-in** topological investigation-execution path into the API, with the current declared-order path retained as the default/fallback, and surface cache-hit vs computed per node.

**Out of scope (deferred to 2c/2d):** report-card verdict nodes, evidence-chain-from-computed-nodes, intra-study sub-node typing (flush/test/finding/decision/conclusion). This spec's "nodes" are **study-run nodes** — each study is one node that consumes its `inputs.from` producer artifacts and produces one run artifact.

## 2. Current state (grounded 2026-07-26)

- `lib/artifacts/pipeline.py::resolve_study(ws_root, slug, *, compute_fn=None)` — recursive pull-or-compute: resolves each `inputs[].from` producer first (recursion), hashes `artifact_id(composite_id, config, sorted(input_ids), commit)`, `store.has(oid)` → reuse else compute-once → `store.put`. Correct, tested, **no production caller** (test-only).
- `_default_compute` **already reaches the real engine** (`run_core.invoke_run` → `run_runner.execute`) but is a self-described seam: it passes **placeholder `emit_paths=[]`** and does **not forward resolved input artifacts** into the run. No cycle detection.
- `ArtifactStore` (rooted at `.pbg/artifacts/`), `hashing.artifact_id` — complete.
- Live execution: `/api/investigation-rerun` → `lib/rerun.rerun_investigation` re-runs each member's baseline in **declared/member order**; `investigations.run_investigation` iterates `runs` in file order. **No `graphlib`/toposort anywhere in the live path.**
- The dependency data needed exists: `study_spec.study_interface` exposes `inputs[].from` + `outputs`; `investigation_graph_views.build_investigation_graph` already builds study→study edges from member `inputs.from`.

## 3. Design — 2a: typed study-run resolver + topological investigation resolver

### 3.1 Complete `_default_compute` (real run nodes)

Two gaps to close so a computed node is a *real* run:
1. **emit_paths from the study's declared outputs/readouts.** Derive the run's `emit_paths` from the study's `outputs` (and/or readouts) instead of `[]`. A study's output artifact = its run store (the emitter output); the produced artifact the store persists is the run's emitter output dir. Concretely: `emit_paths` come from the study's declared observables/readouts (reuse `study_spec`/readout resolution); if a study declares none, fall back to the full emit (current behavior) — but record that.
2. **Forward resolved input artifacts into the run.** For each `inputs[].from` producer, the resolver already has the producer's `artifact_id` (and thus its stored artifact). Pass those into the run request as **input state** (e.g. a producer's `sim_data`/run-store artifact becomes the consumer run's initial input). The mechanism: extend the run-request dict `_default_compute` builds with an `inputs: {artifact: <store path>}` map that `run_runner.execute` reads. (Exact wiring of input-artifact → composite input port is the main implementation question — see §6.)

### 3.2 Cycle detection

`resolve_study` recursion must detect cycles in `inputs.from` (Phase 1's guard asserts the DAG is acyclic for v2ecoli, but the engine must be safe generally). Track an in-progress set on the recursion stack; raise a typed `CyclicDependencyError` naming the cycle.

### 3.3 `resolve_investigation(ws_root, inv_slug, *, compute_fn=None) -> InvestigationResult`

New library entry point:
- Read the investigation's members (`investigation_member_slugs` = `members or studies`).
- Build the study→study DAG from each member's `inputs.from` (restricted to members + known upstream producers like `parca`).
- **Topologically order** (via `graphlib.TopologicalSorter`) and `resolve_study` each member in order — which, through the existing recursion + `store.has` gate, is pull-or-compute with artifact forwarding.
- Return a per-node result: `[{slug, artifact_id, status: cached|computed|skipped|failed, inputs: [...]}]` + the topological order + any `CyclicDependencyError`.
- A node whose upstream failed is `skipped` (not computed) — surfaced, never silently dropped.

### 3.4 Node identity (reproducibility — unchanged, reused)

`artifact_id = H(composite_id + canonical(config) + sorted(input_artifact_ids) + workspace_git_commit)`. Because a consumer's `input_ids` are its producers' `artifact_id`s, a change anywhere upstream re-keys everything downstream; an unchanged subgraph is all cache hits. **Reproducibility is structural**: same inputs+config+code ⇒ same id ⇒ reuse. (Carry over the Spec-1 follow-up: config MUST include seed so two studies differing only by seed don't collide — verify against the migrated study configs.)

## 4. Design — 2b: opt-in topological execution endpoint

- **New endpoint** `POST /api/investigation-resolve` (name TBD) → `resolve_investigation`. Body: `{investigation, force?: bool}`. `force` bypasses the cache (recompute all). Returns the per-node result from §3.3.
- The existing `/api/investigation-rerun` (declared-order, no caching) **stays as the default**; the engine path is **additive and opt-in** — no existing behavior changes. (A later increment can flip the default once proven.)
- **Surface cache-hit vs computed** in the response and (minimally) in the UI: the investigation view can show, per study, "reused" vs "recomputed (N upstream changed)". Full UI is 2d; 2b just returns the structured result + a minimal indicator.
- Runs are **detached subprocesses** exactly as today (`run_runner.execute`), so long runs outlive the request; `resolve_investigation` orchestrates ordering + gating, not in-request blocking. (Execution model detail — see §6: sync-resolve-then-detach vs a job that walks the DAG.)

## 5. Testing

- **Unit (offline, injected `compute_fn`)**: topological order correct for a diamond DAG; cache hit on unchanged rerun; upstream change re-keys downstream; cycle → `CyclicDependencyError`; upstream failure → downstream `skipped`; seed-in-config prevents false cache hits.
- **Real-data integration** on a migrated v2ecoli chain (e.g. `parca → baseline → {downstream}`): resolve twice → second run all cache hits (0 recompute); change one study's config → only it + its descendants recompute; artifacts land in `.pbg/artifacts/`.
- **Non-regression**: `/api/investigation-rerun` (declared-order path) unchanged; existing artifacts tests still green.

## 6. Open questions (resolve in the plan)

- **Input-artifact → composite input port wiring**: how a producer's stored artifact (e.g. `sim_data` from parca) is injected as the consumer run's input. Options: (a) pass the artifact store path in the run request and have `run_runner` load it as initial state; (b) a producer declares a named output artifact that the consumer's config references. Grounded against how v2ecoli currently consumes `sim_data` (ParCa output) in a baseline run.
- **emit_paths derivation**: exact source (study `outputs` vs readouts vs full-emit fallback) and whether a study's "output artifact" is the whole run store or a projected subset.
- **Execution model for 2b**: does the endpoint resolve the DAG synchronously (spawning detached runs per node, waiting for each before the next) or enqueue a DAG-walking job? Topological execution needs a node to finish before its consumers start — so some orchestration/waiting is required. Decide sync-orchestrator-process vs job-manager integration.
- **Seed-in-config precondition** (Spec-1 follow-up): confirm migrated study configs carry seed under `config`/`params` so `artifact_id` distinguishes seeds.

## 7. Risks & mitigations

- **Live execution blast radius** → the engine path is opt-in/additive; declared-order path is the untouched default; heavy real-data testing before any default flip.
- **False cache hits** (seed/config not in the hash) → §6 seed-in-config check + a test that two seeds don't collide.
- **Long/hung runs in a DAG walk** → per-node timeout + `failed`/`skipped` propagation surfaced, never silent.
- **`_default_compute` correctness on real studies** (emit_paths/input forwarding) → integration test on a real parca→baseline chain before wiring the endpoint.

## 8. Decomposition into implementation increments

1. **2a-1** — cycle detection + `resolve_investigation` topological ordering (offline, injected compute_fn). Pure, fully unit-tested.
2. **2a-2** — complete `_default_compute`: emit_paths from outputs + input-artifact forwarding (resolve §6 wiring); real-data integration test on a parca→baseline chain.
3. **2b-1** — `POST /api/investigation-resolve` endpoint + detached DAG-walk execution + per-node cache/compute result; declared-order path untouched.
4. **2b-2** — minimal UI surface (per-study reused/recomputed indicator) reading the endpoint result.
