# Unifying the Vivarium Workbench on bigraph-schema + process-bigraph

**Status:** Design (umbrella architecture)
**Date:** 2026-07-29
**Scope:** Cross-repo — `bigraph-schema`, `process-bigraph`, `vivarium-workbench`, plus a v2ecoli adoption pass. This is the *umbrella* spec; each numbered layer in §7 gets its own implementation-plan spec in its owning repo.

---

> *Revised 2026-07-30 after the Fable architecture review
> (`~/AI-Generated/2026-07-30-architecture-unification-review-fable.md`): one operation
> (`fill`), one law (`is_ground`). Gating is conditional filling, not scheduling; the
> two-phase barrier is deleted (the emitter gains a `results` port).*

## 1. The unifying claim

> **There is one object: a bigraph — a typed document whose place graph is dict nesting,
> whose link graph is `Link` nodes with faces and wires, and whose holes are sorted
> sites. There is one operation: `fill` — substitute fillers into named open sites. There
> is one law: a document is runnable exactly when it is *ground* (no open sites).**

A **process** is a ground document; a **composite** is a document whose sites were filled
by other documents (which is why `Composite` *is* a `Process` — composition is closed); a
**template** is a document that is not yet ground; a **study** is a template with its
model site filled; an **investigation** is a document with one site per dependent study,
filled at runtime by gate edges. There is **one** new primitive — `fill` (and its
predicate `is_ground`); everything else already exists.

The bespoke, imperative orchestrators (`run_runner.py`, `composite_flush.py`,
`investigation_run_views.py`) collapse onto the step-network engine. The endpoint's job
shrinks to: *fill the document → hand it to the engine → read the artifacts*. Shared
vocabulary is the glossary (review §3.4): **site, sort, admits, formation, face, wires,
fill, compose, ground, template, document, edge, reaction, results, artifact**.

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
3. **Study execution:** **one step network** — no phases, no barrier. `Emitter` gains a
   `results` output port, so the extractor and flush entities are ordinary downstream steps.
4. **Emitter seam:** the emitter's `results` port carries the durable handle
   (store ref + `sim_data` context); the **emitter-polymorphic extractor** is a normal step
   that reads it. Durability is a property of one edge, not a stage of the engine.
5. **Investigation gating:** gating is **conditional filling**, not scheduling.
   `determine_steps` force-runs remaining steps and never inspects a value, so triggering
   alone cannot block. A failed prerequisite leaves the dependent's **site open** →
   non-ground → never built. Gating and template binding are the same mechanism.
6. **Templates:** a template is **a document that is not ground** — N open sites, filled by
   `fill`. Not a new type.

## 4. Architecture

### Layer 0 — bigraph-schema: `fill` + `is_ground` *(the one new thing)*

The single new primitive is **`fill`** — substitute fillers into a document's named open
**sites** — plus its predicate **`is_ground`**. A **template** is simply a document that is
not ground; there is **no** `Template`/`Slot` type and `BASE_TYPES` gains nothing. See the
Layer-1 spec (`bigraph-schema/docs/superpowers/specs/2026-07-30-template-slot-primitive-design.md`).

- `assembly.instantiate` (`assembly.py:1044`) already performs named-site substitution;
  `fill` = it + a per-site `admits` check (face-conformance / value-check). `compose` becomes
  a two-line adapter (positional `fill`). Register as `core.fill_sites` — **`Core.bind`
  already exists** and must not be shadowed.
- A site's **name is its key**; its **sort** constrains its filler. A `${name}` scalar and a
  model subtree differ only in sort — one kind of site, not three.
- A **template study** = a document whose model site is face-constrained; drop any conforming
  registered composite (`ecoli_baseline`, `viva_munk.biofilm`, `pbg_copasi.steady-state`) into
  it → a runnable study.
- **Home:** bigraph-schema — the mechanism is generic and every layer consumes it.
- **Blocking prerequisite:** the `compose` link-branch is untested and its wire target is
  suspect (Layer-1 §2/§6 Task 0) — prove it on a real wired document before building up.

### Layer 1 — process-bigraph: Study = one step network

One study document, **one** network — no phases, no barrier. The barrier was an artifact of
a one-line omission: `Emitter.update` returns `{}` (`emitter.py:159`), so
`build_step_network` gives an emitter no outputs and nothing can depend on it. **Fix: give
`Emitter` one output port, `results`**, written at finalize, carrying the durable handle
(store ref + `sim_data` context). Then everything downstream is an ordinary edge:

```
Study document (one step network, run(0.0)):
  sim composite(s) ──emit──► emitter [results ●] ──► [extractor] ──► results store (xarray + sim_data)
                               │ persists → runs.db/zarr        results ──► [ viz_* | analysis_* | report_card_* ]
                                                                                        └──► artifacts/  ← study OUTPUT
```

- The emitter's **`results` port** is the persistence boundary *and* a normal producer store;
  the **extractor** is an ordinary downstream step (emitter-polymorphic, generalizing
  `gather_emitter_results`) that materializes the standardized **`results` handle** (today's
  `RunExtract` context). Flush entities read only `results`, never the raw emitter.
- The composite's declared `visualizations`/`analyses`/`report_cards` are just edges wired to
  `results` — **the step network *is* the flush DAG**; no separate flush assembler exists.
- Durability is a property of one edge, not a stage of the engine — so "one engine" is
  *literally* true, not approximately.
- **Study output = the artifact set** (verdicts, cards, figures, analyses).
- **Ownership split:** the *generic* machinery (two-phase runner, the `results` contract, the
  extractor substep, assembling the flush network from a composite's declared
  `visualizations`/`analyses`/`report_cards`) lives in process-bigraph; the *domain* Steps
  (v2ecoli's cards, viva_munk's viz) stay in their packages and self-register via the existing
  discovery mechanism.

### Layer 2 — process-bigraph: Investigation = a composite (gating = conditional filling)

An investigation is a document with **one open site per dependent study**. Gating is
**conditional filling, not scheduling** — `determine_steps` (`scheduling.py:473`) orders
steps by producer/consumer dependency, has no value predicate, and force-runs remaining
steps to break cycles, so triggering alone *cannot* block a dependent.

- The gate edge for study *A* does not write a boolean; it **emits a filler**. On `passed` it
  fills *B*'s site with *B*'s subtree; on `failed` it leaves the site **open**.
- An open site ⇒ the region is **not ground** ⇒ it is never built and therefore never runs.
  This deletes the `gate/<slug>/verdict` convention and any gate evaluator.
- **Gating and template binding are the same mechanism** (`fill` + `is_ground`), so the
  investigation layer is *literally* the template layer. The blocked study also renders for
  free: a study whose site is still open (the ProcessCard viewer, presentation side).

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
3. **`fill` + sites.** A template document = a non-ground document with named, sorted sites
   (name = key; sort = a value type or a face). `fill(core, body, bindings)` substitutes
   admissible fillers into named sites → a ground document. `is_ground` is the runnable
   predicate. (See Layer-1 spec; register `core.fill_sites`, not `core.bind`.)
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
- **The migrator emits *ground* documents and does not depend on Layer 1** — a study is a
  ground document; templates are introduced only where migration output shows measured
  duplication. This decouples the load-bearing ~250-study path from the newest primitive and
  lets the corpus tell us what the templates should actually abstract.

## 7. Repo ownership & the sequenced sub-spec stack

Each becomes its own spec → plan → implementation cycle, in this order (later layers depend on
earlier):

1. **bigraph-schema — `fill` + `is_ground`.** Keystone; everything depends on it. Blocking
   Task 0: prove `compose` on a real wired document. *(spec lands in bigraph-schema — PR #174)*
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
- **CompositeSpec vs. template overlap (resolved, Layer 2a):** `CompositeSpec`'s `parameters`
  refactor onto `fill` — each `${name}` becomes a site; `substitute_parameters` is deleted. The
  `CompositeSpec` surface stays as the ergonomic authoring API; only its resolution swaps. A
  golden corpus (every `*.composite.{yaml,json}` + the 13 v2ecoli generators) guards byte-identity.
- **Untested `compose` link-branch** is the real foundational risk — Task 0 gates the whole stack.
- **`Composite.__init__` must enforce `is_ground`** (Layer 2a A0) — the contract is otherwise
  unchecked at the one place it is consumed.
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
