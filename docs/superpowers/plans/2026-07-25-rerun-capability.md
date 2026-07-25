# Rerun capability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rerun an investigation, a study, or a single simulation from the workbench — replaying recorded/declared inputs as a new run.

**Architecture:** A new `lib/rerun.py` orchestrates over the existing run subsystem: `run_rerun` replays a recorded sim's exact `spec_id`+`params` into its **origin DB** (study `runs.db` via a factored `study_runs.launch_into_study`, else `composite-runs.db`); `rerun_investigation` re-launches every study's declared baseline. Two POST endpoints + three UI buttons.

**Tech Stack:** Python 3, FastAPI (`api/app.py`), pydantic (`lib/models.py`), SQLite (`runs_meta`), vanilla JS (`static/*.js`) + Jinja (`templates/*`), pytest with the `dashboard_client` subprocess fixture.

## Global Constraints

- Rerun always mints a **new** `run_id` — never overwrite.
- **Sim rerun uses the run's EXACT recorded `spec_id`+`params`** (from `find_run`'s row), NOT the current `study.yaml`.
- **Origin routing** is derived from `find_run`'s returned `db_file`: a study's `runs.db` (parent dir is a study under `WorkspacePaths.studies`) → study origin (slug = parent dir name); `.pbg/composite-runs.db` → composite origin.
- All reruns are **detached** (never block the request); investigation rerun respects `run_registry.CONCURRENCY_CAP` (excess queue).
- New mutating routes (`POST`) MUST call `_csrf_ok()` and return a pydantic model; put logic in `lib/`, route in `api/app.py`.
- `study_runs.run_study_baseline` behavior must stay **byte-identical** after the `launch_into_study` extraction (existing tests green).
- Rerun buttons are live-only; hidden/disabled in snapshot mode (mirror existing run buttons).
- Tests: `pytest`; endpoint/UI tests use the `dashboard_client` fixture against `tests/_fixtures/`.

---

### Task 1: `resolve_rerun_target` — find a run + classify its origin

**Files:**
- Create: `vivarium_workbench/lib/rerun.py`
- Test: `tests/test_rerun_resolve.py`

**Interfaces:**
- Consumes: `cli_runs.find_run(ws_root, run_id) -> (db_file, row)`; `row` has `spec_id`, `params` (dict), `n_steps`. `workspace_paths.WorkspacePaths`.
- Produces: `resolve_rerun_target(ws_root, run_id) -> dict | None` = `{run_id, origin: "study"|"composite", study: str|None, spec_id, params: dict, n_steps: int}` (None if not found).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rerun_resolve.py
from pathlib import Path
from vivarium_workbench.lib import rerun, composite_runs as cr

def _seed(db_path, run_id, spec_id, params, n_steps, status="completed"):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = cr.connect(db_path)
    import json
    conn.execute("INSERT INTO runs_meta (run_id, spec_id, params_json, started_at, status, n_steps) "
                 "VALUES (?,?,?,?,?,?)", (run_id, spec_id, json.dumps(params), 0.0, status, n_steps))
    conn.commit(); conn.close()

def test_study_origin(tmp_path):
    # a run in studies/<slug>/runs.db → origin study, slug from dir
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    db = tmp_path / "workspace" / "studies" / "s1" / "runs.db"
    _seed(db, "spec__1__a", "v2ecoli.composites.baseline.baseline", {"seed": 0}, 100)
    t = rerun.resolve_rerun_target(tmp_path, "spec__1__a")
    assert t["origin"] == "study" and t["study"] == "s1"
    assert t["spec_id"] == "v2ecoli.composites.baseline.baseline"
    assert t["params"] == {"seed": 0} and t["n_steps"] == 100

def test_composite_origin(tmp_path):
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    db = tmp_path / ".pbg" / "composite-runs.db"
    _seed(db, "spec__2__b", "some.composite", {"x": 1}, 5)
    t = rerun.resolve_rerun_target(tmp_path, "spec__2__b")
    assert t["origin"] == "composite" and t["study"] is None

def test_not_found(tmp_path):
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    assert rerun.resolve_rerun_target(tmp_path, "nope") is None
```

- [ ] **Step 2: Run — verify it fails**

Run: `python -m pytest tests/test_rerun_resolve.py -v`  Expected: FAIL (module/func undefined).

- [ ] **Step 3: Implement**

```python
# vivarium_workbench/lib/rerun.py
"""Rerun a recorded/declared run at investigation / study / simulation level.
Thin orchestration over the run subsystem; never overwrites — always a new run."""
from __future__ import annotations

from pathlib import Path

from vivarium_workbench.lib import cli_runs
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def resolve_rerun_target(ws_root, run_id):
    db_file, row = cli_runs.find_run(ws_root, run_id)
    if row is None:
        return None
    dbp = Path(db_file)
    wp = WorkspacePaths.load(Path(ws_root))
    studies_root = Path(wp.studies).resolve()
    origin, study = "composite", None
    # study runs.db lives at <studies_root>/<slug>/runs.db
    if dbp.name == "runs.db" and dbp.parent.parent.resolve() == studies_root:
        origin, study = "study", dbp.parent.name
    return {
        "run_id": run_id, "origin": origin, "study": study,
        "spec_id": row.get("spec_id"),
        "params": dict(row.get("params") or {}),
        "n_steps": int(row.get("n_steps") or 5),
    }
```

- [ ] **Step 4: Run — verify it passes**

Run: `python -m pytest tests/test_rerun_resolve.py -v`  Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/rerun.py tests/test_rerun_resolve.py
git commit -m "feat: resolve_rerun_target — find a run + classify origin"
```

---

### Task 2: Factor `study_runs.launch_into_study`

**Files:**
- Modify: `vivarium_workbench/lib/study_runs.py` (`run_study_baseline`)
- Test: `tests/test_launch_into_study.py`

**Interfaces:**
- Produces: `launch_into_study(ws_root, study, spec_id, params, n_steps, *, label=None) -> (resp, status)` — mints a run_id, runs `spec_id` with `params` (config) into `studies/<study>/runs.db`, runs the study post-run stages, returns `{run_id, ...}, status`. This is the run-launch + post-run **tail** of `run_study_baseline`, taking explicit `spec_id`/`params` instead of resolving them from `study.yaml`.
- Consumes (unchanged): `run_core.invoke_run`, the existing post-run pipeline in `run_study_baseline`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_launch_into_study.py
from vivarium_workbench.lib import study_runs

def test_launch_into_study_uses_explicit_spec_and_study_db(tmp_path, monkeypatch):
    calls = {}
    class _Plan: pass
    def fake_invoke_run(ws_root, *, spec_id, config, db_path, label, n_steps):
        calls.update(spec_id=spec_id, config=config, db_path=db_path, n_steps=n_steps)
        return _Plan()
    monkeypatch.setattr(study_runs.run_core, "invoke_run", fake_invoke_run)
    # stub the post-run tail so the test stays hermetic (no subprocess)
    monkeypatch.setattr(study_runs, "_launch_and_stage", lambda *a, **k: ({"run_id": "r-new", "status": "running"}, 200), raising=False)
    resp, status = study_runs.launch_into_study(
        tmp_path, "s1", "some.composite", {"seed": 3}, 50)
    # db_path points at the study's runs.db; explicit spec+params used
    assert "studies/s1/runs.db" in calls["db_path"].replace("\\", "/")
    assert calls["spec_id"] == "some.composite"
    assert calls["config"].get("seed") == 3 and calls["config"].get("n_steps") == 50
    assert status == 200 and resp["run_id"]
```

(The exact stub seam depends on the extraction; the implementer adjusts the monkeypatch to whatever the post-invoke tail becomes — the assertion that matters is: explicit spec_id/params + the study's runs.db path.)

- [ ] **Step 2: Run — verify it fails**

Run: `python -m pytest tests/test_launch_into_study.py -v`  Expected: FAIL (`launch_into_study` undefined).

- [ ] **Step 3: Implement the extraction**

Read `run_study_baseline` in full. Extract everything from the `full_params`/`db_file`/`label` computation through the end of the function (the `run_core.invoke_run` call, the remote-build guard, the detached spawn, and the post-run stages — viz, post_run_scripts, analyses, `study_outcomes.sync`, `run_params.capture_run_params`, auto-evaluate) into:

```python
def launch_into_study(ws_root, study, spec_id, params, n_steps, *, label=None):
    """Launch spec_id+params into studies/<study>/runs.db (+ post-run stages).
    The run-launch tail of run_study_baseline, with EXPLICIT spec_id/params."""
    study_dir = _resolve_study_dir(ws_root, study)
    db_file = str(study_dir / "runs.db")
    full_params = dict(params or {})
    if n_steps is not None:
        full_params["n_steps"] = n_steps
    label = label or "baseline"
    # ... (the invoke_run + guard + spawn + post-run pipeline, verbatim) ...
    return resp, status
```

Then rewrite `run_study_baseline` so that after it resolves `spec_id`, `generator_overrides` (params), and `params_n_steps` from `study.yaml`, it delegates:
```python
    return launch_into_study(ws_root, name, spec_id, generator_overrides,
                             params_n_steps, label=entry.get("name") or "baseline")
```
Keep `run_study_baseline`'s early validation/resolution (study lookup, migration, baseline entry, remote-build guard placement) behaviorally identical.

- [ ] **Step 4: Run — verify launch_into_study test + no regression**

Run: `python -m pytest tests/test_launch_into_study.py tests/test_study_runs.py -v` (and any `study-run-baseline` endpoint test). Expected: PASS — the extraction preserves `run_study_baseline` behavior.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/study_runs.py tests/test_launch_into_study.py
git commit -m "refactor: extract study_runs.launch_into_study from run_study_baseline"
```

---

### Task 3: `run_rerun` + `rerun_investigation`

**Files:**
- Modify: `vivarium_workbench/lib/rerun.py`
- Test: `tests/test_rerun_run.py`

**Interfaces:**
- Consumes: `resolve_rerun_target` (Task 1); `study_runs.launch_into_study` (Task 2); `cli_runs.run_composite(ws_root, spec_id, *, steps, params, emit_paths, detach)`; `investigations`/scaffold to read an investigation's `studies`.
- Produces:
  - `run_rerun(ws_root, run_id) -> (resp, status)` — study origin → `launch_into_study`; composite origin → `run_composite(detach=True)`; 404 if not found.
  - `rerun_investigation(ws_root, investigation) -> (resp, status)` — for each study in the investigation, `study_runs.run_study_baseline(ws_root, {"study": s})`; aggregate.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rerun_run.py
from vivarium_workbench.lib import rerun

def test_run_rerun_study_origin_routes_to_launch_into_study(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "resolve_rerun_target", lambda ws, rid: {
        "run_id": rid, "origin": "study", "study": "s1",
        "spec_id": "some.composite", "params": {"seed": 2}, "n_steps": 80})
    seen = {}
    monkeypatch.setattr(rerun.study_runs, "launch_into_study",
        lambda ws, study, spec_id, params, n_steps, **k: seen.update(
            study=study, spec_id=spec_id, params=params, n_steps=n_steps) or ({"run_id": "r2", "status": "running"}, 200))
    resp, status = rerun.run_rerun(tmp_path, "r1")
    assert status == 200 and resp["run_id"] == "r2" and resp["origin"] == "study"
    assert seen == {"study": "s1", "spec_id": "some.composite", "params": {"seed": 2}, "n_steps": 80}

def test_run_rerun_composite_origin_routes_to_run_composite(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "resolve_rerun_target", lambda ws, rid: {
        "run_id": rid, "origin": "composite", "study": None,
        "spec_id": "c.comp", "params": {"x": 1}, "n_steps": 5})
    seen = {}
    monkeypatch.setattr(rerun.cli_runs, "run_composite",
        lambda ws, spec_id, *, steps, params, emit_paths, detach: seen.update(
            spec_id=spec_id, steps=steps, params=params, detach=detach) or ({"run_id": "r3", "status": "running"}, 202))
    resp, status = rerun.run_rerun(tmp_path, "r1")
    assert resp["run_id"] == "r3" and seen["detach"] is True and seen["spec_id"] == "c.comp"

def test_run_rerun_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "resolve_rerun_target", lambda ws, rid: None)
    _resp, status = rerun.run_rerun(tmp_path, "nope")
    assert status == 404

def test_rerun_investigation_launches_each_study(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "_investigation_studies", lambda ws, inv: ["s1", "s2"])
    launched = []
    monkeypatch.setattr(rerun.study_runs, "run_study_baseline",
        lambda ws, body: launched.append(body["study"]) or ({"run_id": "r-" + body["study"], "status": "running"}, 200))
    resp, status = rerun.rerun_investigation(tmp_path, "inv1")
    assert launched == ["s1", "s2"]
    assert {x["study"] for x in resp["launched"]} == {"s1", "s2"} and resp["count"] == 2
```

- [ ] **Step 2: Run — verify it fails**

Run: `python -m pytest tests/test_rerun_run.py -v`  Expected: FAIL.

- [ ] **Step 3: Implement**

```python
# add to vivarium_workbench/lib/rerun.py
from vivarium_workbench.lib import study_runs


def run_rerun(ws_root, run_id):
    target = resolve_rerun_target(ws_root, run_id)
    if target is None:
        return {"error": f"run not found: {run_id}"}, 404
    if target["origin"] == "study":
        resp, status = study_runs.launch_into_study(
            ws_root, target["study"], target["spec_id"], target["params"], target["n_steps"])
    else:
        resp, status = cli_runs.run_composite(
            ws_root, target["spec_id"], steps=target["n_steps"],
            params=target["params"], emit_paths=[], detach=True)
    if isinstance(resp, dict):
        resp = {**resp, "origin": target["origin"], "reran": run_id}
    return resp, status


def _investigation_studies(ws_root, investigation):
    """The study slugs an investigation declares (investigation.yaml `studies:`)."""
    from vivarium_workbench.lib import investigations as inv
    spec = inv.load_investigation(Path(ws_root), investigation)  # confirm the real reader name
    return list(spec.get("studies") or [])


def rerun_investigation(ws_root, investigation):
    studies = _investigation_studies(ws_root, investigation)
    launched, errors = [], []
    for s in studies:
        try:
            resp, status = study_runs.run_study_baseline(ws_root, {"study": s})
            if status < 300 and isinstance(resp, dict) and resp.get("run_id"):
                launched.append({"study": s, "run_id": resp["run_id"]})
            else:
                errors.append({"study": s, "error": (resp or {}).get("error", status)})
        except Exception as e:  # noqa: BLE001 — one bad study must not abort the batch
            errors.append({"study": s, "error": str(e)})
    return {"investigation": investigation, "launched": launched,
            "errors": errors, "count": len(launched)}, 200
```

(Confirm the real investigation reader — `investigations.load_investigation` / `scaffold_mutations` — and adjust `_investigation_studies`.)

- [ ] **Step 4: Run — verify it passes**

Run: `python -m pytest tests/test_rerun_run.py -v`  Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/rerun.py tests/test_rerun_run.py
git commit -m "feat: run_rerun (origin routing) + rerun_investigation"
```

---

### Task 4: Endpoints `/api/run-rerun` + `/api/investigation-rerun`

**Files:**
- Modify: `vivarium_workbench/lib/models.py` (`RerunResult`, `InvestigationRerunResult`)
- Modify: `vivarium_workbench/api/app.py` (two POST routes)
- Test: `tests/test_api_rerun.py`

**Interfaces:**
- Consumes: `rerun.run_rerun`, `rerun.rerun_investigation`; `_root.get()` / `get_workspace`; `_csrf_ok()`.
- Produces: `POST /api/run-rerun {run_id}` → `RerunResult`; `POST /api/investigation-rerun {investigation}` → `InvestigationRerunResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_rerun.py
def test_run_rerun_404_for_unknown(dashboard_client):
    c = dashboard_client(workspace=None)  # adapt to the real fixture factory
    r = c.post("/api/run-rerun", json={"run_id": "does-not-exist"})
    assert r.status_code in (404, 200)  # 404 body {"error": ...}
    if r.status_code == 200:
        assert "error" in r.json() or "run_id" in r.json()

def test_investigation_rerun_shape(dashboard_client):
    c = dashboard_client(workspace=None)
    r = c.post("/api/investigation-rerun", json={"investigation": "nonexistent"})
    assert r.status_code == 200
    body = r.json()
    assert "launched" in body and "errors" in body and "count" in body

def test_rerun_routes_csrf_guarded(dashboard_client):
    # a present cross-origin Origin must be rejected (mirrors other mutating routes)
    c = dashboard_client(workspace=None)
    r = c.post("/api/run-rerun", json={"run_id": "x"}, headers={"Origin": "http://evil.example"})
    assert r.status_code in (403, 400)
```

(Adapt `dashboard_client` usage to the real factory fixture — see `tests/test_api_analysis_tools.py` for the pattern; use a fixture workspace with at least one recorded run for a positive-path assertion if feasible.)

- [ ] **Step 2: Run — verify it fails**

Run: `python -m pytest tests/test_api_rerun.py -v`  Expected: FAIL (404 routes).

- [ ] **Step 3: Implement**

Models (`models.py`):
```python
class RerunResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    run_id: Optional[str] = None
    origin: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None

class InvestigationRerunResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    investigation: Optional[str] = None
    launched: list[dict] = []
    errors: list[dict] = []
    count: int = 0
```

Routes (`api/app.py`, mirror the `study-run-baseline` mutating-route pattern incl. `_csrf_ok()` and `Depends(get_workspace)`):
```python
@app.post("/api/run-rerun", tags=["Runs"], summary="Rerun a recorded simulation")
def api_run_rerun(body: dict, request: Request = None, ws: Path = Depends(get_workspace)):
    _csrf_ok(request)
    from vivarium_workbench.lib.rerun import run_rerun
    resp, status = run_rerun(ws, (body or {}).get("run_id", ""))
    return JSONResponse(status_code=status, content=resp)

@app.post("/api/investigation-rerun", tags=["Investigations"], summary="Rerun every study's baseline")
def api_investigation_rerun(body: dict, request: Request = None, ws: Path = Depends(get_workspace)):
    _csrf_ok(request)
    from vivarium_workbench.lib.rerun import rerun_investigation
    inv = (body or {}).get("investigation") or (body or {}).get("name") or ""
    resp, status = rerun_investigation(ws, inv)
    return JSONResponse(status_code=status, content=resp)
```
(Match how the existing routes obtain `request`/CSRF — copy the exact `_csrf_ok` call form used by `study-run-baseline`. Add both paths to any CSRF-required route list, e.g. app.py:445.)

- [ ] **Step 4: Run — verify it passes**

Run: `python -m pytest tests/test_api_rerun.py -v`  Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/models.py vivarium_workbench/api/app.py tests/test_api_rerun.py
git commit -m "feat: POST /api/run-rerun + /api/investigation-rerun"
```

---

### Task 5: UI — three Rerun buttons

**Files:**
- Modify: `vivarium_workbench/templates/index.html.j2` (investigation header)
- Modify: `vivarium_workbench/static/walkthrough.js` (investigation rerun handler)
- Modify: `vivarium_workbench/static/sim-table.js` (`_actions` per-row Rerun)
- Modify: `vivarium_workbench/templates/study-detail.html` + `vivarium_workbench/static/study-detail.js` (Rerun study)
- Test: `tests/test_rerun_ui.py`

**Interfaces:**
- Consumes: `POST /api/investigation-rerun`, `POST /api/run-rerun`, `POST /api/study-run-baseline`. Each sim `<tr>` carries `data-run-id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rerun_ui.py
def test_investigation_header_has_rerun_button(dashboard_client):
    c = dashboard_client(workspace=None)
    html = c.get("/").text
    assert 'id="investigation-rerun"' in html

def test_sim_table_js_wires_rerun(dashboard_client):
    c = dashboard_client(workspace=None)
    js = c.get("/sim-table.js").text
    assert "run-rerun" in js and "Rerun" in js
```

- [ ] **Step 2: Run — verify it fails**

Run: `python -m pytest tests/test_rerun_ui.py -v`  Expected: FAIL.

- [ ] **Step 3: Implement**

- **Investigation header** — `index.html.j2` `.inv-export-actions` span (line 906): add
  `<button id="investigation-rerun" class="btn-mini" title="Re-run every study's baseline">Rerun investigation</button>`.
  In `walkthrough.js` (near `_runUnblockedSimulations`, ~6188), wire a click handler (bind after `_openInvestigationDetail`): `if (!confirm('Re-run every study in this investigation? This launches a fresh baseline run per study.')) return;` → `POST /api/investigation-rerun {investigation: <current name>}` → toast `"<count> runs launched"`, then reuse `#investigation-run-progress`/refresh. Skip in snapshot mode.
- **Sim DB row** — `sim-table.js` `_actions(row)` (line 116): append a `↻ Rerun` control (an `<a>`/`<button>` with `data-run-id`), one-click → `fetch('/api/run-rerun', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({run_id: row.run_id})})` → on ok, toast + `renderTable` refresh. Hide in snapshot mode. (Follows the existing ⬇Data/⬇Analysis action style; the row already exposes `row.run_id`.)
- **Study-detail** — `study-detail.html` header actions + `study-detail.js`: add a "Rerun study" button → `if (!confirm('Re-run this study\'s baseline?')) return;` → `POST /api/study-run-baseline {study: <slug>}` → toast. Live-only.

- [ ] **Step 4: Run — verify + JS parses**

Run: `python -m pytest tests/test_rerun_ui.py -v` and `node --check vivarium_workbench/static/sim-table.js && node --check vivarium_workbench/static/walkthrough.js && node --check vivarium_workbench/static/study-detail.js`. Expected: PASS + JS OK.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/templates/index.html.j2 vivarium_workbench/static/walkthrough.js vivarium_workbench/static/sim-table.js vivarium_workbench/templates/study-detail.html vivarium_workbench/static/study-detail.js tests/test_rerun_ui.py
git commit -m "feat: Rerun buttons — investigation header, study-detail, sim-table row"
```

---

## Self-Review

**Spec coverage:**
- Sim rerun exact recorded config into origin DB → Tasks 1 (classify) + 2 (`launch_into_study`) + 3 (`run_rerun` routing). ✔
- Study rerun (declared baseline) → Task 5 (button → existing `study-run-baseline`). ✔
- Investigation rerun (all studies, force) → Task 3 (`rerun_investigation`) + Task 5 (button). ✔
- Endpoints + models + CSRF → Task 4. ✔
- Three UI buttons + confirm-on-batch / one-click-sim + snapshot degradation → Task 5. ✔
- Detached + concurrency cap → inherited (all launches use the existing detached path / `run_registry.CONCURRENCY_CAP`); no new blocking code. ✔

**Placeholder scan:** No TBD/TODO. Three "confirm the real name" notes name the exact target to verify (`investigations` reader; the `launch_into_study` post-invoke tail; the `_csrf_ok`/`dashboard_client` form) — verification directives, not vague requirements.

**Type consistency:** `resolve_rerun_target` returns `{run_id,origin,study,spec_id,params,n_steps}` — consumed identically in `run_rerun` (Task 3). `launch_into_study(ws_root, study, spec_id, params, n_steps, *, label=None) -> (resp, status)` defined Task 2, called Task 3 with those exact args. `run_rerun`/`rerun_investigation` return `(resp, status)` consumed by the Task 4 routes. Row `run_id` / `data-run-id` is the handle across Task 5 UI and Task 4's `{run_id}` body.
