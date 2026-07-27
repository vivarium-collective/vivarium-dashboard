# Reproducible Rerun Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make workbench reruns reproduce the original result — env-versioned, verifiable, and retrievable from saved artifacts — with one canonical run-record path.

**Architecture:** Every run already stamps a replay *manifest* (`composite_runs.build_run_manifest`) into `runs_meta`. This plan (1) completes that manifest with a reconstructable `env_id`, (2) makes reruns replay it (instead of re-deriving from mutable `study.yaml`), (3) verifies reproduction via a `result_fingerprint`, (4) retrieves saved artifacts instead of recomputing when a matching run exists, (5) flags environment drift into the existing `needs_attention` signals, and (6) consolidates the four divergent run-record writers into one. Additive DB columns; no run-subsystem re-architecture.

**Tech Stack:** Python 3.12, FastAPI (`vivarium_workbench/api/app.py`), SQLite `runs_meta` (`vivarium_workbench/lib/composite_runs.py`), pytest (`dashboard_client` fixture spawns the live app), vanilla JS frontend, `uv` for deps. Cross-repo: `viva_superpowers` (run_registry, study_audit, needs_attention) in `pbg-superpowers`.

## Global Constraints

- Additive DB changes only — new **nullable** columns via `composite_runs._NEW_COLUMNS`; a missing column must never break an old workspace.
- Env/fingerprint capture is **best-effort** — any field that can't resolve degrades to `null`; capture failures log and never block a run.
- A rerun **always mints a new `run_id`** — never overwrite.
- Every mutating endpoint calls `_csrf_ok()`; bypass in tests with `VIVARIUM_WORKBENCH_DISABLE_CSRF=1`.
- Rerun/Reproduce UI is **live-only** — hidden/disabled in snapshot mode.
- Run logic lives in `lib/`; `api/app.py` only routes + returns a pydantic model.
- Real logic is tested against the live app via the `dashboard_client` fixture (`tests/conftest.py`); fixture workspaces live under `tests/_fixtures/`.
- `result_fingerprint` hashes a **declared** `fingerprint_fields` set (default = the study's declared observables), on rounded/canonical values — never volatile fields (timestamps, paths, run_id).

---

### Task 0: Phase 0 — land the stranded reproducibility foundation (integration, not TDD)

**Why:** `env_id`/`result_fingerprint` stamp into the run record and Task 1 consolidates writers — both are unstable while the data model + audit are mid-migration. Land these first.

**Branches to land (per-commit cherry-pick onto current `origin/main`, verify deliverables-only, base-gap-safe — same discipline as the investigation-hardening merges):**
- v2ecoli `study-registry-migration` — data-model canonicalization (dual study layout → one; `conditions.baseline/variants` schema).
- pbg-superpowers `feat/study-audit-l0-l5` — `viva_superpowers/study_audit.py` L0–L5 evaluator + tests.
- v2ecoli `feat/audit-ci-gate` — the `audit-gate` CI job + `workspace/known_audit_failures.txt` ratchet.

- [ ] **Step 1:** For each branch, `git fetch` it into a worktree off current `origin/main`; inspect `git log --oneline origin/main..BRANCH` and confirm the diff is the intended migration/audit content (no base-gap phantom reversions).
- [ ] **Step 2:** Cherry-pick per-commit onto a fresh branch off current `origin/main`; resolve conflicts against the current data model; `git diff --stat origin/main HEAD` shows only migration/audit files.
- [ ] **Step 3:** Run the workspace conformance + audit locally: `uv run python -m viva_superpowers.study_audit --workspace workspace --package v2ecoli.composites --gate --allowlist workspace/known_audit_failures.txt` → exits 0 (hard checks pass; known failures parked).
- [ ] **Step 4:** Open PR; CI green (`audit-gate`, `behavior-tests`, `fast-tests`); land.
- **Done when:** current `origin/main` (v2ecoli + pbg-superpowers) has one study layout, `study_audit.py` present, and `audit-gate` green in CI. **Do not start Task 1 until this is true.**

---

### Task 1: One run-record writer with the manifest always present (item 1 / G6)

**Files:**
- Modify: `vivarium_workbench/lib/composite_runs.py` (`build_run_manifest` ~151-200, `save_metadata`/`_NEW_COLUMNS` ~203-235)
- Modify: `pbg-superpowers/viva_superpowers/run_registry.py` (DDL ~21-35, `register_run`) — add `manifest_json` column so bespoke `run-script` runs are replayable
- Test: `vivarium-workbench/tests/test_composite_runs.py`, `pbg-superpowers/tests/test_run_registry.py`

**Interfaces:**
- Consumes: existing `build_run_manifest(...) -> dict`, `save_metadata(..., manifest: dict|None)`.
- Produces: `runs_meta` rows from **both** writers carry a non-null `manifest_json` for new runs. A shared manifest schema `version: 2` (adds `env`, `seed`, `fingerprint_fields`, `result_fingerprint` keys — filled by later tasks; present-as-null now).

- [ ] **Step 1: Write the failing test** — a run registered via `viva_superpowers.run_registry.register_run(...)` produces a `runs_meta` row whose `manifest_json` is present and parses to a dict with `version == 2`.

```python
# pbg-superpowers/tests/test_run_registry.py
def test_register_run_stamps_manifest_v2(tmp_workspace):
    reg = run_registry.register_run(tmp_workspace, spec_id="ecoli", params={"seed": 0}, n_steps=10)
    row = run_registry.latest_run(tmp_workspace)
    m = json.loads(row["manifest_json"])
    assert m["version"] == 2
    assert m["params"]["seed"] == 0
```

- [ ] **Step 2: Run to verify it fails** — `pytest tests/test_run_registry.py::test_register_run_stamps_manifest_v2 -x` → FAIL (`manifest_json` KeyError / column missing).
- [ ] **Step 3: Implement** — add `manifest_json` to the `run_registry` DDL + `_NEW_COLUMNS` migration; have `register_run` build the manifest (reuse/port `build_run_manifest`) and write it. Bump both writers' manifest `version` to 2 with the new (null-for-now) keys.
- [ ] **Step 4: Run to verify pass**; also run the existing `test_composite_runs.py` manifest tests → still green (no regression on the workbench writer).
- [ ] **Step 5: Commit** — `feat(runs): unify run-record writers on manifest v2 (always present)`.

- [ ] **Step 6:** Retire the legacy `cli_runs.rerun` (`vwb rerun`) path: make `vivarium_workbench/cli.py:285-288` call `lib.rerun.run_rerun` (the one path) or emit a deprecation and delegate. Test: `test_cli.py` asserts `vwb rerun <id>` routes through `lib.rerun`. Commit `refactor(rerun): single rerun path; deprecate cli_runs.rerun`.

---

### Task 2: Reconstructable `env_id` in the manifest (item 2 / G1)

**Files:**
- Create: `vivarium_workbench/lib/env_fingerprint.py` — `compute_env() -> dict`, `env_id(env: dict) -> str`
- Modify: `vivarium_workbench/lib/composite_runs.py` (`build_run_manifest` → embed `env` + `env_id`; add `env_id TEXT` to `_NEW_COLUMNS`)
- Modify: `v2ecoli/scripts/run_condition_multigen_parquet.py` — thread the already-computed `cache_fingerprint` (139-156) into the manifest
- Test: `vivarium-workbench/tests/test_env_fingerprint.py`

**Interfaces:**
- Produces: `compute_env() -> {workspace_commit, sim_packages: {pkg: {version, git_sha}}, lockfile_hash, python, platform, cache_fingerprint}`; `env_id(env) -> str` (16-hex sha256 over canonical(env)). Stored on `runs_meta.env_id` and in `manifest["env"]`.

- [ ] **Step 1: Write the failing test** — `env_id` is stable under key reordering and changes when a package version changes.

```python
# tests/test_env_fingerprint.py
def test_env_id_stable_and_sensitive():
    base = {"workspace_commit": "abc", "sim_packages": {"v2ecoli": {"version": "1.2", "git_sha": "d"}},
            "lockfile_hash": "L", "python": "3.12.1", "platform": "mac", "cache_fingerprint": "cf"}
    reordered = dict(reversed(list(base.items())))
    assert env_id(base) == env_id(reordered)
    bumped = {**base, "sim_packages": {"v2ecoli": {"version": "1.3", "git_sha": "d"}}}
    assert env_id(base) != env_id(bumped)
```

- [ ] **Step 2: Run to verify it fails** — module doesn't exist yet.
- [ ] **Step 3: Implement** `env_fingerprint.py` — `compute_env()` reads: workspace git HEAD (reuse the existing best-effort git read), `importlib.metadata.version` + best-effort `__file__` git sha for `v2ecoli`/`process-bigraph`/`bigraph-schema`/`viva_superpowers`, sha256 of the workspace `uv.lock` if present, `platform.python_version()`, `platform.platform()`, and the passed-in `cache_fingerprint`. `env_id` = `sha256(json.dumps(env, sort_keys=True))[:16]`. Every field best-effort → `null` on failure.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5:** Wire into `build_run_manifest` (embed `env`+`env_id`) + `_NEW_COLUMNS`; a study launch test asserts `runs_meta.env_id` is non-null and `manifest["env"]["lockfile_hash"]` present. Commit `feat(runs): stamp reconstructable env_id (pkg versions + uv.lock + python + cache fp)`.

---

### Task 3: `result_fingerprint` + verify-reproduction (item 5 / G4)

**Files:**
- Create: `vivarium_workbench/lib/result_fingerprint.py` — `fingerprint_run(run_dir, fingerprint_fields) -> str`
- Modify: `vivarium_workbench/lib/run_runner.py` (`execute` completion tail) — compute + store `result_fingerprint`; add column
- Modify: `vivarium_workbench/lib/rerun.py` (`run_rerun`) — after a Reproduce completes, compare fingerprints
- Test: `tests/test_result_fingerprint.py`, `tests/test_rerun.py`

**Interfaces:**
- Consumes: `manifest["fingerprint_fields"]` (default = study's declared observables, resolved at launch).
- Produces: `fingerprint_run(run_dir, fields) -> str` (sha256 over rounded canonical values of the declared fields read from the run's emitter output); `runs_meta.result_fingerprint`; `runs_meta.provenance_status` set to `nondeterministic` on a verified mismatch.

- [ ] **Step 1: Write the failing test** — identical declared-field values → identical fingerprint; a changed value → different.

```python
# tests/test_result_fingerprint.py
def test_fingerprint_ignores_volatile_matches_on_declared(tmp_run_dir):
    write_outputs(tmp_run_dir, doubling_time=42.0, ran_at="2026-01-01T00:00Z")
    fp1 = fingerprint_run(tmp_run_dir, ["doubling_time"])
    write_outputs(tmp_run_dir, doubling_time=42.0, ran_at="2026-02-02T00:00Z")  # volatile changed
    assert fingerprint_run(tmp_run_dir, ["doubling_time"]) == fp1               # same declared → same fp
```

- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Implement** `fingerprint_run` — read declared fields from the run's canonical output (parquet/summary), round floats to a fixed precision, `sha256(json.dumps(sorted_pairs))`. Missing field → recorded as `null` in the hashed payload (deterministic).
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5:** In `run_runner.execute` completion, compute + store `result_fingerprint` (+ `_NEW_COLUMNS`). Commit `feat(runs): result_fingerprint over declared fields`.
- [ ] **Step 6: Verify-reproduction test** — a Reproduce whose env_id+seed match the original asserts equal fingerprints; an injected divergence sets `provenance_status='nondeterministic'`. Implement the compare in `run_rerun`'s completion callback. Commit `feat(rerun): verify reproduction via result_fingerprint`.

---

### Task 4: Reproduce == replay manifest; two buttons; first-class seed (item 3 / G2)

**Files:**
- Modify: `vivarium_workbench/lib/rerun.py` (`run_rerun`, `resolve_rerun_target` — always prefer manifest)
- Modify: `vivarium_workbench/lib/study_runs.py` (`launch_into_study` takes explicit replay inputs incl. `seed`)
- Modify: `vivarium_workbench/lib/run_core.py` (`invoke_run`/`RunPlan` — thread `seed`)
- Modify: `vivarium_workbench/api/app.py` — split study/investigation rerun into `/api/study-reproduce` (manifest) vs `/api/study-run-baseline` (re-derive, existing)
- Modify: `static/study-detail.js`, `templates/study-detail.html`, `static/walkthrough.js` — two distinct buttons "Reproduce" / "Run current spec", live-only
- Test: `tests/test_rerun.py`, `tests/test_study_runs.py`

**Interfaces:**
- Consumes: `manifest` (params, seed, emitter, emit_paths, runtime).
- Produces: `launch_into_study(ws_root, study, spec_id, params, n_steps, *, seed, emitter, emit_paths, runtime)`; endpoint `POST /api/study-reproduce {study, run_id}` → `ReproduceResult`.

- [ ] **Step 1: Write the failing test** — "Reproduce study" forwards the manifest's `seed`+`params` verbatim (a spec-YAML edit made after the original run does NOT change what Reproduce launches).

```python
# tests/test_rerun.py
def test_reproduce_replays_manifest_not_current_yaml(dashboard_client, ws_with_run):
    original = ws_with_run.latest_run()            # manifest seed=7, param X=1
    edit_study_yaml(ws_with_run, param_X=999)      # mutate current spec
    resp = dashboard_client.post("/api/study-reproduce", {"study": ws_with_run.slug, "run_id": original.run_id})
    launched = ws_with_run.run(resp["run_id"])
    assert launched.manifest["params"]["X"] == 1 and launched.manifest["seed"] == 7
```

- [ ] **Step 2: Run to verify it fails** — endpoint missing / re-derives from YAML.
- [ ] **Step 3: Implement** `launch_into_study` explicit-inputs signature + thread `seed` through `run_core.invoke_run`; add `/api/study-reproduce` → `run_rerun` manifest path; keep `/api/study-run-baseline` as "Run current spec."
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5:** Frontend — replace the single ambiguous "Rerun study/investigation" with two buttons; per-row `↻ Rerun` → `/api/study-reproduce`; hide in snapshot mode. Test frontend render (both buttons present live, absent in snapshot). Commit `feat(rerun): Reproduce (manifest) vs Run-current-spec (re-derive); first-class seed`.

---

### Task 5: Env-drift detection + pin (item 4 / G3)

**Files:**
- Modify: `vivarium_workbench/lib/rerun.py` — on Reproduce, diff run `env_id` vs `compute_env()`; set `provenance_status='env_stale'`
- Modify: `pbg-superpowers/viva_superpowers/needs_attention.py` — new signal kinds `env_stale`, `nondeterministic`
- Modify: `pbg-superpowers/skills/viva-report/SKILL.md` — Pass A surfaces the new signals (Case History)
- Support: `study.yaml` optional `pinned_env:` honored (skip flag)
- Test: `tests/test_rerun.py`, `pbg-superpowers/tests/test_needs_attention.py`

**Interfaces:**
- Consumes: `runs_meta.env_id`, `env_fingerprint.compute_env`, `study.yaml.pinned_env`.
- Produces: `needs_attention` entries `{kind: "env_stale"|"nondeterministic", study, run_id, detail}`.

- [ ] **Step 1: Write the failing test** — a run stamped at env A, reproduced under env B → `provenance_status='env_stale'` and a `needs_attention` `env_stale` entry; `pinned_env` suppresses it.

```python
# pbg-superpowers/tests/test_needs_attention.py
def test_env_stale_surfaces_unless_pinned(ws_two_envs):
    ws_two_envs.reproduce(run_at_env="A", current_env="B")
    assert any(s["kind"] == "env_stale" for s in needs_attention.scan(ws_two_envs.root, ws_two_envs.inv))
    ws_two_envs.set_pinned_env(ws_two_envs.slug, env_id="A")
    assert not any(s["kind"] == "env_stale" for s in needs_attention.scan(ws_two_envs.root, ws_two_envs.inv))
```

- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Implement** the diff in `run_rerun` (set `provenance_status`), the two new `needs_attention` signal kinds, and `pinned_env` suppression.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5:** Update `viva-report` SKILL Pass A to list `env_stale`/`nondeterministic` under Case History (doc + a Pass-A test if one exists). Commit `feat(repro): env-drift detection + pinned_env, surfaced via needs_attention`.

---

### Task 6: Retrieve-before-recompute over saved runs (item 7 / G5)

**Files:**
- Create: `vivarium_workbench/lib/run_index.py` — `find_matching_run(ws, composite_id, config, seed, env_id) -> row|None`
- Modify: `vivarium_workbench/lib/rerun.py` (`run_rerun`) — retrieve-or-compute
- Test: `tests/test_run_index.py`, `tests/test_rerun.py`

**Interfaces:**
- Consumes: consolidated `runs_meta` (composite_id, canonicalized params, seed, env_id, result_fingerprint, artifact path, status).
- Produces: `find_matching_run(...) -> row|None`; `run_rerun` serves the saved artifact (no launch) when a completed match with intact outputs exists.

- [ ] **Step 1: Write the failing test** — a second Reproduce with a saved matching run serves it WITHOUT launching a subprocess; a drifted `env_id` forces recompute.

```python
# tests/test_rerun.py
def test_reproduce_retrieves_saved_run(dashboard_client, ws_with_completed_run, monkeypatch):
    spy = install_launch_spy(monkeypatch)     # asserts launcher not called
    resp = dashboard_client.post("/api/study-reproduce", {"study": ws.slug, "run_id": ws.completed.run_id})
    assert resp["retrieved"] is True and spy.launch_count == 0
    ws.bump_env()                             # env drift → different env_id
    resp2 = dashboard_client.post("/api/study-reproduce", {"study": ws.slug, "run_id": ws.completed.run_id})
    assert resp2["retrieved"] is False and spy.launch_count == 1
```

- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Implement** `run_index.find_matching_run` (query `runs_meta` by canonical key; verify artifact path exists + fingerprint non-null); `run_rerun` returns `{retrieved: True, run_id: <existing>}` on hit, else computes.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat(rerun): retrieve saved artifacts before recomputing`.

---

### Task 7: Investigation rerun executes the DAG in order (item 6 / G2)

**Files:**
- Modify: `vivarium_workbench/lib/rerun.py` (`rerun_investigation`)
- Consume: the L5 topological order from `viva_superpowers.study_audit` (`inputs.from` DAG)
- Test: `tests/test_rerun.py`

**Interfaces:**
- Consumes: `study_audit` topological order over `inputs.from`.
- Produces: `rerun_investigation(...) -> {order: [slugs], launched, skipped, errors}`; a downstream study is not launched until its upstreams reproduced/passed.

- [ ] **Step 1: Write the failing test** — for an investigation A→B→C, reproduce launches in order A,B,C and does not launch B before A completes.

```python
# tests/test_rerun.py
def test_investigation_reruns_in_dependency_order(ws_chain_ABC):
    result = rerun_investigation(ws_chain_ABC.root, ws_chain_ABC.inv)
    assert result["order"] == ["A", "B", "C"]
    assert launched_before(result, "A", "B") and launched_before(result, "B", "C")
```

- [ ] **Step 2: Run to verify it fails** — current impl is a flat fan-out.
- [ ] **Step 3: Implement** — compute the topological order via `study_audit`, iterate with prereq-passed gating, aggregate `{order, launched, skipped, errors}`.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat(rerun): investigation rerun executes the inputs.from DAG in order`.

---

## Self-Review

**Spec coverage:** G1→Task 2; G2→Tasks 4,7; G3→Task 5; G4→Task 3; G5→Task 6; G6→Task 1; Phase 0→Task 0. All spec goals mapped.

**Type consistency:** `env_id`, `result_fingerprint`, `provenance_status`, `manifest_json` are the runs_meta column names used consistently across Tasks 1–6; `launch_into_study(..., seed=...)` signature defined in Task 4 and consumed in Tasks 3/6; `compute_env`/`env_id` defined in Task 2 and consumed in Tasks 5/6.

**Placeholder scan:** each task has concrete files (`file:line` where modifying), a real failing test, and a commit. Where exact internal signatures matter (e.g. the run-completion tail in `run_runner.execute`, the `study_audit` topo API), the implementer reads the cited `file:line` first — the test's assertion pins the required behavior.

**Sequencing:** Task 0 (foundation) → 1 (writer/manifest) → 2 (env_id) → 3 (fingerprint) → 4 (reproduce) → 5 (drift) → 6 (retrieve) → 7 (DAG). Each later task depends only on earlier ones.
