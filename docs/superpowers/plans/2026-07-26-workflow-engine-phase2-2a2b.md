# Phase 2 (2a+2b) — Workflow Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Run an investigation's studies in topological `inputs.from` order with content-addressed pull-or-compute caching and producer→consumer artifact forwarding, exposed as an opt-in endpoint; the declared-order path stays the untouched default.

**Architecture:** Generalize the existing `lib/artifacts` engine. `study_interface` learns the canonical `conditions.baseline` form; `resolve_study` gains cycle detection; a new `resolve_investigation` topologically resolves members; `_default_compute` gets real `emit_paths` + injects producer artifact paths into the consumer run's `overrides`. A new `POST /api/investigation-resolve` spawns the DAG walk as a detached job.

**Tech Stack:** Python, `graphlib.TopologicalSorter`, FastAPI, pytest, the existing `lib/artifacts/{pipeline,store,hashing}.py` + `lib/run_runner.py` + `lib/composite_runs.py`.

## Global Constraints

- **Repo/worktree:** `~/code/vivarium-workbench--wf-engine`, branch `feat/workflow-engine-phase2` (off `origin/main` `3b2b1aa`, which includes #606). Verify `git branch --show-current` before each commit.
- **`RunRequest` is a fixed 10-key dataclass** (`lib/run_runner.py:26-55`): `run_id, spec_id, pkg, workspace, overrides, steps, emit_paths, db_file, log_path, target`. Config is carried under **`overrides`** (NOT `config`); db path key is **`db_file`**. There is **NO `inputs`/`initial_state` seam** — the only channel into a run is `overrides`.
- **Input forwarding convention:** a resolved producer artifact reaches its consumer run only through `overrides`. Inject the producer artifact's store path as `overrides["<artifact>_path"]`, and additionally special-case artifact name `sim_data` → `overrides["cache_dir"]` (v2ecoli's `ecoli_baseline` reads ParCa sim_data from `cache_dir`, default `out/cache`, at build time — `v2ecoli/composites/ecoli_baseline.py:622-635,927-950`).
- **Canonical study form (Phase 1):** models live under `conditions.baseline.{composite, params}` + `conditions.variants[]`. Migrated studies have NO top-level `composite`/`config`. `study_interface` currently reads only top-level → returns empty for migrated studies. It MUST read `conditions.baseline`.
- **Real `emit_paths`:** `composite_runs.collect_emit_paths_from_spec(spec)` (NOT `[]`).
- **Reproducibility/hashing (unchanged):** `hashing.artifact_id(composite_id, config, sorted(input_ids), commit)`; a consumer's `input_ids` are its producers' `artifact_id`s. Config MUST include the run's distinguishing params (`condition`, `seed`) so two studies differing only by seed don't collide.
- **Execution model:** `_default_compute` calls `run_runner.execute` **synchronously** (blocks until the run finishes), so `resolve_investigation` resolving nodes in topological order is naturally sequential. The 2b endpoint spawns `resolve_investigation` as a **detached subprocess** (runs outlive the request), following the `run_registry.spawn_detached` pattern.
- **Workbench conventions (CLAUDE.md):** new endpoint route in `api/app.py`, logic in `lib/`; POST endpoints call `_csrf_ok()`; return a pydantic model; use `atomic_io` for file writes; resolve paths via `workspace_paths`.
- **Test env:** offline unit tests inject a stub `compute_fn` (no server, no real engine) — the primary test mode. A real-engine integration test (Task 7) needs a real v2ecoli workspace + venv + ParCa cache and is run manually, not in the offline loop. Run offline tests with the worktree venv: `uv sync` then `.venv/bin/python -m pytest tests/test_<x>.py`.
- **Additive/opt-in:** do NOT change `lib/rerun.rerun_investigation` or `/api/investigation-rerun` (declared-order default stays).

---

### Task 1: `study_interface` reads canonical `conditions.baseline`

**Files:**
- Modify: `vivarium_workbench/lib/study_spec.py` (`study_interface`, ~lines 192-234)
- Test: `tests/test_study_spec_lib.py` (or a new `tests/test_study_interface_conditions.py`)

**Interfaces:**
- Produces: `study_interface(spec)` returns `composite` from `spec["composite"]` else `spec["conditions"]["baseline"]["composite"]`; `config` from `spec["config"]` else `spec["conditions"]["baseline"]["params"]` (a dict, default `{}`). `inputs`/`outputs`/`emitter` behavior unchanged.

- [ ] **Step 1: Write failing tests**
```python
from vivarium_workbench.lib.study_spec import study_interface

def test_interface_reads_conditions_baseline():
    spec = {"conditions": {"baseline": {"composite": "v2ecoli.composites.ecoli_baseline.ecoli_baseline",
            "params": {"condition": "acetate", "seed": 0}}},
            "inputs": [{"artifact": "sim_data", "from": "parca"}]}
    iface = study_interface(spec)
    assert iface["composite"] == "v2ecoli.composites.ecoli_baseline.ecoli_baseline"
    assert iface["config"] == {"condition": "acetate", "seed": 0}
    assert iface["inputs"] == [{"artifact": "sim_data", "from": "parca"}]

def test_interface_top_level_takes_precedence():
    spec = {"composite": "top.c", "config": {"a": 1},
            "conditions": {"baseline": {"composite": "cond.c", "params": {"b": 2}}}}
    iface = study_interface(spec)
    assert iface["composite"] == "top.c" and iface["config"] == {"a": 1}

def test_interface_no_models_is_empty():
    iface = study_interface({"name": "parca-like"})
    assert iface["composite"] is None and iface["config"] == {}
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_study_spec_lib.py -k interface -v` → the conditions test FAILS (returns composite=None).

- [ ] **Step 3: Implement.** In `study_interface`, before returning, fall back to conditions.baseline:
```python
    cond_baseline = ((spec.get("conditions") or {}).get("baseline")) or {}
    composite = spec.get("composite") or cond_baseline.get("composite")
    config = spec.get("config")
    if not config:
        config = dict(cond_baseline.get("params") or {})
    ...
    return {"composite": composite, "config": config, "inputs": inputs,
            "outputs": outputs, "emitter": spec.get("emitter")}
```
(Keep the existing `inputs`/`outputs` parsing + the `InvestigationSpecError` on malformed inputs.)

- [ ] **Step 4: Run tests to verify they pass** — expect PASS; run the whole file to confirm no regression.

- [ ] **Step 5: Commit** — `git add vivarium_workbench/lib/study_spec.py tests/test_study_spec_lib.py && git commit -m "feat(interface): study_interface reads conditions.baseline composite+params"`

---

### Task 2: Cycle detection in `resolve_study`

**Files:**
- Modify: `vivarium_workbench/lib/artifacts/pipeline.py` (`resolve_study`)
- Test: `tests/test_study_pipeline_resolve.py`

**Interfaces:**
- Produces: `class CyclicDependencyError(Exception)` in `pipeline.py`. `resolve_study(ws_root, slug, *, compute_fn=None, _in_progress=None)` raises `CyclicDependencyError` (naming the cycle path) when a slug is re-entered while already on the recursion stack.

- [ ] **Step 1: Write failing test** (inject a compute_fn + a fake 2-study cyclic workspace, or monkeypatch the interface loader). Use the file's existing fixture style:
```python
def test_resolve_study_detects_cycle(tmp_path, monkeypatch):
    from vivarium_workbench.lib.artifacts import pipeline
    # a -> b -> a
    ifaces = {"a": {"composite": "c.a", "config": {}, "inputs": [{"artifact": "x", "from": "b"}], "outputs": []},
              "b": {"composite": "c.b", "config": {}, "inputs": [{"artifact": "x", "from": "a"}], "outputs": []}}
    monkeypatch.setattr(pipeline, "_load_interface", lambda ws, slug: ifaces[slug])  # adapt to real loader name
    with pytest.raises(pipeline.CyclicDependencyError):
        pipeline.resolve_study(tmp_path, "a", compute_fn=lambda **k: tmp_path)
```
(Adapt the monkeypatch target to however `resolve_study` currently loads a study's interface — read the function first and patch the real seam.)

- [ ] **Step 2: Run to verify it fails** — `RecursionError` or hang → confirms no cycle guard. (If it would infinitely recurse, the test proves the need.)

- [ ] **Step 3: Implement.** Thread `_in_progress: set[str]` through the recursion; at entry `if slug in _in_progress: raise CyclicDependencyError(" -> ".join([*_in_progress, slug]))`; add on entry, discard on exit (try/finally).

- [ ] **Step 4: Run tests to verify pass** (new test + existing resolve tests).

- [ ] **Step 5: Commit** — `git commit -m "feat(pipeline): cycle detection in resolve_study (CyclicDependencyError)"`

---

### Task 3: `resolve_investigation` — topological resolve + per-node result

**Files:**
- Modify: `vivarium_workbench/lib/artifacts/pipeline.py` (add `resolve_investigation`)
- Test: `tests/test_resolve_investigation.py` (new)

**Interfaces:**
- Consumes: `investigation_member_slugs` (`lib/investigation_members.py`) = `members or studies`.
- Produces: `resolve_investigation(ws_root, inv_slug, *, compute_fn=None, force=False) -> dict` = `{"order": [slug,...], "nodes": [{"slug", "artifact_id"|None, "status": "cached"|"computed"|"skipped"|"failed", "inputs": [from,...]}], "error": None|str}`. Builds the member DAG from each member's `inputs.from` (edges to producers that are members or known upstream), topologically orders via `graphlib.TopologicalSorter`, and `resolve_study` each in order. `force=True` bypasses the cache (pass through so compute always runs). A node whose upstream `failed`/`skipped` is itself `skipped` (not resolved). A `CyclicDependencyError` (or `graphlib.CycleError`) sets `error` and leaves nodes unresolved.

- [ ] **Step 1: Write failing tests** (offline, injected `compute_fn`; fake a small workspace or monkeypatch the member+interface loaders):
```python
def test_resolve_investigation_topo_order_and_cache(...):
    # diamond: parca -> a, parca -> b, {a,b} -> c
    # first resolve: all computed, order has parca before a,b before c
    # second resolve: all cached (compute_fn not called)
def test_upstream_change_rekeys_descendants(...):
    # change a's config -> a + c recompute, parca + b cached
def test_upstream_failure_skips_descendants(...):
    # compute_fn raises for 'a' -> a=failed, c=skipped, b=computed
def test_cycle_reports_error(...):
    # a<->b -> result["error"] set, no crash
def test_force_bypasses_cache(...):
```
(Build a helper that fakes `investigation_member_slugs` + `study_interface` + a counting `compute_fn`.)

- [ ] **Step 2: Run to verify fail** — module has no `resolve_investigation`.

- [ ] **Step 3: Implement `resolve_investigation`** using `graphlib.TopologicalSorter` over member `inputs.from` edges, then `resolve_study` per node in `static_order()`, tracking a `failed_or_skipped` set to mark descendants `skipped`, catching per-node exceptions → `failed`. Detect cache-hit by comparing the returned artifact against the store before/after (or have `resolve_study` return a `(dir, cached)` — adapt minimally; simplest: check `store.has(oid)` isn't directly exposed, so wrap: a node is `cached` if `compute_fn`/`_default_compute` was NOT invoked — track via a sentinel).

- [ ] **Step 4: Run tests to verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat(pipeline): resolve_investigation topological pull-or-compute over inputs.from"`

---

### Task 4: Real `emit_paths` in `_default_compute`

**Files:**
- Modify: `vivarium_workbench/lib/artifacts/pipeline.py` (`_default_compute`, the request dict)
- Test: `tests/test_pipeline_end_to_end.py` (or `test_study_pipeline_resolve.py`)

**Interfaces:**
- `_default_compute` sets `request["emit_paths"] = composite_runs.collect_emit_paths_from_spec(spec)` where `spec` is the loaded study.yaml spec (load it in `_default_compute` if not already available), falling back to `[]` (which `run_runner._emit_paths_for` expands to all-store) only when the study declares no observables.

- [ ] **Step 1: Write failing test** — a study spec with `readouts`/`tests[].measure.path`; assert the request's `emit_paths` is non-empty and contains the readout path (inject a fake `run_runner.execute` that captures the written `request.json`).

- [ ] **Step 2: Run to verify fail** (current code writes `emit_paths=[]`).

- [ ] **Step 3: Implement** — import `composite_runs`; load the study spec; `emit_paths = composite_runs.collect_emit_paths_from_spec(spec) or []`.

- [ ] **Step 4: Run tests to verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat(pipeline): _default_compute derives real emit_paths from study spec"`

---

### Task 5: Producer artifact → consumer `overrides` injection

**Files:**
- Modify: `vivarium_workbench/lib/artifacts/pipeline.py` (`resolve_study` passes resolved input artifact paths to `compute_fn`; `_default_compute` injects them into `overrides`)
- Test: `tests/test_study_pipeline_resolve.py`

**Interfaces:**
- `resolve_study` passes a `resolved_inputs: dict[str, Path]` (artifact-name → store path of the producer's artifact) to `compute_fn(..., resolved_inputs=...)`. `_default_compute` merges into `overrides`: for each `(artifact, path)`, set `overrides[f"{artifact}_path"] = str(path)`; if `artifact == "sim_data"`, also set `overrides["cache_dir"] = str(path)`. (Documents the v2ecoli sim_data→cache_dir convention; a producer whose artifact can't map is still ordered-before via the DAG, so correctness holds even if a run reads its input via the pre-existing shared cache.)

- [ ] **Step 1: Write failing test** — resolve a 2-study chain (producer → consumer, `inputs: [{artifact: sim_data, from: producer}]`) with a capturing `compute_fn`; assert the consumer compute receives `resolved_inputs["sim_data"]` = the producer's store path; and (unit-testing `_default_compute`'s override merge separately) assert `overrides["cache_dir"]` is set.

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement** the `resolved_inputs` threading + the `_default_compute` override merge (with the `sim_data`→`cache_dir` special-case).

- [ ] **Step 4: Run tests to verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat(pipeline): forward producer artifact paths into consumer run overrides (sim_data->cache_dir)"`

---

### Task 6: `POST /api/investigation-resolve` (opt-in, detached)

**Files:**
- Create: `vivarium_workbench/lib/investigation_resolve_views.py`
- Modify: `vivarium_workbench/api/app.py` (add the route), `vivarium_workbench/lib/models.py` (response model)
- Test: `tests/test_investigation_resolve_api.py` (new)

**Interfaces:**
- Produces: `POST /api/investigation-resolve` body `{investigation: str, force?: bool}` → spawns `resolve_investigation` as a detached subprocess (a small CLI worker, mirroring `run_registry.spawn_detached` + a `cli` subcommand, OR — if a synchronous small-DAG resolve is acceptable for the test path — call inline for the offline test and detach in production). Returns `202 {"status": "resolving", "investigation": ...}` (detached) or the structured result (inline). The declared-order `/api/investigation-rerun` is untouched.
- The route calls `_csrf_ok()` and returns a pydantic model (`lib/models.py`).

- [ ] **Step 1: Write failing test** — using the `dashboard_client` fixture against a fixture workspace with a tiny 2-study investigation, POST `/api/investigation-resolve` and assert a 200/202 with the expected shape (for the test, an INLINE synchronous resolve over an injected/stub compute is acceptable — gate the detach behind a `detach=True` default that the test overrides, or expose the result synchronously for a trivially-cached investigation).

- [ ] **Step 2: Run to verify fail** (route 404).

- [ ] **Step 3: Implement** the view + route + model. Follow `composite_test_run_views.py` for the detached-spawn pattern and `run_registry.spawn_detached` (a new `cli` subcommand `resolve-investigation --workspace --investigation [--force]` calling `resolve_investigation`).

- [ ] **Step 4: Run tests to verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat(api): POST /api/investigation-resolve (opt-in topological pull-or-compute)"`

---

### Task 7: Real-data integration validation (manual)

**Files:** none (a validation script/log; not a CI test)

Run against a REAL v2ecoli workspace with a ParCa cache present (e.g. a chain `parca → baseline → downstream`, or a `showcase-1-parca → showcase-2` chain). This exercises the actual engine (`run_runner.execute` → real sim) and is too heavy for the offline loop.

- [ ] **Step 1:** Serve/point at a real workspace; call `resolve_investigation(ws_root, "<inv>")` once. Confirm: topological order runs producers first; artifacts land in `.pbg/artifacts/`; each node reports `computed`.
- [ ] **Step 2:** Call it again unchanged. Confirm: all nodes `cached`, no recompute (0 new runs).
- [ ] **Step 3:** Change one study's `conditions.baseline.params` (e.g. a seed) and re-resolve. Confirm: only that study + its descendants recompute; upstream stays cached; `artifact_id`s differ for the changed subtree.
- [ ] **Step 4:** Record the results (order, cache hits, selective recompute) in the PR description. Do NOT gate CI on this heavy run.

---

## Self-Review

**Spec coverage:** §3.1 emit_paths → Task 4; §3.1 input forwarding → Task 5; §3.2 cycle detection → Task 2; §3.3 resolve_investigation → Task 3; §3.4 hashing (config incl seed) → Task 1 (surfaces params into config) + verified in Task 7; §4 endpoint → Task 6; §5 testing → Tasks 1-6 unit + Task 7 integration; §6 open questions all resolved in Global Constraints + Tasks 1/4/5/6. `study_interface` gap (grounding Q5) → Task 1.

**Placeholder scan:** each code step has concrete code or an exact function/convention; the two "adapt to the real loader/seam" notes (Task 2 monkeypatch target, Task 3 cache-hit detection) are read-first instructions with the intent fully specified, not deferrals.

**Type consistency:** `study_interface -> {composite,config,inputs,outputs,emitter}`; `resolve_study(..., _in_progress, compute_fn)` raising `CyclicDependencyError`; `resolve_investigation(...) -> {order,nodes,error}`; `_default_compute` overrides-injection + emit_paths — consistent across tasks.

## Notes / risks

- **parca is a special producer** (it builds the ParCa `out/cache`, not a normal composite run). Its output artifact ≠ a normal run store; the `sim_data`→`cache_dir` convention (Task 5) targets the consumer, and the DAG ordering guarantees parca runs before its consumers even if parca's own compute stays the existing cache-build. If parca's node needs a bespoke `compute_fn`, note it in Task 7; don't block the offline tasks on it.
- **Heavy integration** (Task 7) is manual — the offline tasks (1-6) are the CI-gated deliverable; they fully build + unit-test the engine + endpoint with injected compute, with real-engine validation done interactively.
