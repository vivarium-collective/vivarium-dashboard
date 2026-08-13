# Dual-engine comparison — cross-environment investigations

> **Status:** Draft for discussion (Jim + Alex + Eran + the viva-api team), 2026-08-13.
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

The run-as-binding (§2A.2) already carries `env_id` per run. Changes:

- **Study/investigation schema:** a condition (and hence its runs) may declare an
  optional `environment: {repo, ref}`. Absent → the workspace's own environment
  (today's behavior, byte-for-byte).
- **Provenance manifest:** grows `environments: [{role, repo, commit,
  lockfile_hash}]` — for a plain run, one entry (identical to today's single
  pin); for a comparison investigation, the compare node's provenance lists both.
- **Sim-DB / run rows:** surface the per-run coordinate. (Remote-build runs
  already display `repo@branch@commit`; this generalizes an existing column, not
  a new concept.)

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

## 6. Scoped workstreams

| # | Work | Where | Size | Depends on |
|---|---|---|---|---|
| **W1** | Per-run env coordinate: schema (`environment: {repo, ref}` on conditions), provenance `environments: []`, Sim-DB/run-row surfacing | workbench (+ viva-template / viva-workspace schema) | **S–M** (~2 PRs) | — |
| **W2** | Metrics contract (§4) + per-engine extractors ported from harness logic | sms-ecoli (harness) + this spec | **M** (~2–3 PRs) | — (parallel with W1) |
| **W3** | Compare node: two artifacts → report + tolerance verdicts; verdicts → report cards; transfer becomes an explicit node | sms-ecoli + workbench mapping | **M** (~2–3 PRs) | W2 |
| **W4** | AWS dispatch: register `vEcoli-private`; containerized-job escape hatch if needed; Batch dependency wiring (2 sims → 1 compare) | **viva-api** | **M–L** (~3–4 PRs) | W1, W2 |
| **W5** | Local dual-env: wire managed materialization for env B + job-style exec; ParCa cache → content-addressed store | workbench | **M** (~3 PRs) | W1; *may lag W4* |
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

> **Context:** vivarium-workbench is designing a dual-engine comparison workflow
> (see `docs/dual-engine-comparison.md` in the workbench repo): two whole-cell
> models — `CovertLabEcoli/sms-ecoli` (process-bigraph) and
> `CovertLabEcoli/vEcoli-private` (native vEcoli) — each run as its **own** Batch
> job in its **own** per-commit image, followed by a dependent compare job that
> consumes one small metrics artifact from each run's S3 output.
>
> **Questions for you (W4 of that spec):**
> 1. Can `vEcoli-private` be registered as a simulator source in viva-api's
>    existing bootstrap-a-repo flow, given it is private in the CovertLabEcoli
>    org (same as sms-ecoli)? What credential path applies to its image builds?
> 2. vEcoli executes via its own native runscripts, not a process-bigraph run
>    request. Does viva-api's dispatch support (or how hard is) a **generic
>    containerized job**: image + command + env + outputs-to-S3 — with no pbg
>    assumptions?
> 3. Does viva-api's Batch integration expose **job dependencies** (compare job
>    starts after both sim jobs land), or should the workbench poll-and-dispatch
>    the compare job itself?
> 4. Anything about the per-commit ECR image convention (no floating tags) that
>    the two-engine case complicates — e.g., resolving "latest built commit" for
>    two repos atomically?
>
> Please answer against viva-api `main` as of today; the workbench side will pin
> exact commits in every dispatch (no branch coordinates).
