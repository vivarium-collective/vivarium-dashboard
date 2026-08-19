# Dual-engine comparison — cross-environment investigations

> **Status:** Draft for discussion (Jim + Alex + Eran + the viva-api team), 2026-08-13.
> **Updated 2026-08-18:** W1 is now roughly **half-landed** — #868 shipped
> always-filled per-run source provenance (`source_ref {repo, commit}` on every
> run row, manifests auto-built at a single choke point, legacy rows backfilled).
> See §3.1 and the revised W1 row in §6.
> **Type:** Target-state design + scoped work plan. No code changes yet.
> **Companions:** [REFACTOR-PLAN.md](REFACTOR-PLAN.md) §2A.2/§2A.5 (Q1) and the
> 2026-08-13 status reconciliation (PR #804, §0A); the umbrella unification spec
> ([superpowers/specs/2026-07-29-framework-unification-design.md](superpowers/specs/2026-07-29-framework-unification-design.md));
> [run-backend.md](run-backend.md) (direction reshaped — see #804);
> [materialization-lifecycle.md](materialization-lifecycle.md) (the dormant managed
> adapter this spec finally wires up). The motivating workload is documented in
> `sms-api/sms-ecoli_vEcoli_comparison_harness_guide.pdf` (the local one-command
> harness in the sms-ecoli repo).

---

## 1. The workload

The sms-ecoli ↔ vEcoli comparison harness runs **two whole-cell *E. coli* models
on the same nutrient conditions and compares them at matched cell-cycle
timepoints**, producing one self-contained HTML report:

- **Candidate (measured):** `sms-ecoli` — the whole cell reimplemented on the
  process-bigraph engine. The harness lives here; its venv is (today) the only
  environment.
- **Reference (baseline):** `vEcoli-private` — the Covert-Lab vEcoli fork, cloned
  side by side and passed as `--fork <path>`.
- **Process transfer:** a fork config can swap a process (e.g. MetabolismRedux)
  into the candidate — auto-converted vEcoli (v1) → process-bigraph (v2) — so the
  *same* process is compared running in both engines, with its full source
  embedded in the report.
- The report records **both repos' branch + commit** (reproducible), per-condition
  gen-1 % differences (cell / dry / protein / RNA mass, growth rate) with a
  **within-tolerance / drift / mismatch verdict**, and the fork's heavy ParCa
  cache (~10 min) is built once and reused.

Today this is fully local: two hand-cloned repos, one command, no cloud. The
short-term goal is to run this workflow **deployed to AWS**, where workspaces are
materialized from coordinates (per-commit images, sessions, viva-api dispatch) —
not hand-cloned siblings.

## 2. Rejected: fork-as-input

The obvious minimal extension — treat the fork as a pinned *input* to a
single-environment run — is **rejected** (Jim, 2026-08-13), for three reasons:

1. **The reference doesn't run under its own lock.** The harness loads the fork's
   process code directly into sms-ecoli's venv, so the comparison measures
   "vEcoli as interpretable by sms-ecoli's dependency set," not vEcoli-as-vEcoli.
   The first real dependency divergence (numpy pin, interpreter) silently breaks
   the honesty of the comparison.
2. **It doesn't generalize.** Any reference that is not import-compatible with
   the candidate's venv — a different Python, a different engine entirely —
   cannot be expressed at all.
3. **It's asymmetric where the science is symmetric.** The comparison's subject
   is two peers. Symmetry also buys something valuable for free:
   **self-comparison across versions** — `sms-ecoli@A` vs `sms-ecoli@B` as a
   model-drift regression harness. Fork-as-input can never express that.

## 3. The design — Q1 narrows from per-workspace to per-run

REFACTOR-PLAN §2A.5 resolved (Q1): *"the runtime always resolves exactly one
environment."* That decision **survives, narrowed**:

> **A run pins exactly one environment coordinate — but an investigation's member
> runs may pin *different* coordinates. A comparison is two ordinary runs plus
> one analysis over their artifacts.**

No node ever hosts two environments. No dual-venv container. The comparison
decomposes into a small DAG — exactly the shape the umbrella spec's step-network
engine executes (an investigation is a document with one site per dependent
node, filled at runtime):

```
transfer (optional)                 candidate-sim                    reference-sim
reads fork SOURCE, emits            env A: sms-ecoli@commitA         env B: vEcoli-private@commitB
converted v2 process ──────────────▶ runs natively                    runs natively
                                        │                                 │
                                        ▼                                 ▼
                                    metrics artifact A               metrics artifact B
                                        └────────────┬────────────────────┘
                                                     ▼
                                            compare + report
                                            (analysis env; verdicts → report cards)
```

Key properties:

- **Each simulation runs natively in its own environment**, under its own lock.
  The reference is a peer, not an import.
- **The transfer node still reads fork *source*** — that is the science of a
  transfer (v1→v2 conversion), not an environment violation. The reference
  *simulation* is untouched by it.
- **The only new data contract is the normalized metrics artifact** (§4). The
  compare node consumes two of them and knows nothing about either engine.
- The investigation record (study YAML, conditions, verdicts) lives in **one**
  workspace — sms-ecoli's, which owns the harness and the candidate — with the
  reference present purely as a coordinate. (A standalone "comparison workspace"
  referencing two engines is the Q2 science/environment-split future; this spec
  names it and does not build it.)

### 3.1 What this changes in the run model

The run-as-binding (§2A.2) already carries `env_id` per run. Changes — with the
**output side already landed by #868** (2026-08-18 update):

- **Study/investigation schema (the remaining input-side work):** a condition
  (and hence its runs) may declare an optional `environment: {repo, ref}`.
  Absent → the workspace's own environment (today's behavior, byte-for-byte).
- **Provenance manifest:** ✅ **half done.** #868 made per-run source provenance
  **always-filled**: `build_run_manifest` records `repo` + `remote_url` in
  `code_version`, `save_metadata` auto-builds a manifest at a single choke point
  (remote-landing, ad-hoc, and investigation paths all stamped), and legacy
  manifest-less rows are backfilled idempotently (`inferred`/`backfilled`
  flags). **Remaining:** the multi-entry `environments: [{role, repo, commit,
  lockfile_hash}]` form, so a comparison's compare node can pin *both* engines
  (today's shape is one pin per run — which §3 keeps for the sim nodes).
- **Sim-DB / run rows:** ✅ **done.** #868 surfaces `source_ref {repo, commit,
  commit_short, remote_url, commit_url, package, inferred}` on every row
  (`SimRow.source_ref`, wired through the JSONL fold + backfill), with a
  repo@commit Source column in the Runs table. Dual-engine needs only the
  cosmetic step of badging *different* coordinates within one investigation.

## 4. The normalized metrics artifact (the one new contract)

A small, engine-neutral file each side's **extractor** produces *inside its own
environment*, so the compare node never imports engine code:

```yaml
# comparison-metrics v1 (deliberately tiny — resist growth)
schema: comparison-metrics/v1
engine: {repo, commit, label}          # who produced this
condition: basal                       # nutrient condition name
seed: 0
timepoints: matched-cell-cycle         # the matching rule used
metrics:                               # per matched timepoint, gen-1
  cell_mass:    [ ... ]
  dry_mass:     [ ... ]
  protein_mass: [ ... ]
  rna_mass:     [ ... ]
  growth_rate:  [ ... ]
time: [ ... ]
```

Rules: **one file, ~6 metric series, matched timepoints** — the harness already
computes exactly these. The extractors are ports of existing harness logic (the
sms-ecoli side reads pbg emitter output; the vEcoli side reads its native output
with its native libs). The tolerance thresholds and the
within-tolerance / drift / mismatch verdict live in the **compare node**, not in
the artifact. Guard against this quietly becoming a second science schema: any
proposed field beyond a metric series needs a reason written here.

## 5. Execution — cloud and local adapters

### 5.1 AWS (the easier half, and the short-term goal)

viva-api already treats every `repo@commit` as its own environment (per-commit
ECR image, Batch dispatch). The cloud shape reuses the single-engine path twice:

1. **Register `vEcoli-private` as a second simulator source** in viva-api (the
   same bootstrap-a-repo flow that exists today). Private-repo access uses
   viva-api's existing build credentials — **never in-job git credentials** (the
   item-39 / Fix B lesson).
2. **Dispatch two ordinary Batch jobs**, one per engine, each in its own image,
   each running its sim + extractor and writing its metrics artifact to S3. Each
   side's ParCa cache is its own image/job concern (vEcoli's ~10-min build
   amortizes exactly like sms-ecoli's does today).
3. **One dependent compare job** (Batch job dependencies) consumes both artifacts
   → HTML report + verdicts to S3, landed as run artifacts.
4. The workbench shows the comparison as an investigation whose member runs carry
   different env badges; verdicts map onto **report cards → verdict artifacts →
   evidence chains** (the machinery from #618/#619/#767); the report is
   retrievable per-run (#631).

**The open viva-api question (§7.3):** vEcoli runs its *own* runscripts — if
viva-api's job model is pbg-shaped, it needs a generic **containerized-job escape
hatch** (image + command + outputs-to-S3). That is the largest unknown in this
spec and it lives in the viva-api repo (see Appendix A).

### 5.2 Local (the harder half — wires up the dormant managed adapter)

Locally, env B must be provisioned. This is the first real customer for the
**managed materialization** path that has been built, tested, and dormant since
2026-07-22 (`materialization.py`'s coordinate-keyed venv store;
`session_env.py`: "wired + tested, dormant"; flagged as the top wire-up in
REFACTOR-PLAN #804 §0A.4):

- **Resolve env B** = clone `vEcoli-private@commit` + `uv sync` → the
  coordinate-keyed venv store → `<venvB>/bin/python`.
- **Exec, don't converse:** the reference side is a *job-style exec* (run the sim
  + extractor entrypoint in env B), **not** the interactive env-worker JSON-RPC
  protocol — vEcoli is not a pbg workspace; there is no `build_core()` to speak
  to. The materialization primitive is shared; the worker protocol is not.
- The fork's ParCa cache keys into the **content-addressed artifact store**
  (#686/#689) by fork commit + parca params, replacing the harness's ad-hoc
  build-once-and-reuse.
- The existing local one-command harness keeps working unchanged while this
  lands (W5 is severable; see §6).

### 5.3 Mixed-version rollout — every step ships alone (2026-08-18)

Multiple developers land work continuously, so every workstream is designed
**additive / tolerant-reader**: no two PRs must be committed together, and each
intermediate state is functional both locally and remotely.

- **Manifests:** the `environments` key is additive (W1/#885). New manifests
  read by old code → unknown key, ignored. Old manifests read by new code →
  `.get()`. No API-surface change until W6's badges (which tolerate absence).
- **Metrics artifacts (W2/W3):** version-tagged (`comparison-metrics/v1`); the
  compare node refuses a wrong tag loudly. The workbench's report-card mapping
  is **presence-gated** — no artifacts on disk → dormant, never broken.
- **W5:** dormant until a study *declares* an environment; nothing else changes.

Two **ordering rules** (deployment discipline, not co-commits):

1. **Declarations after upgrade.** An *old* server does not error on a declared
   `environment:` — it silently ignores the pin (exactly the failure the new
   code refuses). Do not add `environment:` declarations to a **shared**
   workspace until every server that launches runs there is ≥ the W1 build.
2. **viva-api capability before workbench dispatch.** The W4 workbench dispatch
   must **feature-detect** the containerized-job capability (Appendix A, Q5) and
   fail with a clear "service doesn't support this yet" — never assume, never
   half-dispatch. With detection in place, the two services may deploy in either
   order.

### 5.4 Smoke tests

Neither existed before this spec; both are cheap and pay for themselves during
the multi-developer rollout above.

- **`vivarium-workbench smoke` (local, <1 min, no arguments).** Hermetic: scaffolds
  a throwaway minimal workspace (tiny package + one study) in a temp dir, then
  checks the whole local spine — server boots and answers `/health` and `/`, the
  env worker answers `ping` for the workspace, a tiny baseline run executes, and
  the run's manifest carries `environments: [primary]` with a stamped
  `source_ref`. Exit 0/1; CI-able; safe to run anywhere (never touches a user
  workspace). `--workspace PATH` runs the **non-mutating** subset (server +
  worker + read checks) against a real workspace.
- **`vivarium-workbench smoke --remote` (once compatible viva-api services are
  deployed).** Scripted version of today's manual runbook: viva-api health →
  resolve a pinned commit → dispatch a minimal run → poll to landed → verify S3
  artifacts + `source_ref` provenance. Extends naturally into the **W4
  acceptance test**: the two-sims-plus-compare DAG at tiny step counts *is* the
  "W4 done" criterion. Blocked on the Appendix A answers (capability detection,
  Q5).

### 5.5 Ecosystem convergence — perspective from recent commits (2026-08-19)

A survey of recent work across the three repos shows **"independent execution
environments" is not a future direction this spec argues for — it is the
pattern all three repos are actively building**, one backlog item at a time.
This spec's comparison is a *consumer* of that pattern, not its driver.

| Repo | Evidence |
|---|---|
| vivarium-workbench | HTTP process purged of workspace Python (env workers, #530–#536); session-isolated build clones (#729/#763); the workbench image takes the workspace env from the workspace's **own per-commit image** (item 39 / Fix B) |
| viva-api | Everything executes as **per-commit container jobs on AWS Batch**; Array jobs + `dependsOn` chaining landed and fixed against real AWS (#226/#229, in prod since 0.9.40); chain-dispatch campaigns with per-seed progress (item 6 — its workbench half was #853); **vEcoli already runs as its own image** (`vecoli:ray` in Batch MNP job definitions; a `vecoli-github-pat` build secret; "ensure the vEcoli repo is cloned and image is built") |
| sms-ecoli | **Item 71** (2026-08-18): the self-contained simulation *software* image — no baked data, ParCa computed/fetched at job time, "workload-owned, like vEcoli's image" |

**Consequences for this spec:**

1. **Appendix A is largely pre-answered.** Q3 (job dependencies): *yes* —
   `dependsOn` works in production. Q2 (containerized job): being built as item
   71's workload-owned image + entrypoint, and viva-api already builds/runs
   vEcoli images — so W4's "register the reference engine" half mostly
   **exists**. What genuinely remains of W4: wiring the comparison DAG (two
   sims + a dependent compare job) and Q5 (capability detection). The viva-api
   session should *confirm* rather than design.
2. **The local harness guide describes the legacy mode.** "Fork loads in the
   candidate's venv, no cloud" is the local convenience path; the ecosystem's
   main line is both engines in their own containers via viva-api. **W5
   deprioritizes accordingly** — developer convenience, not the product path.
   The local harness keeps working unchanged meanwhile (§5.3).
3. **W2's design is validated and sharpened**: the extractors' primary role is
   to run **as container job stages inside each engine's image**; the
   local-harness integration (slotting into `run_local_comparison.py`) is
   secondary. The reference extractor's zero-repo-imports design is exactly
   what the container stage needs.
4. **Revised critical path:** W2 (sms-ecoli) → W4-remainder (viva-api DAG
   wiring + capability detection) → W3 (the compare node *as the dependent
   Batch job*). The workbench is not the bottleneck (W1 done; W6 trails).
5. **Register the workstreams as items in the shared cross-repo backlog**
   (the item-numbered program: items 6, 39, 61, 65, 71, …). This spec is the
   design record; the backlog is the program of record — without item numbers
   the other developers won't see this work in their queue.

### 5.6 W4 answers landed — and the architecture shifted under them (2026-08-19)

The viva-api session answered Appendix A (full report:
`sms-api/artifacts/2026-08-19-prod-migration-incident.md`). Verified against
viva-api `main` @ `27d54ffb` (0.9.50), plus two in-flight unmerged PRs that
change the picture:

- **Q1 — VERIFIED end-to-end, not just "exists."** A real
  `vEcoli-private@master` dispatch succeeded on stanford-test on 2026-08-12
  (simulator 67, commit `1d80baa`: 8/8 Batch tasks, 624 MB parquet to S3). The
  backends are **asymmetric by explicit map**: `sms-ecoli → RAY`,
  `vEcoli-private → BATCH` (deliberate — a substring fallback would mis-route
  sms-ecoli). One shared credential secret covers both repos' image builds.
  **ECR tag asymmetry** the DAG wiring must handle: `vecoli` repo tags
  `<commit>-arm64 / -amd64 / -amd64-submit`; `v2ecoli` tags bare `<commit>`.
- **Q2 — the delta was named, then implemented while we asked.** The generic
  substrate (`_submit_mnp` = image+command+env, zero pbg semantics) exists, but
  the MNP job definition's `ray-batch-entrypoint.sh` hard-requires Ray/MNP — and
  vEcoli has **no Ray dependency**, so its image can't ride it. The fix —
  `_ensure_container_job_def`/`_submit_container`, `CONTAINER_*` env, per-commit
  job-def cloning (`containerOverrides` cannot swap the image; verified in #226)
  — is **already implemented in viva-api PR #258 (v0.9.51)**, independently
  converging on this spec's design. It is gated on correctness+scaling pilots.
- **Q3 — the earlier "answered" is INVERTED by viva-api PR #260 (v0.9.52):**
  native Batch `dependsOn` chaining is being **replaced by app-level incremental
  submission** (viva-api schedules generations itself in its poll loop, advisory-
  locked; motivated by item 68's Batch scaling stall). The compare job must
  therefore be planned as **a node in viva-api's app-level scheduler**, not a raw
  `dependsOn` dependent. Note the architectural drift: viva-api is becoming a
  scheduler.
- **Q4 / Q5 — still open.** Q5 (capability detection) is now *more* urgent:
  during this exchange, prod was found running an image from unmerged #260 whose
  migration put the prod schema **ahead of `main`** — a live demonstration that
  the workbench cannot assume the service it talks to matches any main. See the
  incident report; resolving that (pilots → merge-forward) is a team decision
  outside this spec.

## 6. Scoped workstreams

| # | Work | Where | Size | Depends on |
|---|---|---|---|---|
| **W1** | Per-run env coordinate — **half-landed by #868** (always-filled `source_ref` provenance + Sim-DB surfacing ✅). Remaining: schema (`environment: {repo, ref}` on conditions) + the multi-entry `environments: []` provenance form (§3.1) | workbench (+ viva-template / viva-workspace schema) | **S** (~1 PR) | — |
| **W2** | Metrics contract (§4) + per-engine extractors ported from harness logic | sms-ecoli (harness) + this spec | **M** (~2–3 PRs) | — (parallel with W1) |
| **W3** | Compare node: two artifacts → report + tolerance verdicts; verdicts → report cards; transfer becomes an explicit node | sms-ecoli + workbench mapping | **M** (~2–3 PRs) | W2 |
| **W4** | AWS dispatch — **rescoped by §5.6**: PR-1 is *land viva-api #258* (container job defs — already written, gated on pilots); PR-2 = comparison-DAG wiring **as nodes in the new app-level scheduler** (#260) + capability detection (Q5) + the two ECR tag schemes | **viva-api** | **M** (~2 PRs, one pre-written) | W1, W2, #258/#260 pilots |
| **W5** | Local dual-env: wire managed materialization for env B + job-style exec; ParCa cache → content-addressed store. **Deprioritized (§5.5):** developer convenience, not the product path — the container path (W4) is primary | workbench | **M** (~3 PRs) | W1; *trails W4* |
| **W6** | UX: investigation graph renders the DAG with per-node env badges; comparison report per-run | workbench | **S** (~1–2 PRs) | W3 |

**Critical path to "this workflow on AWS": W1 → W2 → W3 → W4.** W5 (local
dual-env) and W6 follow independently. Nothing here blocks on the umbrella
Phase-2 reconciliation: the pragmatic path runs the DAG as scripted jobs first
and migrates onto the step-network engine when that reconciliation lands.

## 7. Decisions to settle (recommendations inline)

1. **Ratify the Q1 narrowing** — "exactly one environment *per run node*;
   investigations may span environments" — as a dated entry in REFACTOR-PLAN
   §2A.5. *(Recommended: yes; it is a widening that preserves the invariant
   everywhere it is load-bearing.)*
2. **Investigation home** — stays in sms-ecoli's workspace, reference as a pure
   coordinate. The standalone comparison workspace is named as Q2-split future.
   *(Recommended: as stated.)*
3. **viva-api job model** — does vEcoli dispatch need the generic
   containerized-job escape hatch, or can its runscript be wrapped to look like
   a simulator dispatch? *(Unknown — needs the viva-api team's read; Appendix A
   is the hand-off prompt.)*
4. **Compare-node environment** — neutral third env (cleanest) vs. the candidate
   env (pragmatic; the harness code lives there). *(Recommended: candidate env
   first; the artifact contract (§4) is what keeps it honest — the compare node
   only ever reads the two neutral files.)*

## 8. Risks

- **vEcoli env buildability off-laptop** — C compiler, heavy ParCa. Mitigated on
  AWS by its own image (built once by viva-api); locally by the coordinate-keyed
  cache. First `uv sync` of the fork on a fresh host is the untested step.
- **viva-api scope creep (W4)** — the escape hatch must stay "image + command +
  outputs-to-S3," not a second workflow engine.
- **The metrics contract growing** — held to §4's rules; growth requires a
  written reason.
- **Rebrand/packaging churn** (REFACTOR-PLAN #804 §0A.3.3) — both engine repos
  are private and moving; every coordinate in this spec is a pinned commit, never
  a branch.

## 9. Out of scope

- Running *either* engine in the workbench HTTP process or the interactive env
  worker (the reference is job-exec only; §2A.7's boundary is unchanged).
- N-way comparisons (N=2 shapes the contract; nothing precludes N later).
- Cross-engine *state* transfer beyond the existing v1→v2 process conversion.
- The Q2 science/environment repo split (this spec is its best motivating case;
  it stays future work).

---

## Appendix A — hand-off prompt for the viva-api session

> **Context:** vivarium-workbench is building a dual-engine comparison workflow
> (see `docs/dual-engine-comparison.md` in the workbench repo): two whole-cell
> models — `CovertLabEcoli/sms-ecoli` (process-bigraph) and
> `CovertLabEcoli/vEcoli-private` (native vEcoli) — each run as its **own** Batch
> job in its **own** per-commit image, followed by a dependent compare job that
> consumes one small metrics artifact from each run's S3 output.
>
> **What already exists (as of 2026-08-19) — the concrete pieces you'd be wiring:**
> - **The artifact + per-engine extractors are merged** (sms-ecoli #82):
>   `docs/comparison-metrics-v1.md` (the contract — each engine emits its
>   gen-1-windowed metric series on its native emit grid),
>   `scripts/extract_metrics_v2.py` (candidate side), and
>   `scripts/extract_metrics_vecoli.py` (reference side — deliberately zero repo
>   imports, so it runs inside vEcoli-private's env; its only remaining stub is
>   S3 reads, moot when it runs in-job with local output).
> - **The container stage is on sms-ecoli main**: item 71's
>   `docker/batch-container-entrypoint.sh` (+ Dockerfile wiring, #78) for plain
>   container-type Batch jobs.
> - **The run-side provenance is merged** (workbench #885): per-run
>   `environment: {repo, ref}` declarations + multi-entry `environments:`
>   manifest pins, ready to record what your dispatch resolves.
>
> So the ask is the **comparison-DAG wiring**: dispatch candidate-sim +
> reference-sim (each image runs its sim then its extractor, landing a
> `comparison-metrics/v1` artifact to S3) → one dependent compare job.
>
> **Questions for you (W4 of that spec):**
> 1. Can `vEcoli-private` be registered as a simulator source in viva-api's
>    existing bootstrap-a-repo flow, given it is private in the CovertLabEcoli
>    org (same as sms-ecoli)? What credential path applies to its image builds?
> 2. vEcoli executes via its own native runscripts, not a process-bigraph run
>    request. Does viva-api's dispatch support (or how hard is) a **generic
>    containerized job**: image + command + env + outputs-to-S3 — with no pbg
>    assumptions? *(§5.5, 2026-08-19: largely pre-answered — viva-api already
>    builds/runs vEcoli images, and sms-ecoli item 71 adds the workload-owned
>    software image + entrypoint. Please CONFIRM the remaining delta rather
>    than design from scratch.)*
> 3. Does viva-api's Batch integration expose **job dependencies** (compare job
>    starts after both sim jobs land), or should the workbench poll-and-dispatch
>    the compare job itself? *(ANSWERED — twice, see §5.6: `dependsOn` landed in
>    0.9.40, but unmerged PR #260 replaces it with app-level incremental
>    submission. Plan the compare job as a node in viva-api's app-level
>    scheduler.)*
> 4. Anything about the per-commit ECR image convention (no floating tags) that
>    the two-engine case complicates — e.g., resolving "latest built commit" for
>    two repos atomically?
> 5. **Capability detection:** how should the workbench detect, at request time,
>    whether the viva-api instance it is talking to supports the containerized-job
>    dispatch (and job dependencies)? A version endpoint, a capabilities list, or
>    a probe? The workbench must **feature-detect, never assume** — dual-engine
>    dispatch against an older viva-api has to be a clear "service doesn't support
>    this yet" error, not a half-dispatched run (see §5.3, rollout rule 2).
>
> Please answer against viva-api `main` as of today; the workbench side will pin
> exact commits in every dispatch (no branch coordinates).
