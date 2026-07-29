# Unifying the Vivarium Workbench on bigraph-schema + process-bigraph

**Status:** Design (umbrella architecture)
**Date:** 2026-07-29
**Scope:** Cross-repo — `bigraph-schema`, `process-bigraph`, `vivarium-workbench`, plus a v2ecoli adoption pass. This is the *umbrella* spec; each numbered layer in §7 gets its own implementation-plan spec in its owning repo.

---

## 1. The unifying claim

Every workbench object — a **study**, an **investigation**, a **template** — becomes a
**bigraph-schema-typed document** that **process-bigraph executes as a step network**.
There are exactly **three new or lifted primitives**; everything else is composition of
machinery that already exists.

The bespoke, imperative workbench orchestrators (`run_runner.py`, `composite_flush.py`,
`investigation_run_views.py`) collapse onto process-bigraph's step-network engine. The
endpoint's job shrinks to: *build the composite document → hand it to the engine → read
the artifacts*.

## 2. Current state — the substrate that already exists

This refactor is more **unification than green-field**. What is already in place:

- **The step-network engine.** process-bigraph already runs a pure network of Steps as a
  DAG to completion (`Composite.run(0.0)` / `run_steps_on_init` / `wire_step_layers` in
  `process_bigraph/scheduling.py` + `composite.py`). Each Step fires when its **producer
  stores** are satisfied (`scheduling.build_step_network`, `determine_steps`). *This is the
  "workflow" engine we need — we do not build one.*
- **Emitters are already Steps.** `process_bigraph/emitter.py` — `Emitter(Step)`, with
  `RAMEmitter`/`JSONEmitter`/`ConsoleEmitter` in-repo and `ParquetEmitter`/`SQLiteEmitter`
  re-exported from `pbg-emitters`; `XArrayEmitter` lives in `pbg-emitters`. `gather_emitter_results(composite, queries)` is already the "pull the results" operation.
- **Report cards / viz / analysis are already Steps.** `v2ecoli/workflow/post_sim.py`:
  `ReportCardStep(V2Step)`, `Visualization(V2Step)`, a `POST_SIM_REGISTRY`, concrete cards
  under `v2ecoli/workflow/report_cards/`. Today they are driven by an **imperative** flush
  loop (`v2ecoli/workflow/flush.py`'s `RunExtract` + `iter_post_sim`), *not* as a step
  network.
- **A proto-template.** `process_bigraph/composite_spec.py::CompositeSpec` already unifies
  `@composite_generator` (`viva_superpowers/composite_generator.py`) and
  `*.composite.{yaml,json}`, and already carries `parameters` (flat `${name}` substitution),
  `visualizations`, `analyses`, `emitters`. It is ~70% of "template".
- **The generics substrate.** bigraph-schema has typed parameters `type[X,Y]` resolved by
  `methods/handle_parameters.py::align_parameters`/`reify_schema`. No first-class `Template`
  node exists yet — that is the one genuinely new primitive.

Prior-art docs to stay consistent with:
`process-bigraph/docs/superpowers/plans/2026-06-28-composite-spec-unified-declaration.md`
and `v2ecoli/docs/superpowers/specs/2026-06-29-study-report-card-modules-design.md`.

## 3. Decisions locked in brainstorming

1. **Artifact of this brainstorm:** one umbrella architecture spec (this doc), then a
   sequenced stack of per-layer implementation plans.
2. **On-disk model:** studies/investigations become **native composite documents** on disk
   with a **one-shot migrator** from the existing `study.yaml` / `investigation.yaml`
   (~250 studies, 13 investigations).
3. **Study execution:** **two-phase composite** — a temporal Phase 1 (sim + emitter) and a
   pure-step Phase 2 (flush), separated by a durable barrier.
4. **Emitter seam (refinement):** the emitter is the durable phase boundary; an explicit,
   **emitter-polymorphic extractor substep** bridges emitter → normalized `results` →
   flush entities.
5. **Investigation gating:** a failed prerequisite **blocks** its dependents — gating falls
   out of normal step-triggering over gate stores.
6. **Templates:** **multi-slot from the start** — N typed slots, 0+ of type `composite`.

## 4. Architecture

### Layer 0 — bigraph-schema: the `template` primitive *(the one new thing)*

A **template** is a schema with named, typed **slots** (holes), at least one of type
`composite`. Filling the slots produces a concrete composite document.

- Generalizes `CompositeSpec.parameters` (flat `${name}` string interpolation) into **typed
  slots resolved through the existing `align_parameters`/`reify_schema` machinery**, so a
  slot value may be a scalar *or* a whole composite subtree.
- **Multi-slot:** a template declares N slots; a single-composite study template is the N=1
  case, a comparison template (model-under-test vs. reference) is N=2. `reify_schema` already
  handles multiple parameters, so this costs little.
- A **template study** = a template whose composite slot(s) bind the model(s)-under-test to a
  standard analysis-flush sub-network. Drop any registered composite (`ecoli_baseline`,
  `viva_munk.biofilm`, `pbg_copasi.steady-state`) into a slot → a runnable study with
  viz/analysis/report cards.
- **Home:** bigraph-schema, because the mechanism is generic and every layer above consumes
  it; and because the user explicitly wants templates there.

### Layer 1 — process-bigraph: Study = a two-phase composite

One study composite document, internally two-phase, with the **emitter as the durable seam**:

```
Study Composite
  Phase 1 (temporal):
    sim composite(s)  ──emit──►  emitter (declared, interchangeable: RAM | Parquet | XArray-zarr)
                                    │  persists → runs.db / zarr
                ── barrier (durable) ──
  Phase 2 (pure step network, run(0.0)):
    [extractor substep]  ── reads emitter (any kind) ──►  results store  (xarray + sim_data context)
    results ──►  [ viz_* | analysis_* | report_card_* ]  (flush entities, fire as a DAG)
                                                    └──►  artifacts/   ← study OUTPUT
```

- **Phase 1** runs the selected sim composite(s) with a *declared, interchangeable* emitter
  attached. The emitter is the persistence boundary (`runs.db`/zarr).
- **The extractor substep** is a first-class Step that is **emitter-polymorphic**: it knows
  how to query *whatever* emitter was used (generalizing `gather_emitter_results` across
  RAM/Parquet/XArray) and materialize the single standardized **`results` handle** (today's
  `RunExtract` context: xarray + `sim_data`). The flush entities never touch the raw
  emitter — only the normalized `results`. Emitter-interchangeability is absorbed here, once.
- **Phase 2** wires the existing viz/analysis/report-card Steps to the `results` store; they
  fire as a DAG (`run(0.0)`), writing artifacts.
- **Study output = the artifact set** (verdicts, cards, figures, analyses).
- **Ownership split:** the *generic* machinery (two-phase runner, the `results` contract, the
  extractor substep, assembling the flush network from a composite's declared
  `visualizations`/`analyses`/`report_cards`) lives in process-bigraph; the *domain* Steps
  (v2ecoli's cards, viva_munk's viz) stay in their packages and self-register via the existing
  discovery mechanism.

### Layer 2 — process-bigraph: Investigation = a composite

Studies are **step nodes**; `pipeline_gate.prerequisites` become **store wiring**:

- An upstream study writes a `gate/<slug>/verdict` store on completion.
- A downstream study step lists that store among its trigger inputs; it fires **only when the
  prerequisite gate stores read `passed`**. A failed prerequisite blocks its dependents — they
  do not run.
- **No separate gate evaluator:** gating is exactly process-bigraph's producer/consumer
  triggering. Membership (`members:`) + the DAG (`prerequisites`) collapse into one composite
  document. The investigation runs on the *same* engine.

### Layer 3 — workbench: consume, don't reimplement

- `study.yaml` / `investigation.yaml` → native **composite documents** on disk (e.g.
  `study.composite.yaml`, an instance of a template or a bare composite), with a one-shot
  migrator.
- `run_runner.py` / `composite_flush.py` / `investigation_run_views.py` shrink to
  "build the composite doc → engine → read artifacts."
- UI renders the composite graph + its artifacts (much of the read-side —
  `single_study_report.py`, `study_charts.py` — stays, now reading engine-produced artifacts).

### Cross-cutting — bigraph-schema as the registry

`study`, `investigation`, `template`, `slot`, and the emit-pull/flush step vocabulary all
**register as bigraph-schema types**. Discovery already surfaces `Edge` subclasses as
`step`/`process` links, so most of this is registration, not new type machinery. This is the
"everything under one framework" endpoint.

## 5. Key contracts (the interfaces that must be nailed)

1. **The `results` handle** (Phase-1 → Phase-2 boundary). A normalized, emitter-independent
   object: time-indexed xarray of emitted state + `sim_data`/context. Formalizes today's
   `RunExtract.context_bag()`. Every flush entity consumes *only* this.
2. **The extractor substep** (emitter adapter). Input: a reference to the finished run's
   emitter/store. Output: the `results` handle. One implementation per emitter kind, selected
   by the emitter the composite declared.
3. **Template / slot schema.** A template document: N named slots each with a type (scalar
   types or `composite`), optional defaults, and a body schema referencing the slots. Binding =
   `reify_schema` fill → concrete composite document.
4. **Study composite document.** The on-disk native form: which sim composite(s) + params, the
   emitter, the bound flush entities, expected-behavior/tests. Produced by the migrator or by
   instantiating a template study.
5. **Investigation composite document + gate stores.** Studies-as-steps, `gate/<slug>/verdict`
   store convention, prerequisite→trigger wiring.

## 6. Migration strategy

- **Native composite documents are canonical**; a **one-shot migrator** converts the existing
  ~250 `study.yaml` (schema_version 4) and 13 `investigation.yaml` (schema_version 2) into
  composite documents. The migrator reuses the existing normalizers (`study_spec.study_interface`,
  `investigations.normalize_dag_edges`) as the *reader* side so semantics are preserved.
- Migration is per-workspace, reversible via git (workbench already commits workspace mutations
  to a branch), and dry-run-able (mirror `migrate-investigations`).
- Existing published/read-only bundles keep rendering (Layer 3 read-side is preserved); only the
  *authoring + run* path moves onto the engine.

## 7. Repo ownership & the sequenced sub-spec stack

Each becomes its own spec → plan → implementation cycle, in this order (later layers depend on
earlier):

1. **bigraph-schema — `template`/`slot` primitive.** Keystone; everything depends on it.
   *(spec lands in bigraph-schema)*
2. **process-bigraph — Study two-phase composite.** The `results` contract, the
   emitter-polymorphic extractor substep, and flush-network assembly; replaces the imperative
   flush/run cores. *(spec lands in process-bigraph)*
3. **process-bigraph — Investigation composite.** Gating-as-wiring (block semantics), gate-store
   convention. *(spec lands in process-bigraph)*
4. **vivarium-workbench — migrator + orchestrator slimming + UI.** Native composite docs on
   disk; endpoints delegate to the engine. *(spec lands in vivarium-workbench)*
5. **v2ecoli — adoption pass.** Prove the whole stack end-to-end on one real study and one real
   investigation; register the domain flush Steps against the new assembly.

## 8. Risks & things to watch

- **The "fire once after the sim" subtlety is deliberately avoided** by the two-phase barrier;
  do not let Phase-2 steps get wired to per-tick emitter updates.
- **Emitter polymorphism** is the crux of the extractor substep — the `results` contract must be
  rich enough that no flush entity ever needs the raw emitter. If a flush entity needs something
  the contract lacks, extend the contract, not the entity.
- **CompositeSpec vs. template overlap:** the template primitive must *subsume* `CompositeSpec`'s
  `parameters`, not duplicate it. Layer 1 of the stack decides whether `CompositeSpec` becomes a
  thin adapter over the bigraph-schema template or is refactored into it.
- **Cross-repo release choreography:** bigraph-schema → process-bigraph → workbench → v2ecoli is
  a dependency chain; each sub-plan must state its minimum upstream version.
- **~250 studies** means the migrator is load-bearing; it needs a golden-file test corpus.

## 9. Out of scope (YAGNI)

- Rewriting the read-side renderers (`single_study_report.py`, `study_charts.py`) — they keep
  working against engine-produced artifacts.
- A new emitter format — the extractor adapts to existing emitters.
- Distributed/remote execution of the step network (Nextflow export already exists if needed).
- Non-composite investigation features (executive summaries, glossaries) — carried through as
  document metadata, unchanged.
