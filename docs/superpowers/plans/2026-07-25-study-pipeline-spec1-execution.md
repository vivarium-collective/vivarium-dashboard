# Study Pipeline Spec 1 — Deterministic Execution: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make study execution deterministic and reusable: content-addressed artifacts (produced once, pulled everywhere), a registry-only study layout with investigations as pure references, and a pull-or-compute rerun pipeline.

**Architecture:** A thin content-addressed layer *wrapping* the existing run engine (`run_core.invoke_run` / `run_runner.execute`) — not a rewrite. New code lives under `vivarium_workbench/lib/artifacts/`. Study loading + investigation-graph building are updated to the registry/reference model. A one-shot migrator moves the 26 nested studies into `studies/<slug>/`.

**Tech Stack:** Python 3.12, FastAPI dashboard, pytest (existing `dashboard_client` fixture + `tests/_fixtures/`), SQLite (`runs.db`), YAML study/investigation specs. Design: `docs/superpowers/specs/2026-07-25-study-pipeline-spec1-execution.md`.

## Global Constraints

- **Reuse the engine.** The compute path stays `run_core.invoke_run(...)` / `run_runner.execute(request_path)`. New code gates it (hash → pull-or-compute) and records artifact pointers; it does not reimplement running.
- **Hash formula (canonical):** `artifact_id = sha256( composite_id + "\n" + canonical(config) + "\n" + "\n".join(sorted(input_artifact_ids)) + "\n" + workspace_git_commit )`, hex, truncated to 16 chars for paths (full hash in meta). `canonical(config)` = `json.dumps(config, sort_keys=True, separators=(",",":"), default=_stable_number)`. `config` **includes** `seed`.
- **Store location:** `wp.pbg / "artifacts" / <artifact_id>/` — resolve via `WorkspacePaths`, never hardcode `.pbg`.
- **No duplicated blobs:** `runs.db` records only `{stage: artifact_id}` pointers; payloads live only in the store.
- **Registry-only:** all studies resolve from `wp.studies / <slug>`. A guard test fails if any `study.yaml` exists under `wp.investigations`.
- **Determinism:** every stage is skipped (store hit) when its `artifact_id` already exists. No wall-clock, RNG, or `latest_run` in the hash or the resolve path.
- **Back-compat:** the workbench serves existing workspaces; unknown/legacy `study.yaml` fields must not crash loaders (additive schema).

---

## File Structure

- Create: `vivarium_workbench/lib/artifacts/__init__.py`
- Create: `vivarium_workbench/lib/artifacts/hashing.py` — `canonical(config)`, `artifact_id(...)`
- Create: `vivarium_workbench/lib/artifacts/store.py` — `ArtifactStore` (has/get/put/meta)
- Create: `vivarium_workbench/lib/artifacts/pipeline.py` — `resolve_study(...)` pull-or-compute
- Create: `vivarium_workbench/lib/study_migrate.py` — nested→registry migrator
- Modify: `vivarium_workbench/lib/study_spec.py` — parse+validate `inputs/outputs/composite/config/emitter`
- Modify: `vivarium_workbench/lib/investigation_graph_views.py` — members + derived edges
- Modify: `vivarium_workbench/cli.py` — `vivarium-workbench migrate-studies` command
- Tests: `tests/test_artifact_hashing.py`, `tests/test_artifact_store.py`, `tests/test_study_schema.py`, `tests/test_investigation_reference_graph.py`, `tests/test_study_pipeline_resolve.py`, `tests/test_study_migrate.py`, `tests/test_no_nested_studies_guard.py`

Each `lib/artifacts/*` file owns one concern and is unit-testable without a running server.

---

### Task 1: Artifact hashing (pure)

**Files:**
- Create: `vivarium_workbench/lib/artifacts/hashing.py`
- Test: `tests/test_artifact_hashing.py`

**Interfaces:**
- Produces: `canonical(config: dict) -> str`; `artifact_id(*, composite_id: str, config: dict, input_ids: list[str], commit: str) -> str` (16-char hex).

- [ ] **Step 1: Write the failing test**
```python
# tests/test_artifact_hashing.py
from vivarium_workbench.lib.artifacts.hashing import canonical, artifact_id

def test_canonical_is_key_order_independent():
    assert canonical({"b": 1, "a": 2}) == canonical({"a": 2, "b": 1})

def test_artifact_id_is_stable_and_16_hex():
    kw = dict(composite_id="c", config={"seed": 0}, input_ids=["x", "y"], commit="abc")
    h = artifact_id(**kw)
    assert h == artifact_id(**kw) and len(h) == 16 and all(c in "0123456789abcdef" for c in h)

def test_input_order_does_not_matter():
    a = artifact_id(composite_id="c", config={}, input_ids=["x", "y"], commit="k")
    b = artifact_id(composite_id="c", config={}, input_ids=["y", "x"], commit="k")
    assert a == b

def test_any_input_change_changes_id():
    base = dict(composite_id="c", config={"seed": 0}, input_ids=[], commit="k")
    h = artifact_id(**base)
    assert h != artifact_id(**{**base, "config": {"seed": 1}})
    assert h != artifact_id(**{**base, "commit": "k2"})
    assert h != artifact_id(**{**base, "composite_id": "d"})
```

- [ ] **Step 2: Run test to verify it fails** — `pytest tests/test_artifact_hashing.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement**
```python
# vivarium_workbench/lib/artifacts/hashing.py
import hashlib, json

def _stable(o):
    if isinstance(o, float) and o.is_integer():
        return int(o)
    raise TypeError(type(o))

def canonical(config: dict) -> str:
    return json.dumps(config or {}, sort_keys=True, separators=(",", ":"), default=_stable)

def artifact_id(*, composite_id: str, config: dict, input_ids: list[str], commit: str) -> str:
    payload = "\n".join([composite_id, canonical(config),
                         "\n".join(sorted(input_ids or [])), commit or ""])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Run test to verify it passes** — `pytest tests/test_artifact_hashing.py -v` → PASS.

- [ ] **Step 5: Commit** — `git add vivarium_workbench/lib/artifacts/hashing.py vivarium_workbench/lib/artifacts/__init__.py tests/test_artifact_hashing.py && git commit -m "feat(artifacts): content-addressed hashing"`

---

### Task 2: Content-addressed artifact store

**Files:**
- Create: `vivarium_workbench/lib/artifacts/store.py`
- Test: `tests/test_artifact_store.py`

**Interfaces:**
- Consumes: `artifact_id` (Task 1), `WorkspacePaths`.
- Produces: `ArtifactStore(ws_root)` with `has(id)->bool`, `path(id)->Path`, `put(id, src_path, meta)->Path` (idempotent; a second put with the same id is a no-op store hit), `meta(id)->dict`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_artifact_store.py
from pathlib import Path
from vivarium_workbench.lib.artifacts.store import ArtifactStore

def test_put_get_has_and_idempotent(tmp_path):
    src = tmp_path / "sim_data.bin"; src.write_bytes(b"PARCA")
    st = ArtifactStore(tmp_path)
    assert not st.has("aaaa000000000000")
    p = st.put("aaaa000000000000", src, {"producer_study": "parca", "kind": "sim_data"})
    assert st.has("aaaa000000000000")
    assert p.read_bytes() == b"PARCA"
    assert st.meta("aaaa000000000000")["producer_study"] == "parca"
    # second put is a store hit (no overwrite, no error)
    src.write_bytes(b"DIFFERENT")
    st.put("aaaa000000000000", src, {"producer_study": "parca"})
    assert st.path("aaaa000000000000").read_bytes() == b"PARCA"

def test_store_lives_under_pbg_artifacts(tmp_path):
    st = ArtifactStore(tmp_path)
    st.put("bbbb000000000000", _mk(tmp_path, b"x"), {})
    assert (tmp_path / ".pbg" / "artifacts" / "bbbb000000000000").is_dir()
```
(`_mk` writes a temp file; add a small helper in the test.)

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement** — resolve `wp.pbg / "artifacts"` via `WorkspacePaths.load(ws_root)`. `put`: if `has(id)` return `path(id)` (store hit); else copy `src` → `<id>/artifact.bin` (or recursively for a dir), write `<id>/meta.json` atomically (use `lib/atomic_io.py`), including `created_at` passed in (never `datetime.now()` inside the hash path — timestamps are metadata only, not hashed). Support both file and directory payloads (`shutil.copytree` for dirs — sim_data caches and zarr are directories).

- [ ] **Step 4: Run to verify it passes.**

- [ ] **Step 5: Commit.**

---

### Task 3: Study-spec schema (inputs/outputs/composite/config/emitter)

**Files:**
- Modify: `vivarium_workbench/lib/study_spec.py`
- Test: `tests/test_study_schema.py`

**Interfaces:**
- Consumes: existing study loader (`load_study_detail_spec` / `load_spec`).
- Produces: a normalized `interface` on the loaded study: `{composite, config, inputs:[{artifact,from}], outputs:[str], emitter}`. Missing blocks default to `inputs=[]`, `outputs=[]` (additive, back-compat).

- [ ] **Step 1: Write the failing test** — assert a `study.yaml` with `inputs: [{artifact: sim_data, from: parca}]`, `outputs: [run_zarr]`, `composite:`, `config: {seed:0}`, `emitter: parquet` loads into a normalized `interface` dict; assert a legacy study.yaml WITHOUT those blocks loads with `inputs==[]`, `outputs==[]` and does not raise; assert validation rejects an input missing `from` with a clear `InvestigationSpecError`.

- [ ] **Step 2–4:** implement a `study_interface(spec) -> dict` normalizer + validation; wire it into the loader output; run tests to red→green.

- [ ] **Step 5: Commit.**

---

### Task 4: Investigation-as-reference + derived DAG edges

**Files:**
- Modify: `vivarium_workbench/lib/investigation_graph_views.py`
- Test: `tests/test_investigation_reference_graph.py`

**Interfaces:**
- Consumes: `investigation.yaml: members: [slug,...]`, each member's `interface.inputs` (Task 3).
- Produces: `build_investigation_graph` returns `studies` = the referenced members (loaded from `wp.studies/<slug>`), and `study_edges` = `{source: study/<from>, target: study/<slug>}` **derived** from each member's `inputs.from` (only edges where `from` is also a member).

- [ ] **Step 1: Write the failing test** — a fixture workspace with `studies/parca` (outputs sim_data) + `studies/ko` (`inputs:[{artifact:sim_data,from:parca}]`) and an `investigation.yaml: members:[parca, ko]`; assert `build_investigation_graph` yields 2 study nodes and exactly one derived edge `parca → ko`. Assert a member slug referenced by **two** investigations appears in both graphs (many-to-many).

- [ ] **Step 2–4:** implement members-based loading + `inputs.from` edge derivation (drop the legacy `pipeline_gate.prerequisites` path for edges once members exist; keep reading legacy specs without crashing). Red→green.

- [ ] **Step 5: Commit.**

---

### Task 5: Pipeline resolver (pull-or-compute)

**Files:**
- Create: `vivarium_workbench/lib/artifacts/pipeline.py`
- Test: `tests/test_study_pipeline_resolve.py`

**Interfaces:**
- Consumes: `hashing.artifact_id`, `ArtifactStore`, study `interface` (Task 3), the workspace git commit (`lib/git_status_lib` or `subprocess git rev-parse HEAD`), and a `compute_fn` seam defaulting to `run_core.invoke_run` (injected in tests, mirroring `dispatch_batch(run_workflow_fn=...)`).
- Produces: `resolve_study(ws_root, slug, *, compute_fn=None) -> dict` returning `{stage: artifact_id, cached: bool}` per stage, recursing into `inputs.from` producers first.

- [ ] **Step 1: Write the failing test** — with a STUB `compute_fn` (records calls, writes a fake artifact), assert: (a) resolving `ko` first resolves `parca` (its input) — parca computed once; (b) resolving `ko` again performs **zero** compute calls (store hit on every stage); (c) changing `ko`'s config re-runs `ko`'s stages but NOT `parca` (its `sim_data` id is unchanged); (d) the returned map records `parca`'s `sim_data` `artifact_id` and `cached: True` on the second resolve.

- [ ] **Step 2–4:** implement the recursive pull-or-compute: for each declared input, compute the producer's `sim_data` `artifact_id`; if `store.has(id)` pull it, else `resolve_study(producer)` then pull; compute this study's own stage ids from `(composite, config, resolved input ids, commit)`; skip any stage whose id is in the store; call `compute_fn` only for missing stages; `put` outputs; record `{stage: id}` into `runs.db`. Never call `datetime.now()`/RNG in the resolve path. Red→green.

- [ ] **Step 5: Commit.**

---

### Task 6: Migration tool (nested → registry)

**Files:**
- Create: `vivarium_workbench/lib/study_migrate.py`
- Modify: `vivarium_workbench/cli.py` (add `migrate-studies` subcommand, `--dry-run`)
- Test: `tests/test_study_migrate.py`

**Interfaces:**
- Produces: `migrate_studies(ws_root, *, dry_run=False) -> dict` (moved slugs, rewritten investigations, backfilled inputs, TODO markers).

- [ ] **Step 1: Write the failing test** — fixture workspace with `investigations/A/studies/parca` + `investigations/A/studies/ko` and `investigation.yaml`; assert after migration: both studies live at `studies/parca` / `studies/ko`; nothing remains under `investigations/A/studies/`; `investigations/A.yaml` (or A/investigation.yaml) has `members:[parca, ko]`; a study that consumes sim_data gets `inputs:[{artifact:sim_data,from:parca}]` backfilled; a non-inferable input leaves a `# TODO(inputs)` marker rather than a guess; **slug collision raises** (don't silently overwrite).

- [ ] **Step 2–4:** implement move + investigation rewrite + best-effort `inputs` backfill (infer `sim_data` producer from the workspace's ParCa study; otherwise TODO). `--dry-run` prints the plan without moving. Red→green.

- [ ] **Step 5: Commit.**

---

### Task 7: Guard — no study under investigations/

**Files:**
- Test: `tests/test_no_nested_studies_guard.py`

- [ ] **Step 1: Write the test** — walk `wp.investigations`; assert no `study.yaml` exists beneath it (mirrors the tracked-symlink guard). Include a clear failure message naming offenders.

- [ ] **Step 2: Run** — RED until Task 8 migrates the real workspace; that's expected (this guard is the acceptance gate).

- [ ] **Step 3: Commit** (test only; do not weaken it to pass early).

---

### Task 8: End-to-end + migrate the v2ecoli workspace

**Files:**
- Test: `tests/test_pipeline_end_to_end.py` (uses `dashboard_client` fixture workspace)
- Modify (data, in the v2ecoli repo, separate commit): the 26 nested studies

- [ ] **Step 1: Integration test** — fixture workspace with a `parca` producer + two investigations sharing it; run `resolve_study` for a member of each; assert ParCa's `sim_data` is stored once (one `artifact_id`, second resolve is a store hit) and both investigations' graphs show the shared node. Run the guard (Task 7) against the fixture → PASS.

- [ ] **Step 2: Run the migrator on v2ecoli** — `vivarium-workbench migrate-studies --workspace ~/code/v2ecoli/workspace --dry-run`, review, then apply; resolve TODO-marked inputs by hand; commit in the **v2ecoli** repo (not this one).

- [ ] **Step 3: Run the guard against v2ecoli** → PASS (no nested studies remain).

- [ ] **Step 4: Commit** the integration test here; commit the migrated workspace in v2ecoli.

---

## Self-Review

- **Spec coverage:** artifacts (T1–2), registry/reference model (T3–4), pull-or-compute pipeline (T5), migration + guard (T6–8) — all spec sections mapped. Studies-tab badge, evidence spine, remote store are correctly **absent** (deferred to Specs 2/3).
- **No placeholders:** foundational tasks carry full code; integration tasks carry concrete test assertions + precise interfaces. The only intentional TODO is the migrator's non-inferable-input marker (a spec'd behavior, not a plan gap).
- **Type consistency:** `artifact_id` is a 16-char hex str everywhere; `interface.inputs` is `[{artifact,from}]`; store keys by `artifact_id`; resolver returns `{stage: artifact_id}`.
- **Determinism review:** no `datetime.now()`/RNG/`latest_run` in the hash or resolve path; timestamps are metadata only. Store `put` is idempotent (store hit wins).
