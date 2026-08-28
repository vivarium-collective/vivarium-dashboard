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
   after a restart is re-attached, not orphaned. *(Revised by A0b: the cheaper
   route to this is to stop holding a thread per run at all, so there is nothing
   to orphan — viva-api already holds the state, keyed by `simulation_id`.)*
3. ~~**The viva-api relay is in scope as a design**, gated on a real need before
   being built.~~ **Superseded by 4.**
4. **DECIDED 2026-08-28 — §E option (e): proxy env-worker traffic through
   sms-api**, which owns queuing, durability and status. This settles the
   intermediate tier *and* §C: the relay is no longer gated on bit-identical
   local execution, because it is now the transport for a product decision —
   putting the worker's 26 capabilities on an API every client can call.
5. **OPEN, worth revisiting — §E option (f): a Service per env-worker Job.**
   Not a competitor to (e): it addresses the *in-cluster* leg (sms-api → worker)
   where (e) addresses the client leg. Adopting both would retire dial-back and
   make local and remote transports symmetric. Deferred, not rejected — and the
   RBAC objection that shaped the original design was **wrong**: it is a
   three-line Role edit.

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
timeout is **60 s** (`smsvpc-Inter-…`; prod's is 600 s). So on a gateway-fronted
deployment a synchronous route cannot complete for any real investigation
*regardless of the run target* — broken by shape, not only by routing.

**Verified on dev, 2026-08-28**, and the limit turns out to be broader than this
route. `GET /api/investigations` against a **freshly materialized build** was
measured through the tunnel:

```
client:  HTTP 504 Gateway Time-out  after 60.1 s
server:  GET /api/investigations -> 200 (126037.0 ms)
         GET /api/investigations -> 200 (172071.4 ms)
         GET /api/investigations -> 200 (200191.4 ms)
```

The server **succeeded** — at 126 s, 172 s and 200 s — while the client got a 504
at 60.1 s. (A synthetic silent request was dropped at 60.1 s too, so the ceiling
is exact and applies end-to-end through the SSM tunnel.) It is cold-start
dominated: warm retries returned 200 in 32 s, then 9.9 s.

Two consequences:

- **This is not only an orchestration problem.** *Any* endpoint slower than 60 s
  is unusable on this deployment, and the first thing a user does after switching
  to a build — list its investigations — is one of them. That deserves its own
  issue (cache/warm the discovery, or make the endpoint incremental); it is not
  fixed by anything in this plan.
- **It compounds with the run route.** A synchronous `/api/investigation-run` is
  the same failure with a far longer tail.

**Still inferred, not observed:** that `/api/investigation-run` *specifically*
exceeds 60 s. It could not be tested on dev — the base workspace is a scaffold
with zero investigations, and running one on a materialized build would execute
real simulations. The shape argument (inline orchestration + measured 60 s
ceiling) is strong, but it is an inference.

It also revises an earlier diagnosis: the 504 reported when switching workspaces
was attributed wholly to the base-path bug (#960). That bug was real and proven
— `/?workspace=…` serves PTools — but this is a **second, independent** cause of
504s in the same flow, and stopping at the first explanation missed it.

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

### A0b — The async model already exists, and Batch is already async *(2026-08-28)*

Two questions — *"isn't there an async version?"* and *"shouldn't this go to Batch,
which is inherently async?"* — turn out to have the same answer, and it revises
A2 and A3 more than A1.

**There is a complete async remote-run API, built and in use.** A thin-client
three-phase family, with `study-detail.js` as its caller:

| route | role |
|---|---|
| `POST /api/remote-run-build` | phase 1 — push + register the simulator build |
| `POST /api/remote-run-submit` | phase 2 — issue the run; **`202 {simulation_id, phase:"running"}`** |
| `GET /api/remote-run-poll` | on-demand status (build / run / analysis phase) |
| `POST /api/remote-run-land` | phase 3 — download + land a completed run |

`remote_run_submit` contains **zero blocking polls**, and its docstring is
explicit: it "returns as soon as sms-api hands back a `database_id` … in seconds
regardless of campaign size", because viva-api moved the per-seed submission loop
off the response path (backlog item 51). The JS panel polls for progress. This is
the correct shape, already implemented.

**But the other dispatch path throws that away.** `run_runner._execute_remote` →
`remote_run.run_remote` does:

```
sim_id = client.compose_submit(...)        # returns immediately — Batch is async
status = _poll_until_terminal(...)         # BLOCKS for the life of the job
results = client.download_compose_results(sim_id, dest)
```

So there are **two dispatch idioms**, and the plan had been consolidating onto the
wrong one:

| idiom | shape | used by |
|---|---|---|
| thin-client phases | submit → 202 → client polls → land. Never blocks. | `study-detail.js` |
| `invoke_run` → `run_runner._execute_remote` → `run_remote` | submit **then block polling** then download | `study_runs`, `composite-test-run`, and therefore `run_jobs` |

**`run_jobs` is async only at the HTTP layer.** Its `_worker` calls
`study_runs.run_study_baseline`, which blocks through `_launch_run_and_flush`'s
"full 7-stage flush tail", which for a `deployment` target blocks inside
`run_remote`. So a daemon thread is held for the entire life of a Batch job — to
babysit work AWS is already tracking.

**That reframes A2 and A3.** They were solving symptoms of holding threads:

- **A2 (durable job state + reconcile) shrinks.** You need durable thread state
  because you are holding threads. Adopt the thin-client shape — record
  `simulation_id`, return — and there is no thread to lose across a restart.
  **viva-api becomes the durable state**, and `sim_id` the handle. What survives
  from A2 is exactly the small part: persist the dispatch ref and poll it, using
  `GET /simulations/status/batch?ids=…` (§A0.4).
- **A3 (concurrency) largely dissolves.** A bounded pool exists to cap
  simultaneously-*blocked* threads. Non-blocking submits need no pool; Batch
  provides the parallelism. Dependency ordering (prereqs) remains real.

**Revised destination:** not "make `run_jobs` durable and concurrent", but
"make the run path non-blocking, the way `remote-run-submit` already is, and let
`run_jobs` track `simulation_id`s rather than threads."

Open questions this raises, which the plan should not pretend to settle:

- `run_remote`'s blocking poll also performs **`download_compose_results`** —
  landing results is a real step the thin-client family gives its own phase
  (`remote-run-land`). A non-blocking run path needs somewhere for landing to
  happen; that is what phase 3 is for, and what `run_jobs` would have to drive.
- The local (`target == "local"`) branch is genuinely synchronous — a subprocess
  on this host. Non-blocking dispatch is a *remote*-target property, so the two
  branches stop being symmetric and the job model must carry both.

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

**§E raises the stakes on this gate.** If the relay is built, option (e) there —
proxying *all* env-worker traffic through sms-api, which then owns queuing,
durability and status — becomes the natural destination, collapsing the relay,
the missing intermediate tier, and durable job state into one mechanism on a
substrate that already exists (Postgres, `JobStatus`, `ORMHpcRun`). So this is
not only a laptop question.

## E. The missing middle: jobs that are neither interactive nor Batch-scale

*(2026-08-28. Raised as a question — "do we need a path for intermediate jobs
>60 s, and if the worker is single-threaded, does sms-api queue them or do we add
thread pools?" — recorded with what the code actually constrains.)*

Two tiers exist and nothing sits between them:

| tier | mechanism | bound |
|---|---|---|
| interactive | env-worker call | `ENV_WORKER_CALL_TIMEOUT`, default **60 s** |
| deployment-scale | viva-api → AWS Batch | async; minutes to hours |

**sms-api cannot queue env-worker calls as things stand, because it is not on
that path.** Dial-back (§5A) means the *workbench* holds a direct socket to the
worker; viva-api only creates and deletes the Job
(`/env-worker/v1/workers`). It never sees a method call. Queueing already happens
one layer earlier, in the workbench.

**Both ends are serial by explicit design.** `env_worker._serve` is a *"Serial
request loop (spec §8): one request at a time, FIFO."* `EnvWorker.call` holds a
mutex across send+recv — *"holds the lock so the next frame read is unambiguously
this call's reply."*

**The binding constraint is monopolization, not the timeout.** The pool keys
workers `(workspace, env_key, kind)`, so a workspace has **exactly one** worker;
`ENV_WORKER_POOL_MAX=8` caps *distinct* environments, not concurrency within one.
So **any long call blocks every other call for that workspace, including
interactive ones** — an intermediate tier cannot be "an interactive call with a
bigger timeout".

### Options

**(a) Thread pool inside `env_worker`.** Requires a protocol change — serial FIFO
is spec §8 and the client's mutex assumes the next frame is its reply, so
responses would need id-multiplexing and a reader thread. Worse, the worker holds
**process-global mutable state** built lazily (`_WS_CORE`, `_VIZ_CORE`,
`_OBS_LINEAGE_AGENT_RE`) and mutates `sys.path`, all written assuming serial
execution; workspace science code (process-bigraph, numpy) adds its own
assumptions. **Highest risk.**

**(b) More than one worker per workspace.** Add an instance slot to the pool key.
No protocol change; concurrency = worker count. But each remote worker is a
**pod** (1 CPU / 2 GiB), so N-way concurrency costs N pods and the LRU cap becomes
a concurrency cap. Cheap to build, expensive to run.

**(c) Async submit/poll *over* the serial protocol.** A `submit`-shaped method
starts work in one background thread and returns a handle; a `poll` retrieves it.
Every protocol call stays fast, so the worker is never monopolized, and the FIFO
loop is preserved. Same shape `remote-run-submit` already uses one layer up
(§A0b). Cheap — but the job state lives **in the worker**, so an evicted,
idle-reaped or crashed worker loses it, and results have nowhere durable to land.

**(d) Send it to Batch anyway.** Correct for anything genuinely large; Batch
startup (image pull, queue wait) dominates a 90-second job.

**(e) Proxy every env-worker request through sms-api, and let sms-api own
queuing, durability and status.** The workbench stops holding a socket to the
worker; sms-api brokers each call.

This is the option that puts the queue where a queue can actually be durable.
sms-api already has the substrate — PostgreSQL, a `JobStatus` model,
`ORMHpcRun` / `ORMAnalysis` — and **already implements exactly this pattern** for
compose: submit → `/simulation/{id}/status` → `/simulation/{id}/results`, with
`/simulations/status/batch` for bulk polling. "Let sms-api handle it" is reuse of
a proven mechanism rather than a new one in the workbench.

**It also makes the worker's capabilities part of the product API.** This is
arguably the strongest argument for (e) and is not an implementation detail.
Today the worker's **26 capabilities** — `list_generators`, `registry_catalog`,
`discover_composites`, `run_study`, `config_to_composite`, … — are reachable
*only* through the workbench, because the workbench holds the socket. **Zero of
them appear in the Atlantis CLI**, whose commands stop at the compose surface
(`simulator_*`, `simulation_*`).

That breaks the stated EUTE model, in which the CLI, TUI and Marimo GUI are three
clients of one REST API: environment introspection and workspace-scoped execution
are currently workbench-only plumbing rather than product surface. Proxying
through sms-api turns each capability into an HTTP endpoint any client can call —
so the CLI could script these workflows, and so could CI, a notebook, or a
third-party tool. None of the other four options change this; they all leave the
socket where it is.

It also **subsumes §C rather than depending on it**. The relay was scoped as a
laptop-only bridge so a laptop could reach worker-as-image; making the proxy
universal means there is *one* path, and the laptop case falls out. And it
answers (c)'s weak spot directly: worker death or idle-reap stops losing the job,
because the record is in Postgres, not in the worker.

Costs, stated plainly:

- **sms-api becomes a hard dependency of every remote env-worker call**, where
  today it only creates the Job. An sms-api outage would become a workbench
  outage for hosted introspection — a new coupling that does not exist now.
- **A hop on every interactive call.** In-cluster that is cheap; over SSM from a
  laptop it is not, and interactive latency is the thing users feel.
- ~~**A duplex transport sms-api does not have.**~~ **Overstated — corrected
  2026-08-28.** The interactive tier needs **no WebSocket**. Because *sms-api*
  would hold the worker socket, the client→sms-api leg is plain request/response:
  `POST /env-worker/v1/workers/{name}/call {method, params}` → sms-api forwards
  over the socket → returns the result. `EnvWorkerService.start` already takes
  `callback_host` / `callback_port`, so pointing the worker at sms-api instead of
  the workbench is **configuration, not redesign**. A streaming transport is only
  needed if something wants push, and nothing does today.
- **The gateway's 60 s ceiling moves in front of every worker call.** Proxied
  calls traverse the ALB, so the measured 60 s limit (§A0) now applies to them.
  That is survivable for interactive work — `ENV_WORKER_CALL_TIMEOUT` is *also*
  60 s, so the budgets coincide — but it makes the intermediate tier
  **necessarily task-based**: a long call cannot be a long HTTP request. This
  constrains the design rather than blocking it.
- **Local subprocess workers must not proxy.** A laptop routing to itself via the
  cloud is absurd, so the local/remote asymmetry stays and the proxy is a property
  of the *remote* transport only.

**(f) Give each env-worker Job a Kubernetes Service, and dial *in*.**

*Raised in review 2026-08-28, and it corrects a framing error of mine.* Dial-back
(§5A) exists because "viva-api's ServiceAccount can create Jobs but not Services"
— which I repeatedly stated as a constraint. It is a **three-line RBAC gap, not a
law**: `kustomize/base/rbac-jobs.yaml` grants `jobs`, `jobs/status`, `configmaps`,
`pods`, `pods/log`, and adding `services: [create, get, delete]` is an edit, not
an architecture.

**What it genuinely buys — symmetry.** Today the two transports are inverted: for
a local worker the workbench connects to a subprocess it spawned; for a remote
one the *worker* connects out to the workbench. With a Service both become
"connect to an address", and the dial-back machinery disappears —
`DialBackListener`, the advertise-host, the one-time token in the first frame, and
the `ENV_WORKER_ADVERTISE_HOST`-selects-the-launcher trick. `EnvWorker.from_socket`
already exists, so the launchers would differ only in how they *obtain* an
address. **The worker gets simpler, not more complex** — it becomes a plain
listener. The complexity moves into Kubernetes object lifecycle: a Service per
Job, garbage-collected via `ownerReferences` so it dies with the Job the way
`ttl_seconds_after_finished` already handles the Job itself.

**What it does not buy — laptop reach.** A ClusterIP Service is routable only
inside the cluster network. The SSM tunnel forwards to the internal **ALB**,
which is an address the bastion can reach; a bastion EC2 in the VPC cannot
generally reach a ClusterIP, because kube-proxy programs that on cluster nodes.
Making a worker reachable from a laptop would need a NodePort or a load balancer
**per ephemeral worker** — minutes of provisioning for a pod that may live for
one query. So a Service alone leaves the laptop where it is; a stable rendezvous
is still required, which is what (e) provides.

**What it costs relative to (e).** A direct workbench→worker path bypasses sms-api
entirely, so it forgoes exactly what (e) was chosen for: durable task records,
per-worker queuing, status, and reaching the worker's 26 capabilities from the
Atlantis CLI.

**(e) and (f) are not exclusive, and the combination may be the real end state.**
They address different legs:

| leg | mechanism |
|---|---|
| client (workbench, CLI, CI) → sms-api | (e) — HTTP, queued, durable, product API |
| sms-api → worker, in-cluster | **(f) — a Service, dialled in** |

In that pairing (f) replaces dial-back for the leg where it is awkward — sms-api
would no longer bind a listener and hand out its own host/port — while (e) keeps
the outside world on one durable, addressable API. Worth revisiting on those
terms rather than as a competitor to (e).

### Where this lands

**DECIDED: (e).** The reasoning below is kept because it records *why*, and
because the §C coupling it identified is what the decision turns on.

**(c) and (e) were the real candidates, and the choice was coupled to §C.**

- If the **relay is built** (§C), the transport cost is already paid, and (e) is
  then mostly "put a queue and a table behind it" — making it the natural
  destination, and collapsing three separate mechanisms (relay, intermediate
  tier, durable job state) into one.
- If the **relay is not built**, (e) is a large change to carry on its own, and
  **(c)** is the cheap tier that needs no new transport — with its durability gap
  accepted as the price.

So §C's gating question — does bit-identical local execution matter? — turns out
to decide more than the laptop case. It decides whether the intermediate tier is
a workbench feature or an sms-api one.

Either way, three things stay unsettled and should not be hand-waved: **where
results land** (the same question §A0b raises about
`download_compose_results`), **what the idle-TTL reaper must know** so it does not
reap a worker mid-job, and **which methods qualify** — the same scale axis as §B.

### What (e) means for the rest of this plan

The decision reaches back into sections written before it.

- **§C is no longer gated.** The relay is the transport for (e). Its cost is
  lower than §C assumed, since the interactive tier is request/response, not a
  duplex stream.
- **§A2′ moves repositories.** Durable job state stops being a workbench concern:
  sms-api records the task in Postgres alongside `ORMHpcRun` / `ORMAnalysis`. The
  workbench keeps `simulation_id`-shaped handles, not threads.
- **§A3′ loses most of its concurrency work.** sms-api must serialize calls
  **per worker** to honor the worker's serial FIFO contract — the queue that
  `EnvWorker.call`'s mutex provides today, moved somewhere durable. Cross-worker
  parallelism is then a scheduling property of sms-api, not a thread pool.
- **§B is unchanged but better placed.** The scale precheck still decides which
  tier work belongs in; with three tiers it now has three answers instead of two.

### Open questions (e) does not answer

Recorded so they are decided deliberately rather than by the first commit:

1. **Where the serialization point lives.** sms-api must not issue two concurrent
   calls down one worker socket. Per-worker lock, per-worker queue, or a single
   consumer per worker — each has different failure behavior when sms-api itself
   restarts.
2. **Whether interactive calls are also task-based.** Uniformity argues yes;
   latency argues no (an extra round trip on `list_generators` is felt). A split
   contract — sync under the budget, task-based over it — is more code but
   matches how the tiers actually differ.
3. **Auth on the call endpoint.** The worker↔sms-api leg has the dial-back token
   (§5A). The client→sms-api leg has whatever protects viva-api generally, which
   is a different question and is now on the path of every workspace query.
4. **What happens to the local subprocess launcher.** It must *not* proxy — a
   laptop routing to itself through the cloud is absurd — so `LocalWorkerLauncher`
   keeps its direct socket and the two transports stay asymmetric. The pool's
   `env_key` / `kind` split already models this.
5. **Migration order.** The workbench's `RemoteWorkerLauncher` and
   `DialBackListener` both move to sms-api. Whether that is a flag-gated parallel
   path or a cutover determines whether dev can run both shapes during the change.

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
3. **A2′** — *revised by A0b.* Make the remote-target run path **non-blocking**
   (the shape `remote-run-submit` already has), record `simulation_id`, and poll
   via `GET /simulations/status/batch?ids=…`. This replaces "durable thread
   state + reconcile" — with no thread held, there is far less to lose.
4. **A3′** — prereq ordering. *Concurrency largely dissolves with A2′*: a
   bounded pool exists to cap simultaneously-blocked threads, and Batch supplies
   the parallelism once submits stop blocking.
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