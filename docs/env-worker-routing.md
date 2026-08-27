# What runs in an env worker, and what must be dispatched

**Status: design, not implemented** (REFACTOR-PLAN §2A.8 workstream 8). Written
after the image-as-worker arc landed and the first real launches exposed how the
question is usually asked backwards.

Companions: [`env-worker-runtime.md`](env-worker-runtime.md) is what exists today;
§2A.7 draws the line this proposes to enforce; §2A.8 is the hosted-environment
decision.

---

## The problem

`get_pool().call(...)` has **25 call sites** carrying **19 distinct methods**.
Some are interactive lookups; some run simulations. On a hosted deployment the
worker is a pod sized for interaction — `250m`/`512Mi` requested, `1`/`2Gi`
limit — and a real study on this system declares:

```
item35-closing-pilot-8d50ff0-2x10    n_seeds:2     n_generations:10  →      20 sims
item1-baseline-1000x10               n_seeds:1000  n_generations:10  →  10,000 sims
```

Both live in the same repo, in the same `study.yaml` shape, reached through the
same entrypoints. The first belongs in a worker. The second is an OOMKill.

Wiring the pool to the remote launcher without addressing this would route the
second into a 2 GiB pod. **The routing question must be answered first.**

## What can and cannot be known before running

Three cases, and they are genuinely different:

| | cost signal | can we know a priori? |
|---|---|---|
| **Study / baseline runs** | `n_seeds` × `n_generations`, declared in `study.yaml` | **Yes, exactly.** No inference — the spec says so. |
| **Bare composite runs** | `steps` (`run_composite`), `interval` (`run_process`) | **No.** `steps` bounds the *loop*, not the per-step cost: 5 steps of `reference_demo_x2y2` and 5 of `ecoli_baseline` differ by orders of magnitude. |
| **Everything else** (`registry_catalog`, `attach_process_docs`, …) | — | **Not needed.** These are lookups by construction. |

A `@composite_generator` is arbitrary Python, so for the middle row there is no
predicate to write. **Any "is this expensive?" heuristic keyed on the composite
reference would be wrong in both directions, and wrong silently.** That is the
one option this design rules out.

The system has already collided with this. `env_worker_pool`'s own comment records
a multi-generation `ecoli_baseline` at "default 2700 steps, ~minutes" blowing the
60 s call timeout → `EnvWorkerUnavailable` → respawn → fail; the resolution was to
make the timeout **config-overridable so such workloads can raise it**. So a cost
bound already exists — it is just expressed as a ceiling to be raised rather than
a signal to dispatch.

## Proposal — invert the question

Stop asking "is this expensive?" and state what the worker is *for*, so violations
are loud instead of fatal.

### 1. The worker's budget is its contract

§2A.7 already says the worker answers **interactive** queries and that heavy work
is a **job**. Make the limits say the same thing: the call timeout and the pod's
memory ceiling *are* the cost policy — stated as limits, not predictions. Anything
exceeding them is, by definition, not an interactive query.

### 2. Classify by **method** at the pool, not by call site

`WorkerPool.call(workspace, method, params)` sees the method name and is the single
choke point all 25 sites pass through. §2A.7's distinction is method-shaped
(`registry_catalog` vs `run_study`), so encode it there:

- **interactive** → the deployment's launcher (remote when hosted)
- **job-class** (`run_study`, `run_study_analyses`, `run_investigation_analysis`,
  `run_process`, …) → **local worker, or refuse on hosted** with a message naming
  the dispatch path

This is deliberately robust to an incomplete audit: a call site nobody traced
still cannot route heavy work into an undersized pod. (Of the 8 job-class sites,
4 have been traced; `investigation_steps` dispatches `run_study` to the worker with
**no run-target gate at all**.)

### 3. Precheck declared scale where it exists

On the study path, multiply `n_seeds × n_generations` **before** starting and
route or refuse above a configured threshold. Exact, cheap, and it catches the
10,000-sim case *up front* — failing after forty minutes is far worse than failing
immediately.

### 4. Make the budget failure say what to do

Where scale is not declared, the timeout is the only honest mechanism — but it
should surface as *"this exceeded the interactive budget; dispatch it via …"*
rather than `EnvWorkerUnavailable`, which reads as an infrastructure fault and
invites raising the ceiling again.

## Explicitly not doing

- **Guessing cost from the composite reference.** No allow-list of "cheap"
  composites, no name matching.
- **Papering over an undispatched heavy path by routing it somewhere plausible.**
  Silently running `item1-baseline-1000x10` anywhere is the outcome to prevent.

## What this does not fix

Routing is not dispatch. Application paths written when a study run was small
still need to resolve the run target the way the study-run path already does —
`resolve_run_target()` exists precisely for this, and backlog item 18 records the
same failure once before: *"a deployment-wide pin with no session build silently
fell through to a local subprocess on the study-run path."* `investigation_steps`
is the known instance; the remaining 4 untraced job-class sites should be audited.

That is application work, separate from this. **A loud refusal at the pool is what
makes it discoverable rather than silent.**

## Open question — let the author declare it

The knowledge lives with whoever wrote the composite or study. A declared
execution class (`interactive` / `job`), carried the way `analyses` and
`observables` already are, would replace inference with a fact. That is a schema
change and a separate decision — noted here because every mechanism above is a
proxy for it.

## Suggested order

1. Method classification at the pool + the refusal message *(small, safe, and it
   makes everything below discoverable)*
2. Declared-scale precheck on the study path
3. Budget-failure message
4. Audit the remaining job-class call sites for run-target resolution
5. *(separate)* author-declared execution class
