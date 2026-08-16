# Remote dispatch composite resolution — what's fixed by the image vs. what's client-controllable

When a workbench Study is dispatched remotely — `POST /api/remote-run-submit`
on this repo (`vivarium_workbench/lib/remote_run_views.py:297`, routed from
`vivarium_workbench/api/app.py:6792-6799`) → viva-api's `POST /simulations`
(`viva_api/api/routers/sms.py`) → a real AWS Batch job running a **pinned**
Docker image — most of what actually executes is baked into that image and
cannot be changed by any client request, ever. A much smaller surface is
genuinely controllable per dispatch. This doc traces the real code path to
say, precisely, which is which, and what package/repo identity actually ends
up running.

*Citations are `path:line`. `viva_api/...` paths are relative to the
`viva-api` repo's own root — that repo currently ships both a legacy
`sms_api/` package tree and the renamed `viva_api/` tree side by side; every
citation here is against the new one. `sms-ecoli/...` and `sms-cdk/...`
citations include the repo name and are relative to the `ecosystem/` root,
per this workspace's sibling-repo layout (see `../../CLAUDE.md`).*

## At a glance

| Aspect | Fixed by the pinned image | Client-controllable per dispatch |
|---|---|---|
| Composite wiring/code (which Python actually runs) | Always — `V2ECOLI_BATCH_BASELINE_COMPOSITE_ID` is a hardcoded viva-api constant | Never, for a chain (multi-generation) dispatch — not even via a Study's own `spec.yaml` |
| Seed / generation counts | — | Yes — `num_seeds`, `num_generations` on `POST /simulations` |
| Most `batch_baseline` composite parameters (`single_daughters`, `time_step`, `max_duration`, `variants`, `emitter`, `study`, …) | Yes, silently, via `DEFAULT_*` constants in the image | No — no matching field exists anywhere on the request surface |
| Analysis modules | — | Yes — `analysis_options`, sourced from a Study's `spec.analyses[]`; a separate mechanism from composite overrides |
| Which git commit/image runs | Fixed the moment a `simulator_id` is chosen | Only indirectly — a client picks among already-registered builds, never an arbitrary commit |

## 1. Composite structure is 100% baked into the image

`viva_api/simulation/simulation_service_ray.py:107` hardcodes:

```python
V2ECOLI_BATCH_BASELINE_COMPOSITE_ID = "v2ecoli.composites.batch_baseline.batch_baseline"
```

This is a Python constant in viva-api's own deployed code — not a field on
the HTTP dispatch request surface. The full `POST /simulations` parameter
list (`viva_api/api/routers/sms.py:192-261`) gives a caller no way to
functionally redirect which composite code runs a chain dispatch (see the
`composite`-field caveat in §3).

**The non-obvious part.** For any dispatch where the generation count is
greater than 1 (checked internally as `n_generations > 1`, the routing check
at `simulation_service_ray.py:968-971`), viva-api routes to
`submit_chain_dispatch_job`, which uses this hardcoded constant —
**completely independent of whatever composite a workbench Study declares in
its own `spec.yaml` `baseline[].composite` field.** `remote_run_submit()`
(`vivarium_workbench/lib/remote_run_views.py:297-340`) doesn't even pass a
`composite` argument when it calls into viva-api: its `client.run_simulation(...)`
call (lines 328-336) sends `simulator_id`, `num_generations`, `num_seeds`,
`run_parca`, `observables`, and `analysis_options` — nothing else.

State this plainly: **a workspace Study's own composite reference is not
what determines which composite code actually runs for a multi-generation
remote-pinned dispatch.** That's fixed server-side in viva-api, always
`batch_baseline`. It's a real gotcha — it's reasonable to assume that
configuring a Study's composite field controls dispatch behavior, and for
this path, that assumption is wrong.

The generic runner (`viva_api/compose/run_pbg.py:168-183`) resolves a
composite id via `process_bigraph.composite_spec.get(composite_id)` — a
registry populated purely by import-time decorator side effects inside the
running container. No HTTP request body reaches this registry; it's fully
determined by what got imported when the container started.

**Bottom line:** to run different composite *code* (a different wiring or
structure), you need a different image built from a different commit — full
stop. No override mechanism, request field, or Study config can substitute
code at dispatch time.

## 2. What IS genuinely client-controllable

`_seed_generation_command` (`simulation_service_ray.py:601-679`) builds each
individual per-seed/per-generation job's `--overrides` JSON. Per job it sets:

- `n_seeds: 1`, `n_generations: 1` — always, regardless of campaign size. The
  campaign's *total* seed/generation counts instead drive an outer Python
  loop in `submit_chain_dispatch_job` (`simulation_service_ray.py:1249-1252`),
  where `n_seeds`/`n_generations` come straight from the client's
  `num_seeds`/`num_generations` request params.
- `base_seed` / `initial_generation_index` — computed from that same loop.
- Checkpoint/resume paths (`initial_carry_state_path`,
  `daughter_state_out_path`) — computed server-side via `RayLayout`.

That's the real controllable surface for counts and continuity. Composite
*parameters*, by contrast, are mostly not reachable at all.

`batch_baseline`'s full declared parameter schema
(`sms-ecoli/v2ecoli/composites/batch_baseline.py:65-187`, the
`@composite_generator(parameters={...})` block) has **17 parameters**.
Several of them — `single_daughters`, `time_step`, `max_duration`,
`variants`, `emitter`, `study` — never appear in viva-api's overrides dict at
all, and there's no matching field on `POST /simulations`'s param surface
either. They silently resolve to whatever `DEFAULT_*` constants are baked
into the pinned image's own `v2ecoli/steps/batch_baseline_runner.py`. This is
a real, easy-to-miss gap: these are architecturally "composite parameters"
that read as if they should be per-dispatch configurable, but in practice
they're only changeable via a new image build.

`analysis_options` **is** genuinely respected, but through a mechanism
entirely separate from composite overrides. Per-seed sim jobs hardcode
`analyses: "none"` (so the composite's own inline flush never fires —
analysis instead runs as its own, later DAG node,
`simulation_service_ray.py:681-741,1323-1360`). The client's
`analysis_options` request field flows into `analysis_modules_for()`
(`simulation_service_ray.py:200-221`), which feeds that separate analysis
job. On the vivarium-workbench side this traces back to a workbench Study's
own `spec.analyses[]` field: `remote_run_submit`
(`vivarium_workbench/lib/remote_run_views.py:314-327`) reads
`spec.get("analyses")` and translates it via `build_analysis_options` into
v2ecoli's `{scale: {name: params}}` shape before it goes into
`run_simulation(...)`. A comment at those same lines (314-318) notes this was
previously a real gap — every remote-dispatched run's `analysis_options` came
out empty regardless of what a study configured, until `spec.analyses` was
threaded through. Today it genuinely IS respected, and IS the thing that
determines what analysis modules actually run.

The merge rule for overrides that *do* apply:
`pbg-superpowers/pbg_superpowers/composite_generator.py:84-90` — only
explicitly-overridden parameter keys change; everything else falls back to
the composite function's own declared default, resolved from whatever's
loaded in that specific process. Unknown override keys raise `ValueError`
**inside the container at runtime** — not caught at viva-api dispatch time,
since viva-api has no visibility into the pinned image's actual parameter
schema when it builds the command.

## 3. `POST /simulations` — the real client-facing surface

Full param list (`viva_api/api/routers/sms.py:184-261`):

```
simulator_id, experiment_id, simulation_config_filename, num_generations,
num_seeds, composite, condition, max_generations, vecoli_source, description,
run_parca, observables, ecoli_sources_*, tags, analysis_options
```

`num_generations` → `config_data["generations"]`, `num_seeds` →
`config_data["n_init_sims"]` (`viva_api/common/handlers/simulations.py:504-507`)
are genuinely respected.

The `composite` field is present on this surface, but don't read too much
into it: per §1, it is not what determines which composite code runs a chain
dispatch (`num_generations > 1`) — the hardcoded
`V2ECOLI_BATCH_BASELINE_COMPOSITE_ID` wins for that path regardless of what
this field is set to. There is no field anywhere on this surface through
which a client can supply code or an arbitrary module path.

`simulator_id` selects among **already-registered DB rows** (built earlier
via `upload_simulator`) — a client cannot use a dispatch request to point at
an arbitrary, not-yet-built commit. Picking a commit and dispatching a run
are two separate steps behind two separate API calls, and only the first one
can name a git ref.

## 4. The container entrypoint is generic and workload-blind

`sms-ecoli/docker/ray-batch-entrypoint.sh` forms the Ray cluster from AWS
Batch's own gang-scheduling env vars, stages inputs from a fixed S3 URI, and
on the head node runs `bash -lc "${RAY_JOB_CMD}"` verbatim (around line 295)
— the same script drives ParCa jobs, comparison-ensemble jobs, and
chain-dispatch jobs alike. It has zero `v2ecoli`/`batch_baseline`-specific
knowledge; it is a generic launcher.

`RAY_JOB_CMD` reaches the container only as an **environment variable**
override — never an `image` or `command` override at the AWS Batch
job-definition level. `sms-cdk/lib/ray-batch-stack.ts:231,242` fix `image`
and `command` on the job definition itself, both outside any per-dispatch
request's reach. A dispatch can change what arguments the command receives;
it cannot change the command, and it cannot change the image.

## 5. Package/repo identity — what actually runs

The build recipe (`viva_api/simulation/simulation_service_ray.py:867-904`):
clone the `SimulatorVersion` DB row's own `{git_repo_url, git_branch,
git_commit_hash}` into a fresh directory, check out that exact commit, then
run `sms-ecoli/docker/build-and-push-ecr.sh` from that fresh clone.

- `sms-ecoli/docker/build-and-push-ecr.sh:27,87` builds from that exact
  clone's own root — nothing else.
- `sms-ecoli/Dockerfile:25-26`: `WORKDIR /app/v2ecoli` then `COPY . .` — the
  image's `v2ecoli` Python package literally *is* that checked-out tree.
- `sms-ecoli/pyproject.toml:6`: `name = "v2ecoli"` confirms the package
  name.

That package is sourced from **`CovertLabEcoli/sms-ecoli`** specifically (a
private repo) — distinct from the separate, public
**`vivarium-collective/v2ecoli`** GitHub repo, which is a different project
this ecosystem also references elsewhere. Same package name, different repo.
This distinction matters: same-named-package/different-repo confusion has
caused real, silent-failure incidents in this ecosystem before — dispatches
that looked like they targeted one repo but silently ran the other's code.

A separate `vivarium-collective/vEcoli` clone also exists inside the image
(`sms-ecoli/Dockerfile:64-67`) — a distinct upstream comparison project,
capital-E "vEcoli", not lowercase "v2ecoli" — but only to support a separate
`--composite vecoli` comparison-driver feature. It is **never** pip-installed
as the `v2ecoli` package itself.

So there are **three** similar-looking names in play here, and they are not
interchangeable:

| Name | What it is |
|---|---|
| `v2ecoli` | The installed Python package name (`sms-ecoli/pyproject.toml:6`) |
| `sms-ecoli` (`CovertLabEcoli/sms-ecoli`) | The private GitHub repo a remote-pinned dispatch's image is actually built from |
| `vivarium-collective/v2ecoli` | A *different*, public GitHub repo — same package name, **not** the source of a remote-pinned dispatch's image |
| `vEcoli` (`vivarium-collective/vEcoli`) | A third, distinct upstream comparison project, bundled read-only in the image for `--composite vecoli` comparisons only — never installed as `v2ecoli` |

Worth being extra careful here: seeing "v2ecoli" in a log line or a UI label
does not, by itself, tell you which of these it means.

## Practical implications

- A workspace Study's own `spec.yaml` `baseline[].composite` field does not
  control which composite code runs remotely once a dispatch has more than
  one generation — it's always `batch_baseline`, fixed in viva-api
  (`simulation_service_ray.py:107,968-971`). Don't debug a "wrong composite
  ran" symptom by looking at the Study spec; look at what image/commit was
  pinned via `simulator_id`.
- Several `batch_baseline` parameters that look like per-dispatch knobs
  (`single_daughters`, `time_step`, `max_duration`, `variants`, `emitter`,
  `study`) are not reachable from any client request today — changing them
  requires a new pinned image build, not a different dispatch payload.
- A misspelled or unsupported override key doesn't fail fast: it raises
  inside the container, at runtime, after the job is already scheduled and
  running — not at `POST /simulations` time.
- Before assuming code identity from the name "v2ecoli" alone, check which
  of the three things in the table in §5 is actually meant: the installed
  package, the private `sms-ecoli` repo, or the public
  `vivarium-collective/v2ecoli` repo — and don't confuse either with the
  third, unrelated project, `vEcoli`.
