# Consolidating run orchestration

**Status:** proposed 2026-08-27, **revised 2026-08-28** against the two API
surveys — see [§A0](#a0--what-the-surveys-changed-added-2026-08-28) for what
changed and why. Follows §2A.8 workstream 8 steps 1 and 2a (#952, #954, #957),
which are built and deployed to `sms-api-stanford-test`.

## The problem

The workbench has **three investigation orchestrators that disagree about where
work runs**, so a fix applied to one silently misses the others:

| path | orchestration | honors `resolve_run_target` |
|---|---|---|
| `/api/investigation-run-unblocked` | `run_jobs` manager — thread, 202 + poll | **yes**, via `study_runs` |
| `/api/investigation-run` | inline `textwrap` script + `subprocess`, **synchronous** | **no — zero references** |
| `prepare-investigation` CLI | pbg composite, blocking `StudySteps` | refuses since 2a (#957) |

`remote_pinned.resolve_run_target` is the user's own local-vs-deployment choice —
set by which workspace they picked (a session build stamps `.viv-build.json`), or
by `VIVARIUM_WORKBENCH_REMOTE_PINNED`, which `sms-api-stanford-test` sets for
*every* workspace. Measured there:

| | pin | base workspace | materialized build |
|---|---|---|---|
| hosted (`sms-api-stanford-test`) | **on** | `deployment` | `deployment` |
| laptop | off | `local` | `deployment` |

So on that deployment today, **"Run investigation" executes on the workbench host
regardless of what the user chose.** `investigation_run_views.py` contains no
reference to `resolve_run_target`, `invoke_run`, or `target`.

Step 2a (#957) closed this bypass for `investigation_steps` — the pbg composite
path — but could not see `/api/investigation-run`, which never touches
`WorkerPool`. That is the limit of the pool-as-choke-point argument: it protects
worker calls, and this path does not make one.

## What already works

`run_jobs` is closer to the destination than it looks:

| piece | state |
|---|---|
| job manager singleton, `submit()` → `job_id`, 202 | **built** |
| one daemon thread per job, per-item status, crash capture | **built** |
| status polling — `GET /api/investigation-run-unblocked-status` | **built** |
| gating — `enumerate_unblocked` | **built** (human gate, not a DAG — see A3) |
| dispatch — `study_runs` → `invoke_run` → `run_runner._execute_remote` → `/compose/v1` | **built** |
| concurrency | not built (sequential `for` in `_worker`) |
| durability | not built (in-memory dict) |

The consequence worth stating: **"auto-dispatch" needs no new machinery.**
`run_runner.execute` already branches on `req.target == "deployment"` into
`_execute_remote`, which exports the composite, submits to `/compose/v1`, polls,
and lands `results.zip` — writing the same `composite-runs.db` rows the local path
does, so browser polling is unchanged.

The blocking-vs-async question that appeared open only existed *inside* the pbg
composite, where a `StudyStep.update()` would have to hold a scheduler thread for
the life of a Batch job. Outside pbg the question dissolves: jobs are async by
construction, and a dispatched run is an item that takes longer.

## Decisions

1. **`run_jobs` is canonical.** The pbg composite stays reachable from
   `prepare-investigation` but is not the default.
2. **Durable, with reconcile on boot.** A dispatched Batch run still in flight
   after a restart is re-attached, not orphaned.
3. **The viva-api relay is in scope as a design**, gated on a real need before
   being built.

---

## A. Consolidate on `run_jobs`

### A0 — What the surveys changed *(added 2026-08-28)*

Reading this plan against [`workbench-api-survey.md`](workbench-api-survey.md) and
[`ui-api-consumption-survey.md`](ui-api-consumption-survey.md), then tracing the
UI and viva-api, turned up four things that revise it.

**1. `/api/investigation-run` is synchronous, and that is a second defect.**
The two orchestrators are two *buttons* with different shapes, both in
`walkthrough.js`:

| UI action | endpoint | shape |
|---|---|---|
| "Run unblocked" | `/api/investigation-run-unblocked` | async — 202 + `job_id`, polls status every 2 s into an `investigation-run-progress` panel |
| "Run" (investigation detail) | `/api/investigation-run` | **blocking fetch** — `_runInvestigation` disables the button, sets "Running…", and waits for every simulation |

The handler runs the orchestration **inline in the request**. The dev ALB's idle
timeout is **60 s** (`smsvpc-Inter-…`, measured; prod's is 600 s). So on a
gateway-fronted deployment this route cannot complete for any real investigation
*regardless of the run target* — it is broken by shape, not only by routing.

**2. That changes A1.** Plumbing dispatch through the `run_one_composite` seam
would fix the target on a route whose synchronous shape still cannot survive the
gateway — and would be discarded by A5 anyway. **Refuse instead**, mirroring the
posture #957 took: on a `deployment` target, return an error naming
"Run unblocked". Cheap, honest, not throwaway.

The laptop keeps working: with no pin and no build stamp the target is `local`
and the route behaves exactly as today. A laptop *switched to a build* resolves
`deployment` and is redirected to the async path — which is the path that
actually dispatches.

**3. The async UX already exists**, so A5 is not new UX. "Run unblocked" already
owns the 202 → poll → progress-panel idiom; converging means pointing the second
button at the same machinery.

**4. Reconcile-on-boot is well supported by viva-api.** It exposes
`GET /simulations/status/batch?ids=…` → `list[ComposeHpcRun]` — exactly one call
for all in-flight ids. The workbench's `SmsApiClient` has `compose_status(task_id)`
(singular) but **no batch wrapper**; adding one is the small piece A2 needs.

Also worth carrying: `/api/study-run-variant` has **no live UI caller**, yet is
load-bearing — `run_unblocked_views._worker` drives runs through the *lib*
function `study_runs.run_study_variant`. **Convergence should target lib
functions, not routes.** Routes are one entry point; the `lib/*_views.py` builders
are the reuse surface.

### A1 — Refuse a deployment-target run on the synchronous route *(live defect)*

> **Revised 2026-08-28 by A0.** This section first proposed plumbing dispatch
> through the executor seam. Kept below for the reasoning, which still explains
> *why not to re-point the route*; the action is now the smaller refusal.

**Action:** in `run_one_composite` (or at the `investigation_run` entry), resolve
the target and refuse on `deployment`, naming `/api/investigation-run-unblocked`.
`local` is untouched.

The original analysis, still valid as to why the route must not simply be
re-pointed at `run_jobs` today:
`investigation_run` delegates to `investigations.run_investigation(ws_root, name,
run_one_composite=…, …)`, where the executor is an **injected callable** supplied
in exactly one place (`investigation_run_views`) and stubbed in
`tests/test_investigation_run_views_lib.py`.

Dispatching *through* that seam — `run_core.invoke_run` → `run_runner` instead of
the embedded subprocess script — was the original proposal and remains the
natural shape **if** this route is ever meant to keep running work itself. A0
argues it is not: the route's synchronous contract cannot survive a gateway, so
the seam is the right place to *decline*, not the right place to dispatch.

Re-pointing the whole route at `run_jobs` was considered and rejected *for now*:
it would mean re-implementing everything `run_investigation` does — the
multi-composite `state_doc` path (emitter step injected by `inject_emitter_step`),
the viz hooks (`viz_render_hooks`), spec-error handling, and the concurrent
run-lock guard that must surface as 404 — all while fixing a live defect. That
work belongs in A5, once `run_jobs` is a superset.

### A2 — Durable job state + reconcile on boot

`RunJobManager` keeps jobs in an in-memory dict with a daemon thread each; a pod
roll loses everything, and hosted pods roll on every deploy.

Persist into the existing `composite-runs.db` (which already backs run polling)
using the established additive-migration pattern — `composite_runs._NEW_COLUMNS`
plus `_migrate_runs_meta` adds nullable columns, no table rewrite:

- a `run_jobs` table: `job_id`, investigation, status, items JSON, timestamps
- on `runs_meta`, a column for the **remote dispatch ref**. `remote_run.run_remote`
  already receives `sim_id` from `client.compose_submit(...)` and nothing stores
  it; reconcile needs it.

On startup, for each non-terminal job: re-attach items whose `remote_sim_id` is
still in flight, and fail the rest with a legible "lost to a restart" reason
rather than leaving them `running` forever.

### A3 — Concurrency + dependency ordering

`run_unblocked_views._worker` is a sequential `for` over `job.items`.

- **Concurrency:** run independent items through a *bounded* pool — each
  dispatched item is a Batch job, and each local item a subprocess on the
  workbench host.
- **Dependency ordering:** `run_jobs.enumerate_unblocked` means *"required-before-run
  settings are filled in"* — a **human gate, not a DAG**. Inter-study prerequisites
  live on the pbg path (`investigation_execution._study_prereqs`, read from each
  study's `gate.prerequisites`; `StudyStep.inputs()` turns them into wires).
  Consolidating means lifting that extraction — already a standalone function —
  and re-enumerating as items complete so dependents release.

Scope: **2 of 9** investigations in v2ecoli declare prereqs (`colonies`,
`multiscale-bioprocess`). Real, but not universal — a correct sequential fallback
is acceptable if concurrency lands first.

### A4 — Auto-dispatch

Nothing to build; verify. After A1 every investigation path runs through
`study_runs` → `invoke_run` → `run_runner`, whose `deployment` branch dispatches.

### A5 — Converge the remaining orchestrators

A1 fixes correctness without merging anything. Converge only once `run_jobs` has
A2/A3, by making `/api/investigation-run` a thin wrapper that submits to
`run_jobs` and returns its `job_id`. Deferring is deliberate — converging first
would mean re-implementing `run_investigation` under pressure to fix a defect.

Do **not** invest in making `StudySteps` non-blocking; superseded by A1–A3.

## B. Workstream 8 step 2b — declared-scale precheck

The only thing separating a small in-context run from one that must dispatch, now
that step 1 removed the transport pin that had been acting as an accidental cost
policy.

- Multiply declared `n_seeds × n_generations` (`lib/ensemble_config.py` maps
  `n_seeds` → `n_init_sims`) **before** starting; route or refuse above a
  configured threshold.
- Belongs at the **study-run entry**, before `invoke_run` — *not* at the pool.
  Real study runs never touch `WorkerPool`; `JOB_CLASS_METHODS` marks worker
  calls, which is a different seam.
- Applies only where `target == "local"`. A `deployment` target already goes to
  Batch, which is sized for it.
- Do **not** infer cost for bare composites — [`env-worker-routing.md`](env-worker-routing.md)
  §4 rules that out (a `@composite_generator` is arbitrary Python).

## C. Env-worker relay through viva-api *(design only)*

A laptop cannot use worker-as-image today: the worker dials **out** to the
workbench, and the SSM tunnel (`AWS-StartPortForwardingSessionToRemoteHost`) is
laptop-initiated with no inbound path. Reversing it does not help — the worker has
no Service (viva-api's ServiceAccount can create Jobs, not Services), which is why
dial-back exists at all.

**Design:** viva-api becomes the rendezvous. It is in-cluster (so the worker can
dial back to *it*) and reachable from the laptop over the existing tunnel. It
binds the `DialBackListener`, starts the Job pointing at itself, and bridges bytes
between that socket and the laptop's connection.

Costs, stated plainly:

- viva-api has **no WebSocket endpoints today** — this introduces the first, plus
  ALB upgrade handling and auth for the bridge.
- Every worker call crosses SSM (the path that takes ~224 s for a tarball).
- One worker pod per laptop session.

**Payoff beyond parity:** it also fixes the laptop hybrid, where a materialized
build borrows the *base* workspace's venv — measured: a build pinned at `234dc76`
running under `v2ecoli@a08e20bd`'s dependencies, exactly what #937 warns about.
One mechanism would then cover hosted and laptop, making #937 largely redundant.

**Gate:** build if bit-identical local execution matters. If not, #937 is far
cheaper — local, fast after first sync, no moving network parts, but
platform-appropriate rather than identical.

## D. Loose ends

- `remote_run._DEFAULT_POLL_TIMEOUT = 7200` (2 h). A study outliving it fails the
  whole investigation under the documented fail-loud policy. Revisit with A3.
- `composite_subprocess.run_composite_subprocess` spawns with **`sys.executable`**,
  not `env_resolver.resolve_interpreter`. On the slim image that interpreter cannot
  import the workspace package, so a hosted `target == "local"` run would fail
  inside the child. The pinned deployment never hits it, but runs and env workers
  pick interpreters by different rules.
- Prod is on workbench 0.3.55 / api 0.9.57 and untouched; everything here has been
  exercised only on dev.

---

## Order

1. **A1** — refuse a `deployment`-target run on the synchronous route.
2. **A4** — verify dispatch end-to-end via "Run unblocked" (no code).
3. **A2** — durability + reconcile (`compose_status_batch` wrapper is the new
   piece), before concurrency multiplies what a restart can lose.
4. **A3** — concurrency, then prereq ordering.
5. **A5** — converge the "Run" button onto `run_jobs`, once A2/A3 make it a
   superset. Target the **lib functions**, not the routes.
6. **B** — the scale precheck.
7. **C** — the relay, gated.

A0 raises A5's value: it is not only consolidation, it is what makes the "Run"
button work at all on a gateway-fronted deployment.

Steps 1–2 stand alone: they close the defect that makes "Run investigation"
ignore the deployment pin.

## Critical files

| file | role |
|---|---|
| `lib/investigation_run_views.py` | A1 — the `run_one_composite` seam; the fix lands in this closure |
| `lib/investigations.py` | A1 context — `run_investigation` takes the executor as a parameter; **do not change** |
| `lib/run_unblocked_views.py` | A3/A5 — the `_worker` loop |
| `lib/run_jobs.py` | A2/A3 — manager, `enumerate_unblocked` |
| `lib/composite_runs.py` | A2 — schema + additive migration |
| `lib/remote_run.py` | A2 (`sim_id`), D (poll timeout) |
| `lib/investigation_execution.py` | A3 — `_study_prereqs` to lift |
| `lib/study_runs.py` | B — precheck seam before `invoke_run` |
| viva-api `api/routers/env_worker.py`, `compose/env_worker_service.py` | C |

## Verification

- **A1:** on a pinned deployment (every workspace resolves `deployment`), POST
  `/api/investigation-run` and assert the run dispatches to Batch rather than
  executing on the pod — today it runs locally, and that difference *is* the test.
  `tests/test_investigation_run*.py` pin the response contract and must stay green.
- **A2:** submit a job, `kubectl rollout restart deployment/workbench`, confirm the
  job reappears with in-flight items re-attached and none stuck `running`.
- **A3:** an investigation with independent studies shows overlapping item
  timestamps; `colonies` still runs its dependents last.
- **B:** a study declaring 1000×10 with `target == "local"` refuses immediately,
  naming the dispatch path; a small study still runs.
- Per-repo CI; `bash scripts/run_js_tests.sh` for any UI touch.