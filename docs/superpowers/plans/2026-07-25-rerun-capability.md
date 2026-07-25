# Reproducible runs + full flush + rerun — Implementation Plan (rev 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee reproducible runs (complete per-run manifest), complete the post-run flush (real analyses + report cards on the composite path), and add rerun (investigation / study / simulation) that replays the manifest exactly + runs the full flush.

**Architecture:** Additive — a new `runs_meta.manifest_json` column stamped at both launch paths; finish the existing `composite_flush` stub; a new `lib/rerun.py` orchestrating over the run subsystem; two endpoints + three UI buttons.

**Tech Stack:** Python 3, FastAPI (`api/app.py`), pydantic (`lib/models.py`), SQLite (`runs_meta`), env-worker pool (analyses), vanilla JS + Jinja, pytest with the `dashboard_client` subprocess fixture.

## Global Constraints

- **Task 1 is DONE** (`lib/rerun.py::resolve_rerun_target`, commit `0af7983`). Build on it; don't recreate it.
- Rerun always mints a **new** `run_id` — never overwrite.
- **Reproducibility guarantee:** the manifest must capture the COMPLETE effective replay inputs — `spec_id`, FULL effective `params` (not the delta), `n_steps`, `emitter`, `emit_paths`, `runtime` block, `origin`, `study`, `pkg`, `generation_id`, best-effort `code_version`. A rerun replays FROM the manifest, not the live YAML.
- `runs_meta` schema change is additive nullable via `composite_runs._NEW_COLUMNS` only.
- Manifest/flush/version capture is **best-effort**: a failure degrades (null manifest field / logged analysis error), never breaks a run.
- Legacy runs (no manifest) still rerun via the delta `params`+`n_steps` fallback.
- `study_runs.run_study_baseline` behavior stays byte-identical after the `launch_into_study` extraction; the full 7-stage flush is preserved (viz → post-run scripts → `run_study_analyses` (report cards) → `study_outcomes.sync` → `capture_run_params` → `auto_evaluate` → investigation rollup).
- New POST routes call `_csrf_ok()` and return a pydantic model; logic in `lib/`, route in `api/app.py`.
- Rerun buttons live-only; hidden/disabled in snapshot mode.
- Tests run via the worktree interpreter: `PYTHONPATH=/Users/eranagmon/code/vwb-rerun /Users/eranagmon/code/vivarium-workbench/.venv/bin/python -m pytest …` from `/Users/eranagmon/code/vwb-rerun`.

---

### Task 2 — Run manifest infra + composite-path manifest (Part A)

**Files:**
- Modify: `vivarium_workbench/lib/composite_runs.py` (`_NEW_COLUMNS`, `save_metadata`)
- Modify: `vivarium_workbench/lib/composite_test_run_views.py` (build + pass the composite manifest)
- Modify: `vivarium_workbench/lib/rerun.py` (`resolve_rerun_target` prefers manifest)
- Test: `tests/test_run_manifest.py`, extend `tests/test_rerun_resolve.py`

**Interfaces:**
- Produces: `runs_meta.manifest_json` column; `save_metadata(..., manifest: dict | None = None)` writes it; `build_run_manifest(...)` helper (in `composite_runs.py`) that assembles the canonical manifest dict; `resolve_rerun_target` returns manifest fields (`emitter`, `emit_paths`, `runtime`) when a manifest exists, else the delta fallback.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_run_manifest.py
import json
from vivarium_workbench.lib import composite_runs as cr

def test_migration_adds_manifest_column(tmp_path):
    conn = cr.connect(tmp_path / "runs.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs_meta)")}
    assert "manifest_json" in cols

def test_save_metadata_writes_manifest(tmp_path):
    conn = cr.connect(tmp_path / "runs.db")
    manifest = {"version": 1, "spec_id": "s", "params": {"seed": 0, "cache_dir": "out/cache"},
                "n_steps": 100, "emitter": "parquet", "emit_paths": ["bulk"],
                "runtime": {"emitter": "parquet"}, "origin": "study", "study": "s1"}
    cr.save_metadata(conn, spec_id="s", run_id="r1", params={"seed": 0}, label="b",
                     started_at=0.0, n_steps=100, manifest=manifest)
    row = conn.execute("SELECT manifest_json FROM runs_meta WHERE run_id='r1'").fetchone()
    assert json.loads(row[0])["emitter"] == "parquet"
    assert json.loads(row[0])["params"]["cache_dir"] == "out/cache"

def test_build_run_manifest_shape():
    m = cr.build_run_manifest(spec_id="s", params={"seed": 0}, n_steps=100,
                              emitter="parquet", emit_paths=["bulk"], runtime={"x": 1},
                              origin="study", study="s1", pkg="v2ecoli", generation_id=None)
    for k in ("version", "spec_id", "params", "n_steps", "emitter", "emit_paths",
              "runtime", "origin", "study", "pkg", "code_version"):
        assert k in m
```
Extend `tests/test_rerun_resolve.py`: seed a row with a full `manifest_json` → `resolve_rerun_target` returns `emitter`/`emit_paths`/`runtime` from the manifest; a row with only `params_json`+`n_steps` (no manifest) → falls back (those keys absent/None).

- [ ] **Step 2: Run — verify fail.** `… -m pytest tests/test_run_manifest.py -v` → FAIL.

- [ ] **Step 3: Implement**

`composite_runs.py`:
- Add `"manifest_json": "TEXT",` to `_NEW_COLUMNS`.
- Add `build_run_manifest(*, spec_id, params, n_steps, emitter, emit_paths, runtime, origin, study=None, pkg=None, generation_id=None, ws_root=None) -> dict` — assembles the canonical dict (§ spec Part A), including best-effort `code_version = {"git_sha": <git HEAD of ws_root>, "package": <pkg version>}` (wrap git/version lookups in try/except → null).
- `save_metadata(..., manifest=None)` — add the kwarg; extend the INSERT to include a `manifest_json` column with `json.dumps(manifest) if manifest else None`.

`composite_test_run_views.py` — where it builds `request.json` / calls `save_metadata`: build the manifest via `build_run_manifest(origin="composite", spec_id=…, params=<full overrides>, n_steps=…, emitter=…, emit_paths=…, runtime={})` and pass `manifest=` to `save_metadata`.

`rerun.py::resolve_rerun_target` — if `row.get("manifest_json")`, parse it and return `{..., spec_id, params: manifest["params"], n_steps, emitter, emit_paths, runtime, origin (from manifest), study}`; else the existing delta path (add `emitter=None, emit_paths=None, runtime=None` to the returned dict for a uniform shape).

- [ ] **Step 4: Run — verify pass.** `… -m pytest tests/test_run_manifest.py tests/test_rerun_resolve.py -v` → PASS.

- [ ] **Step 5: Commit.** `git add … && git commit -m "feat: runs_meta.manifest_json + build_run_manifest + composite-path manifest"`

---

### Task 3 — `launch_into_study` (factor tail + stamp study manifest) (Part C-refactor + A)

**Files:**
- Modify: `vivarium_workbench/lib/study_runs.py` (`run_study_baseline`)
- Test: `tests/test_launch_into_study.py`

**Interfaces:**
- Produces: `launch_into_study(ws_root, study, spec_id, params, n_steps, *, emitter=None, emit_paths=None, runtime=None, label=None) -> (resp, status)` — the run-launch + FULL 7-stage flush tail of `run_study_baseline`, taking EXPLICIT replay inputs, building+stamping the run's manifest (Task 2) into `studies/<study>/runs.db`.

- [ ] **Step 1: Write failing test**

```python
# tests/test_launch_into_study.py
from vivarium_workbench.lib import study_runs

def test_launch_into_study_explicit_inputs_and_manifest(tmp_path, monkeypatch):
    seen = {}
    def fake_invoke_run(ws_root, *, spec_id, config, db_path, label, n_steps):
        seen.update(spec_id=spec_id, config=config, db_path=db_path, n_steps=n_steps)
        class P: pass
        return P()
    monkeypatch.setattr(study_runs.run_core, "invoke_run", fake_invoke_run)
    # stub the subprocess + post-run tail so the test is hermetic; capture the manifest passed to save_metadata
    manifests = []
    monkeypatch.setattr(study_runs, "_launch_run_and_flush",
        lambda *a, **k: (manifests.append(k.get("manifest")) or ({"run_id": "r-new", "status": "running"}, 200)),
        raising=False)
    resp, status = study_runs.launch_into_study(
        tmp_path, "s1", "some.composite", {"seed": 3}, 50,
        emitter="parquet", emit_paths=["bulk"], runtime={"emitter": "parquet"})
    assert "studies/s1/runs.db" in seen["db_path"].replace("\\", "/")
    assert seen["spec_id"] == "some.composite" and seen["config"].get("seed") == 3
    assert status == 200 and resp["run_id"]
    # manifest carries the explicit replay inputs
    m = manifests[-1]; assert m and m["emitter"] == "parquet" and m["emit_paths"] == ["bulk"]
```
(The exact stub seam depends on the extraction; the implementer adjusts monkeypatch targets to the real factored internals. The assertions that matter: explicit spec_id/params + the study `runs.db` path + a manifest carrying emitter/emit_paths/runtime.)

- [ ] **Step 2: Run — verify fail.** → FAIL (`launch_into_study` undefined).

- [ ] **Step 3: Implement the extraction**

Read `run_study_baseline` in full. Extract from the `full_params`/`db_file`/`label` computation (study_runs.py ~L120) through the end — including `run_core.invoke_run`, the remote-build guard, the detached spawn, AND all 7 post-run stages (`render_study_visualizations`, `run_post_run_scripts`, `run_study_analyses`, `study_outcomes.sync`, `capture_run_params`/`write_run_params`, `auto_evaluate.evaluate_on_run_completion`, `_sync_parent_investigation`) — into `launch_into_study(ws_root, study, spec_id, params, n_steps, *, emitter=None, emit_paths=None, runtime=None, label=None)`. Inside it:
- resolve `study_dir` + `db_file = study_dir/runs.db`; `full_params = {**params, "n_steps": n_steps}`.
- build the manifest via `composite_runs.build_run_manifest(origin="study", study=study, spec_id=spec_id, params=full_params, n_steps=n_steps, emitter=emitter, emit_paths=emit_paths, runtime=runtime, pkg=…, ws_root=ws_root)` and thread it to the `save_metadata` call in the subprocess launch (via the existing `composite_subprocess` path — pass `manifest` through, OR stamp it onto the row right after save).
- keep the 7 stages verbatim.

Rewrite `run_study_baseline`: after it resolves `spec_id`, `generator_overrides`, `params_n_steps`, `emitter` (L176), `emit_paths` (L173), and the `runtime` block (L169-178) from `study.yaml`, delegate:
```python
    return launch_into_study(ws_root, name, spec_id, generator_overrides, params_n_steps,
                             emitter=emitter, emit_paths=emit_paths, runtime=runtime_block,
                             label=entry.get("name") or "baseline")
```
Do the same delegation for `run_study_variant` if it duplicates the tail (keep its variant-specific resolution, delegate the launch+flush).

- [ ] **Step 4: Run — verify + no regression.** `… -m pytest tests/test_launch_into_study.py tests/test_study_runs.py -v` (+ any study-run-baseline endpoint test) → PASS. Manually confirm all 7 stage calls remain in `launch_into_study`.

- [ ] **Step 5: Commit.** `git commit -m "refactor: launch_into_study (explicit inputs + manifest + full 7-stage flush)"`

---

### Task 4 — Complete the composite-path flush (Part B)

**Files:**
- Modify: `vivarium_workbench/lib/composite_flush.py` (`_dispatch_analyses` / `run_flush`)
- Test: `tests/test_composite_flush.py`

**Interfaces:**
- Consumes: the env-worker analysis dispatch used by `study_run_post.run_study_analyses` (line 183).
- Produces: `run_flush` renders REAL analyses + a report card for a composite that declares analyses; graceful no-op (thin report) when it declares none.

- [ ] **Step 1: Write failing test**

```python
# tests/test_composite_flush.py
from vivarium_workbench.lib import composite_flush

def test_flush_renders_declared_analyses(tmp_path, monkeypatch):
    # a composite that declares one analysis → _dispatch_analyses RENDERS it (not just records)
    rendered = {}
    monkeypatch.setattr(composite_flush, "_render_analysis",
        lambda **k: rendered.setdefault("called", True) or {"name": k.get("name"), "artifact": "a.json"},
        raising=False)
    monkeypatch.setattr(composite_flush, "_composite_analyses",
        lambda spec_id, core: [{"name": "mass_over_time"}], raising=False)
    out = composite_flush._dispatch_analyses(spec_id="c", db_file=str(tmp_path/"x.db"),
                                             run_id="r1", core=object())
    assert rendered.get("called") and out and out[0]["name"] == "mass_over_time"

def test_flush_no_analyses_is_graceful(tmp_path, monkeypatch):
    monkeypatch.setattr(composite_flush, "_composite_analyses", lambda spec_id, core: [], raising=False)
    out = composite_flush._dispatch_analyses(spec_id="c", db_file=str(tmp_path/"x.db"),
                                             run_id="r1", core=object())
    assert out == []
```
(Adjust the monkeypatch seams to the real factored internals — the point: a declared analysis is RENDERED to an artifact, an analysis-less composite is a no-op.)

- [ ] **Step 2: Run — verify fail.** → FAIL.

- [ ] **Step 3: Implement**

In `composite_flush.py`, replace the "records declarations" body of `_dispatch_analyses` (the NOTE at ~L32-34) so each declared analysis is actually rendered over the run's emitter output — reuse `study_run_post.run_study_analyses`'s env-worker dispatch (factor a shared `render_analysis(...)` if needed, or call the same env-worker `analysis` capability). `run_flush` then writes the real `analyses.json` (artifact list) + a report card (`render_report_card`) with the rendered results. Wrap each analysis render in try/except → log + skip (best-effort; one bad analysis doesn't fail the flush). Keep the analysis-less path a thin no-op.

- [ ] **Step 4: Run — verify pass.** `… -m pytest tests/test_composite_flush.py -v` → PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat: composite flush renders real analyses + report card (finish stub)"`

---

### Task 5 — `run_rerun` (manifest replay) + `rerun_investigation` (Part C)

**Files:**
- Modify: `vivarium_workbench/lib/rerun.py`
- Test: `tests/test_rerun_run.py`

**Interfaces:**
- Consumes: `resolve_rerun_target` (manifest-preferred, Task 2); `study_runs.launch_into_study` (Task 3); `cli_runs.run_composite`; the investigation reader.
- Produces: `run_rerun(ws_root, run_id) -> (resp, status)`; `rerun_investigation(ws_root, investigation) -> (resp, status)`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_rerun_run.py
from vivarium_workbench.lib import rerun

def test_run_rerun_study_forwards_full_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "resolve_rerun_target", lambda ws, rid: {
        "run_id": rid, "origin": "study", "study": "s1", "spec_id": "c",
        "params": {"seed": 2, "cache_dir": "out/cache"}, "n_steps": 80,
        "emitter": "parquet", "emit_paths": ["bulk"], "runtime": {"emitter": "parquet"}})
    seen = {}
    monkeypatch.setattr(rerun.study_runs, "launch_into_study",
        lambda ws, study, spec_id, params, n_steps, **k: seen.update(
            study=study, spec_id=spec_id, params=params, n_steps=n_steps, kw=k)
            or ({"run_id": "r2", "status": "running"}, 200))
    resp, status = rerun.run_rerun(tmp_path, "r1")
    assert resp["run_id"] == "r2" and resp["origin"] == "study" and resp["reran"] == "r1"
    assert seen["spec_id"] == "c" and seen["params"]["cache_dir"] == "out/cache"
    assert seen["kw"]["emitter"] == "parquet" and seen["kw"]["emit_paths"] == ["bulk"]
    assert seen["kw"]["runtime"] == {"emitter": "parquet"}

def test_run_rerun_composite(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "resolve_rerun_target", lambda ws, rid: {
        "run_id": rid, "origin": "composite", "study": None, "spec_id": "c.comp",
        "params": {"x": 1}, "n_steps": 5, "emitter": None, "emit_paths": ["bulk"], "runtime": None})
    seen = {}
    monkeypatch.setattr(rerun.cli_runs, "run_composite",
        lambda ws, spec_id, *, steps, params, emit_paths, detach: seen.update(
            spec_id=spec_id, params=params, emit_paths=emit_paths, detach=detach)
            or ({"run_id": "r3", "status": "running"}, 202))
    resp, status = rerun.run_rerun(tmp_path, "r1")
    assert resp["run_id"] == "r3" and seen["detach"] is True and seen["emit_paths"] == ["bulk"]

def test_run_rerun_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "resolve_rerun_target", lambda ws, rid: None)
    assert rerun.run_rerun(tmp_path, "x")[1] == 404

def test_rerun_investigation(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "_investigation_studies", lambda ws, inv: ["s1", "s2"])
    launched = []
    monkeypatch.setattr(rerun.study_runs, "run_study_baseline",
        lambda ws, body: launched.append(body["study"]) or ({"run_id": "r-"+body["study"], "status": "running"}, 200))
    resp, _ = rerun.rerun_investigation(tmp_path, "inv1")
    assert launched == ["s1", "s2"] and resp["count"] == 2
```

- [ ] **Step 2: Run — verify fail.** → FAIL.

- [ ] **Step 3: Implement** (`rerun.py`)

```python
from vivarium_workbench.lib import study_runs

def run_rerun(ws_root, run_id):
    t = resolve_rerun_target(ws_root, run_id)
    if t is None:
        return {"error": f"run not found: {run_id}"}, 404
    if t["origin"] == "study":
        resp, status = study_runs.launch_into_study(
            ws_root, t["study"], t["spec_id"], t["params"], t["n_steps"],
            emitter=t.get("emitter"), emit_paths=t.get("emit_paths"), runtime=t.get("runtime"))
    else:
        resp, status = cli_runs.run_composite(
            ws_root, t["spec_id"], steps=t["n_steps"], params=t["params"],
            emit_paths=t.get("emit_paths") or [], detach=True)
    if isinstance(resp, dict):
        resp = {**resp, "origin": t["origin"], "reran": run_id}
    return resp, status

def _investigation_studies(ws_root, investigation):
    from vivarium_workbench.lib import investigations as inv
    spec = inv.load_investigation(ws_root, investigation)   # confirm the real reader name
    return list(spec.get("studies") or [])

def rerun_investigation(ws_root, investigation):
    studies = _investigation_studies(ws_root, investigation)
    launched, errors = [], []
    for s in studies:
        try:
            resp, status = study_runs.run_study_baseline(ws_root, {"study": s})
            (launched if status < 300 and (resp or {}).get("run_id") else errors).append(
                {"study": s, "run_id": (resp or {}).get("run_id")} if status < 300
                else {"study": s, "error": (resp or {}).get("error", status)})
        except Exception as e:  # noqa: BLE001 — one bad study must not abort the batch
            errors.append({"study": s, "error": str(e)})
    return {"investigation": investigation, "launched": launched, "errors": errors,
            "count": len(launched)}, 200
```
(Confirm the real investigation reader name — `investigations.load_investigation` / `scaffold_mutations` — and adjust `_investigation_studies`.)

- [ ] **Step 4: Run — verify pass.** `… -m pytest tests/test_rerun_run.py -v` → PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat: run_rerun (manifest replay) + rerun_investigation"`

---

### Task 6 — Endpoints `/api/run-rerun` + `/api/investigation-rerun`

**Files:**
- Modify: `vivarium_workbench/lib/models.py` (`RerunResult`, `InvestigationRerunResult`)
- Modify: `vivarium_workbench/api/app.py` (two POST routes + CSRF list)
- Test: `tests/test_api_rerun.py`

- [ ] **Step 1: Write failing test** — (as in rev-1 plan Task 4) `POST /api/run-rerun` unknown run → 404/error body; `POST /api/investigation-rerun` → `{launched, errors, count}`; both CSRF-guarded (present cross-origin Origin → 403/400). Use the real `dashboard_client` factory (see `tests/test_api_analysis_tools.py`).

- [ ] **Step 2: Run — verify fail** (404 routes).

- [ ] **Step 3: Implement** — models `RerunResult`/`InvestigationRerunResult` (extra="allow"); routes mirroring `study-run-baseline`'s mutating-route form (`_csrf_ok(request)`, `Depends(get_workspace)`, `JSONResponse(status_code=status, content=resp)`); add both paths to the CSRF-required route list (app.py ~L445).

- [ ] **Step 4: Run — verify pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat: POST /api/run-rerun + /api/investigation-rerun"`

---

### Task 7 — UI: three Rerun buttons

**Files:**
- Modify: `templates/index.html.j2` (investigation header), `static/walkthrough.js`, `static/sim-table.js`, `templates/study-detail.html`, `static/study-detail.js`
- Test: `tests/test_rerun_ui.py`

- [ ] **Step 1: Write failing test** — served `/` HTML has `id="investigation-rerun"`; `/sim-table.js` contains `run-rerun` + `Rerun`.

- [ ] **Step 2: Run — verify fail.**

- [ ] **Step 3: Implement**
- Investigation header `.inv-export-actions` (index.html.j2 ~L906): `<button id="investigation-rerun" class="btn-mini">Rerun investigation</button>`; handler in `walkthrough.js` (near `_runUnblockedSimulations` ~L6188): confirm → `POST /api/investigation-rerun {investigation}` → toast (`<count> launched`) + reuse `#investigation-run-progress`. Snapshot-hidden.
- Sim row `_actions(row)` (sim-table.js L116, td at L151): `↻ Rerun` one-click → `POST /api/run-rerun {run_id: row.run_id}` → toast + `renderTable` refresh. Snapshot-hidden.
- Study-detail header (study-detail.html + study-detail.js): "Rerun study" → confirm → `POST /api/study-run-baseline {study}` → toast. Live-only.

- [ ] **Step 4: Run — verify + JS parse.** `… -m pytest tests/test_rerun_ui.py -v` + `node --check` on the three JS files → PASS + OK.

- [ ] **Step 5: Commit.** `git commit -m "feat: Rerun buttons — investigation / study / sim-table"`

---

## Self-Review

**Spec coverage:** A (manifest) → Task 2 (infra + composite) + Task 3 (study manifest via launch_into_study); B (flush) → Task 4; C (rerun) → Task 1 (done, resolve) + Task 3 (launch_into_study) + Task 5 (run_rerun/investigation) + Task 6 (endpoints) + Task 7 (UI). Reproducibility guarantee → Task 2 manifest completeness + Task 5 forwards emitter/emit_paths/runtime verbatim (asserted). Full flush preserved → Task 3 keeps 7 stages; composite flush completed → Task 4. ✔

**Placeholder scan:** No TBD/TODO. Three "confirm the real name/seam" notes (investigation reader; the `launch_into_study` post-invoke internals; the composite-flush render seam) name the exact target to verify.

**Type consistency:** `build_run_manifest(...)`/`save_metadata(manifest=)` (Task 2) → `resolve_rerun_target` returns `{spec_id,params,n_steps,emitter,emit_paths,runtime,origin,study}` (Task 2) → `run_rerun` forwards them to `launch_into_study(..., emitter=, emit_paths=, runtime=)` (Task 3 signature) / `run_composite(..., emit_paths=)` (Task 5). Endpoint bodies `{run_id}` / `{investigation}` (Task 6) ↔ UI (Task 7).
