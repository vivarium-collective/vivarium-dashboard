# Capability-matched Analysis Tools + Parsimony Viewer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Analysis Tools tab match tools to compatible runs/studies by capability, and land the Parsimony Viewer as the first capability-matched tool.

**Architecture:** Runs advertise capability tags derived from emitted shape (reusing `explorer_data._categorize_leaves`) plus an artifact tag `3d_pack`; tools declare a `requires` list; a matcher (`lib/analysis_tools.py`) pairs each tool with compatible runs/studies and serves them via one `GET /api/analysis-tools`; the frontend renders a tools-first tab.

**Tech Stack:** Python 3, FastAPI (`api/app.py`), pydantic (`lib/models.py`), SQLite (`runs_meta`), vanilla JS (`static/walkthrough.js`), Jinja (`templates/index.html.j2`), pytest with the `dashboard_client` subprocess fixture.

## Global Constraints

- Import `lib` homes directly; never add new dependencies on `server.py`.
- Every mutating (POST/DELETE) route calls `_csrf_ok()`. All new routes here are GET — no CSRF needed.
- Return a pydantic model from new endpoints; register the model in `lib/models.py`; TS types are generated from models (`lib/generate_ts.py`).
- Resolve workspace layout via `lib/workspace_paths.py`; never hardcode `studies/`.
- New capability derivation must be best-effort: unreadable/empty store → `[]`, never raises.
- `runs_meta` schema changes are additive nullable columns via `composite_runs._NEW_COLUMNS` only — do NOT edit the vendored `run_registry.RUNS_META_DDL` (byte-faithful copy).
- Publish (`publish.py`) must keep working: new endpoints need a static `api/*.json` form; Launch/Open degrade when there's no live backend.
- Capability vocabulary is single-sourced in `lib/capabilities.py::CAPABILITY_TAGS`.
- Match rule everywhere: `set(tool.requires) <= set(target.capabilities)`.
- Tests run via `pytest`; endpoint tests use the `dashboard_client` fixture against a `tests/_fixtures/` workspace.

---

### Task 1: Capability vocabulary constant

**Files:**
- Create: `vivarium_workbench/lib/capabilities.py`
- Test: `tests/test_capabilities.py`

**Interfaces:**
- Produces: `CAPABILITY_TAGS: dict[str, str]` (tag → one-line description); `CATEGORY_TO_TAG: dict[str, str]` (mapping the `_categorize_leaves` bucket names to tags).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_capabilities.py
from vivarium_workbench.lib.capabilities import CAPABILITY_TAGS, CATEGORY_TO_TAG

def test_vocabulary_has_expected_tags():
    for tag in ["observables", "mass", "bulk_counts", "fluxes",
                "listeners", "growth_division", "3d_pack"]:
        assert tag in CAPABILITY_TAGS
        assert isinstance(CAPABILITY_TAGS[tag], str) and CAPABILITY_TAGS[tag]

def test_category_map_targets_real_tags():
    # every category maps to a defined tag
    for cat, tag in CATEGORY_TO_TAG.items():
        assert tag in CAPABILITY_TAGS
    # the five explorer categories are covered
    assert set(CATEGORY_TO_TAG) == {
        "Mass", "Bulk molecules", "Fluxes", "Listeners", "Growth & division"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_capabilities.py -v`
Expected: FAIL — `ModuleNotFoundError: vivarium_workbench.lib.capabilities`

- [ ] **Step 3: Write minimal implementation**

```python
# vivarium_workbench/lib/capabilities.py
"""Single source of truth for the analysis-tool capability vocabulary.

A *capability* is a lowercase tag a run/study advertises about the data it
produced. Tools declare a ``requires`` list of these tags; the matcher pairs a
tool with a run/study when ``set(requires) <= set(capabilities)``.

Two sources of tags:
  * store-derived — from a run's emitted leaves (see lib/run_capabilities.py),
    reusing the explorer's leaf categorisation (lib/explorer_data._categorize_leaves).
  * artifact-sourced — from workspace files (e.g. 3D packs on disk / hosted).
"""
from __future__ import annotations

CAPABILITY_TAGS: dict[str, str] = {
    "observables": "run has a readable store with at least one emitted leaf",
    "mass": "run emits cell-mass observables",
    "bulk_counts": "run emits bulk molecule counts",
    "fluxes": "run emits reaction fluxes / FBA results",
    "listeners": "run emits listener observables",
    "growth_division": "run emits growth & division observables",
    "3d_pack": "study has a 3D molecular pack (viz/3d/*.pack.json or hosted)",
}

# lib/explorer_data._categorize_leaves bucket name -> capability tag.
CATEGORY_TO_TAG: dict[str, str] = {
    "Mass": "mass",
    "Bulk molecules": "bulk_counts",
    "Fluxes": "fluxes",
    "Listeners": "listeners",
    "Growth & division": "growth_division",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_capabilities.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/capabilities.py tests/test_capabilities.py
git commit -m "feat: capability vocabulary constant"
```

---

### Task 2: Derive store-based capabilities for a run

**Files:**
- Create: `vivarium_workbench/lib/run_capabilities.py`
- Test: `tests/test_run_capabilities.py`

**Interfaces:**
- Consumes: `capabilities.CATEGORY_TO_TAG`; `explorer_data.list_observables(db_path, run_id, workspace) -> {"categories": {name: [...]}}`.
- Produces: `derive_capabilities(db_path, run_id=None, workspace=None) -> list[str]` (sorted, deduped; `[]` on unreadable/empty store, never raises).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_capabilities.py
from vivarium_workbench.lib import run_capabilities as rc

def test_maps_categories_to_tags(monkeypatch):
    monkeypatch.setattr(rc.explorer_data, "list_observables",
        lambda *a, **k: {"categories": {"Mass": [1], "Bulk molecules": [1, 2]}})
    tags = rc.derive_capabilities("x.db", "run1")
    assert set(tags) == {"observables", "mass", "bulk_counts"}
    assert tags == sorted(tags)  # stable order

def test_empty_store_yields_empty(monkeypatch):
    monkeypatch.setattr(rc.explorer_data, "list_observables",
        lambda *a, **k: {"categories": {}})
    assert rc.derive_capabilities("x.db") == []

def test_read_failure_yields_empty(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("cannot open")
    monkeypatch.setattr(rc.explorer_data, "list_observables", boom)
    assert rc.derive_capabilities("x.db") == []  # never raises
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_capabilities.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# vivarium_workbench/lib/run_capabilities.py
"""Store-derived capability tags for one simulation run.

Best-effort and pure: opens the run's store via the existing explorer reader,
maps present leaf-categories to tags, and returns a sorted tag list. Any read
failure or empty store yields ``[]`` (such a run matches no tool).
"""
from __future__ import annotations

from vivarium_workbench.lib import explorer_data
from vivarium_workbench.lib.capabilities import CATEGORY_TO_TAG


def derive_capabilities(db_path, run_id=None, workspace=None) -> list[str]:
    try:
        obs = explorer_data.list_observables(db_path, run_id, workspace)
    except Exception:  # noqa: BLE001 — unreadable store -> no capabilities
        return []
    categories = (obs or {}).get("categories") or {}
    tags: set[str] = set()
    for name, leaves in categories.items():
        if not leaves:
            continue
        tags.add("observables")
        tag = CATEGORY_TO_TAG.get(name)
        if tag:
            tags.add(tag)
    return sorted(tags)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_capabilities.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/run_capabilities.py tests/test_run_capabilities.py
git commit -m "feat: derive store-based run capabilities"
```

---

### Task 3: Persist capabilities — migration + write on finalize

**Files:**
- Modify: `vivarium_workbench/lib/composite_runs.py` (`_NEW_COLUMNS`, ~line 55; run-finalize write path)
- Test: `tests/test_run_capabilities_persist.py`

**Interfaces:**
- Consumes: `run_capabilities.derive_capabilities`.
- Produces: `runs_meta.capabilities_json` column (JSON list text); a helper `write_run_capabilities(conn, run_id, tags: list[str]) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_capabilities_persist.py
import json
from vivarium_workbench.lib import composite_runs

def test_migration_adds_column(tmp_path):
    db = tmp_path / "runs.db"
    conn = composite_runs.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs_meta)")}
    assert "capabilities_json" in cols

def test_write_and_read_capabilities(tmp_path):
    db = tmp_path / "runs.db"
    conn = composite_runs.connect(db)
    conn.execute(
        "INSERT INTO runs_meta (run_id, spec_id, started_at, status) "
        "VALUES ('r1','s1',0.0,'completed')")
    composite_runs.write_run_capabilities(conn, "r1", ["observables", "mass"])
    row = conn.execute(
        "SELECT capabilities_json FROM runs_meta WHERE run_id='r1'").fetchone()
    assert json.loads(row[0]) == ["observables", "mass"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_capabilities_persist.py -v`
Expected: FAIL — `capabilities_json` absent / `write_run_capabilities` undefined.

- [ ] **Step 3: Write minimal implementation**

Add the column to the migration dict (find `_NEW_COLUMNS = {...}` near line 55 and add the entry):

```python
# vivarium_workbench/lib/composite_runs.py  (inside _NEW_COLUMNS)
    "capabilities_json": "TEXT",
```

Add the writer helper (module-level, near `_migrate_runs_meta`):

```python
def write_run_capabilities(conn, run_id: str, tags) -> None:
    """Store a run's capability tags as JSON text in runs_meta."""
    import json
    conn.execute("UPDATE runs_meta SET capabilities_json=? WHERE run_id=?",
                 (json.dumps(list(tags)), run_id))
    conn.commit()
```

Wire it into the run-finalize path: locate where a run's row is marked
`status='completed'` (search `status='completed'` / `status="completed"` in
`composite_runs.py`) and, right after that update, compute + store tags:

```python
    from vivarium_workbench.lib.run_capabilities import derive_capabilities
    tags = derive_capabilities(store_or_db_path, run_id, workspace)
    write_run_capabilities(conn, run_id, tags)
```

(Use the emitter store path the finalize code already has in scope for
`store_or_db_path`; `workspace` may be `None`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_capabilities_persist.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/composite_runs.py tests/test_run_capabilities_persist.py
git commit -m "feat: persist run capabilities (migration + finalize write)"
```

---

### Task 4: Lazy backfill + surface on /api/simulations

**Files:**
- Modify: `vivarium_workbench/lib/simulations_index.py` (`_row_to_dict`, ~line 149)
- Modify: `vivarium_workbench/lib/models.py` (`SimRow`, line 53)
- Test: `tests/test_simulations_capabilities.py`

**Interfaces:**
- Consumes: `run_capabilities.derive_capabilities`; `composite_runs.write_run_capabilities`.
- Produces: `SimRow.capabilities: list[str]`; each `/api/simulations` row carries `capabilities`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_simulations_capabilities.py
import json
from vivarium_workbench.lib import simulations_index as si

def test_completed_run_backfills_and_caches(tmp_path, monkeypatch):
    # a completed run with no cached capabilities gets derived + written back
    monkeypatch.setattr(si.run_capabilities, "derive_capabilities",
                        lambda *a, **k: ["observables", "fluxes"])
    row = {"run_id": "r1", "status": "completed", "capabilities_json": None,
           "db_path": "x.db", "store_path": None}
    out = si._capabilities_for_row(row, conn=_FakeConn())
    assert out == ["observables", "fluxes"]

def test_inprogress_run_derives_without_caching(monkeypatch):
    monkeypatch.setattr(si.run_capabilities, "derive_capabilities",
                        lambda *a, **k: ["observables"])
    conn = _FakeConn()
    row = {"run_id": "r2", "status": "running", "capabilities_json": None,
           "db_path": "x.db", "store_path": None}
    out = si._capabilities_for_row(row, conn=conn)
    assert out == ["observables"]
    assert conn.writes == []  # not cached while running

def test_cached_value_is_used(monkeypatch):
    called = {"n": 0}
    def spy(*a, **k):
        called["n"] += 1; return ["x"]
    monkeypatch.setattr(si.run_capabilities, "derive_capabilities", spy)
    row = {"run_id": "r3", "status": "completed",
           "capabilities_json": json.dumps(["observables", "mass"])}
    out = si._capabilities_for_row(row, conn=_FakeConn())
    assert out == ["observables", "mass"]
    assert called["n"] == 0  # no recompute when cached

class _FakeConn:
    def __init__(self): self.writes = []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_simulations_capabilities.py -v`
Expected: FAIL — `_capabilities_for_row` undefined.

- [ ] **Step 3: Write minimal implementation**

Add a `run_capabilities` import at the top of `simulations_index.py`, then add:

```python
def _capabilities_for_row(row: dict, conn=None) -> list[str]:
    """Capabilities for one runs_meta row: cached value, else derive.

    Completed runs are cached back (including []); in-progress runs derive on
    the fly and are NOT cached (so a still-emitting run isn't frozen empty)."""
    import json
    cached = row.get("capabilities_json")
    if cached:
        try:
            return list(json.loads(cached))
        except Exception:  # noqa: BLE001
            pass
    store = row.get("store_path") or row.get("db_path")
    if not store:
        return []
    tags = run_capabilities.derive_capabilities(store, row.get("run_id"))
    if row.get("status") == "completed" and conn is not None:
        try:
            from vivarium_workbench.lib.composite_runs import write_run_capabilities
            write_run_capabilities(conn, row["run_id"], tags)
        except Exception:  # noqa: BLE001 — caching is best-effort
            pass
    return tags
```

In `_row_to_dict` (~line 149), after the row dict is assembled, set
`d["capabilities"] = _capabilities_for_row(row, conn=conn)` (pass the open
connection the builder already holds; if none is in scope, pass `conn=None`
and rely on next-scan caching). Ensure the `SELECT` that builds `row` includes
`capabilities_json` (add it to the column list).

Add the field to `SimRow` (models.py, in the field block ending ~line 95):

```python
    capabilities: list[str] = []  # capability tags advertised by this run
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_simulations_capabilities.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/simulations_index.py vivarium_workbench/lib/models.py tests/test_simulations_capabilities.py
git commit -m "feat: lazy-backfill run capabilities onto /api/simulations"
```

---

### Task 5: `requires` contract + matcher (`lib/analysis_tools.py`)

**Files:**
- Modify: `vivarium_workbench/lib/analysis_viewers.py` (docstring contract, lines 15–32 — add `requires`)
- Create: `vivarium_workbench/lib/analysis_tools.py`
- Test: `tests/test_analysis_tools.py`

**Interfaces:**
- Consumes: `analysis_viewers.viewers_public(ws_root) -> list[dict]`; the runs index (via `simulations_index.build_simulations_data(ws_root)` — returns rows with `capabilities`); `studies_with_3d_pack(ws_root)` (Task 7).
- Produces: `match(requires: list[str], candidates: list[dict]) -> list[dict]`; `builtin_tools() -> list[dict]`; `build_analysis_tools(ws_root) -> list[dict]`.
- Tool descriptor shape: `{id, title, description, kind, requires, matched: [{ref, label, detail}], unmatched_reason}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analysis_tools.py
from vivarium_workbench.lib import analysis_tools as at

def test_match_requires_subset():
    cands = [
        {"ref": "r1", "capabilities": ["observables", "fluxes"]},
        {"ref": "r2", "capabilities": ["observables"]},
        {"ref": "r3", "capabilities": []},
    ]
    got = at.match(["observables"], cands)
    assert {m["ref"] for m in got} == {"r1", "r2"}
    got2 = at.match(["fluxes"], cands)
    assert {m["ref"] for m in got2} == {"r1"}

def test_builtin_tools_declare_requires():
    ids = {t["id"]: t for t in at.builtin_tools()}
    assert ids["data-explorer"]["requires"] == ["observables"]
    assert ids["parsimony-viewer"]["requires"] == ["3d_pack"]

def test_build_composes_external_and_builtin(monkeypatch):
    monkeypatch.setattr(at, "viewers_public",
        lambda ws: [{"id": "omics", "title": "Omics", "requires": [],
                     "targets": [{"study": "s1", "label": "s1"}]}])
    monkeypatch.setattr(at, "_run_candidates",
        lambda ws: [{"ref": "run1", "label": "run1", "capabilities": ["observables"]}])
    monkeypatch.setattr(at, "_pack_candidates",
        lambda ws: [{"ref": "ecoli-3d", "label": "ecoli-3d", "capabilities": ["3d_pack"]}])
    tools = {t["id"]: t for t in at.build_analysis_tools("/ws")}
    # external tool with no requires keeps its targets verbatim
    assert tools["omics"]["matched"] == [] and tools["omics"]["targets"]
    # data explorer matched the observables run
    assert {m["ref"] for m in tools["data-explorer"]["matched"]} == {"run1"}
    # parsimony matched the 3d_pack study
    assert {m["ref"] for m in tools["parsimony-viewer"]["matched"]} == {"ecoli-3d"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_tools.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

First document the new field in `analysis_viewers.py` (add inside the "Each
viewer dict:" block near line 20):

```
      "requires":    list[str],          # optional; capability tags a run/study
                                         #   must advertise to match this tool.
                                         #   Absent/empty -> not run-matched;
                                         #   the viewer's own "targets" are used.
```

Then create the matcher module:

```python
# vivarium_workbench/lib/analysis_tools.py
"""Compose the Analysis Tools tab: external viewers + built-in tools, each
matched to the runs/studies whose capabilities satisfy the tool's ``requires``.
Match rule: set(requires) <= set(candidate.capabilities)."""
from __future__ import annotations

from pathlib import Path

from vivarium_workbench.lib.analysis_viewers import viewers_public


def match(requires, candidates: list[dict]) -> list[dict]:
    req = set(requires or [])
    if not req:
        return []
    return [c for c in candidates if req <= set(c.get("capabilities") or [])]


def builtin_tools() -> list[dict]:
    return [
        {"id": "data-explorer", "title": "Data Explorer",
         "description": "Interactively explore a run: timeseries, scatter, "
                        "allocation, and flux maps.",
         "kind": "embed-explorer", "requires": ["observables"]},
        {"id": "parsimony-viewer", "title": "Parsimony Viewer",
         "description": "3D molecular packing of a cell — saved views at "
                        "declared times.",
         "kind": "embed-3d", "requires": ["3d_pack"]},
    ]


def _run_candidates(ws_root) -> list[dict]:
    from vivarium_workbench.lib.simulations_index import build_simulations_data
    data = build_simulations_data(ws_root) or {}
    out = []
    for r in data.get("runs", []):
        out.append({"ref": r.get("run_id"),
                    "label": r.get("label") or r.get("sim_name") or r.get("run_id"),
                    "detail": r.get("emitter_type") or "",
                    "capabilities": r.get("capabilities") or []})
    return out


def _pack_candidates(ws_root) -> list[dict]:
    from vivarium_workbench.lib.analysis_tools_3d import studies_with_3d_pack
    out = []
    for s in studies_with_3d_pack(ws_root):
        views = ", ".join(p["name"] for p in s.get("packs", [])) or "3D pack"
        out.append({"ref": s["study"], "label": s["study"],
                    "detail": views, "capabilities": ["3d_pack"],
                    "viewer_url": s.get("viewer_url")})
    return out


def build_analysis_tools(ws_root) -> list[dict]:
    ws_root = Path(ws_root)
    runs = _run_candidates(ws_root)
    packs = _pack_candidates(ws_root)
    tools: list[dict] = []

    # external contributed viewers (may or may not declare requires)
    for v in viewers_public(ws_root):
        v = dict(v)
        v.setdefault("requires", [])
        v["matched"] = match(v["requires"], runs) if v["requires"] else []
        tools.append(v)

    # built-in tools
    for t in builtin_tools():
        t = dict(t)
        cands = packs if "3d_pack" in t["requires"] else runs
        t["matched"] = match(t["requires"], cands)
        t["unmatched_reason"] = (
            f"No compatible runs — needs {', '.join(t['requires'])}."
            if not t["matched"] else "")
        tools.append(t)
    return tools
```

(Note: `studies_with_3d_pack` lives in `analysis_tools_3d.py` created in Task 7;
its absence would only break `_pack_candidates`, which Task 7's test covers.
For Task 5's tests it is monkeypatched.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/analysis_tools.py vivarium_workbench/lib/analysis_viewers.py tests/test_analysis_tools.py
git commit -m "feat: requires contract + tool/run capability matcher"
```

---

### Task 6: `/api/analysis-tools` endpoint + payload model + publish

**Files:**
- Modify: `vivarium_workbench/lib/models.py` (new `AnalysisToolsPayload`)
- Modify: `vivarium_workbench/api/app.py` (new `GET /api/analysis-tools`)
- Modify: `vivarium_workbench/publish.py` (emit `api/analysis-tools.json`)
- Test: `tests/test_api_analysis_tools.py`

**Interfaces:**
- Consumes: `analysis_tools.build_analysis_tools(ws_root)`; `_root.get()` for the workspace root.
- Produces: `GET /api/analysis-tools -> {"tools": [...]}`; `AnalysisToolsPayload`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_analysis_tools.py
def test_analysis_tools_endpoint(dashboard_client):
    r = dashboard_client.get("/api/analysis-tools")
    assert r.status_code == 200
    body = r.json()
    assert "tools" in body
    ids = {t["id"] for t in body["tools"]}
    assert {"data-explorer", "parsimony-viewer"} <= ids
    for t in body["tools"]:
        assert "requires" in t and "matched" in t
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_analysis_tools.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Write minimal implementation**

Add the model (models.py):

```python
class AnalysisToolsPayload(BaseModel):
    """GET /api/analysis-tools — tools-first Analysis Tools tab."""
    model_config = ConfigDict(extra="allow")
    tools: list[dict] = []
```

Add the route (api/app.py, near the other analysis routes ~876):

```python
@app.get("/api/analysis-tools", response_model=AnalysisToolsPayload)
def api_analysis_tools():
    from vivarium_workbench.lib.analysis_tools import build_analysis_tools
    from vivarium_workbench.lib import _root
    return {"tools": build_analysis_tools(_root.get())}
```

Add the import of `AnalysisToolsPayload` to app.py's models import line.

In `publish.py`, where the other `api/*.json` snapshots are written, add:

```python
    from vivarium_workbench.lib.analysis_tools import build_analysis_tools
    _write_json(out / "api" / "analysis-tools.json",
                {"tools": build_analysis_tools(ws_root)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_analysis_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/models.py vivarium_workbench/api/app.py vivarium_workbench/publish.py tests/test_api_analysis_tools.py
git commit -m "feat: GET /api/analysis-tools endpoint + publish snapshot"
```

---

### Task 7: `3d_pack` capability + per-study model gallery

**Files:**
- Create: `vivarium_workbench/lib/analysis_tools_3d.py`
- Modify: `vivarium_workbench/api/app.py` (new `GET /api/study/{study}/3d/models.json`)
- Test: `tests/test_analysis_tools_3d.py`
- Fixture: add `viz/3d/*.pack.json` under an existing `tests/_fixtures/` study

**Interfaces:**
- Consumes: `saved_visualizations.build_saved_visualizations(ws_root)` (finds `viz/3d/*.pack.json`) and `ui.viz_viewer_urls`; `workspace_paths` for study dir.
- Produces: `studies_with_3d_pack(ws_root) -> [{study, packs:[{name,file}], viewer_url?}]`; `study_models_manifest(ws_root, study) -> [{name, file}]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analysis_tools_3d.py
from vivarium_workbench.lib import analysis_tools_3d as a3

def test_studies_with_3d_pack_from_disk(monkeypatch):
    monkeypatch.setattr(a3, "build_saved_visualizations", lambda ws: {
        "saved": [
            {"study": "ecoli-3d", "name": "initial",
             "pack_url": "/files/studies/ecoli-3d/viz/3d/initial.pack.json"},
            {"study": "ecoli-3d", "name": "division",
             "pack_url": "/files/studies/ecoli-3d/viz/3d/division.pack.json"},
        ]})
    monkeypatch.setattr(a3, "_hosted_viewer_urls", lambda ws: {})
    studies = a3.studies_with_3d_pack("/ws")
    s = {x["study"]: x for x in studies}["ecoli-3d"]
    assert [p["name"] for p in s["packs"]] == ["initial", "division"]

def test_manifest_default_initial_first(monkeypatch):
    monkeypatch.setattr(a3, "studies_with_3d_pack", lambda ws: [
        {"study": "ecoli-3d", "packs": [
            {"name": "division", "file": "/a/division.pack.json"},
            {"name": "initial", "file": "/a/initial.pack.json"}]}])
    manifest = a3.study_models_manifest("/ws", "ecoli-3d")
    # 'initial' snapshot is ordered first when present
    assert manifest[0]["name"] == "initial"

def test_hosted_viewer_url_attaches(monkeypatch):
    monkeypatch.setattr(a3, "build_saved_visualizations", lambda ws: {"saved": []})
    monkeypatch.setattr(a3, "_hosted_viewer_urls",
        lambda ws: {"ecoli-3d": "https://r2/viewer?models=..."})
    studies = {x["study"]: x for x in a3.studies_with_3d_pack("/ws")}
    assert studies["ecoli-3d"]["viewer_url"].startswith("https://r2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_tools_3d.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# vivarium_workbench/lib/analysis_tools_3d.py
"""3D-pack capability: which studies advertise ``3d_pack`` and their saved-view
gallery. A study advertises 3d_pack if it has viz/3d/*.pack.json on disk OR a
configured hosted pack in ui.viz_viewer_urls. Reuses the existing pack scan."""
from __future__ import annotations

from vivarium_workbench.lib.saved_visualizations import build_saved_visualizations

_INITIAL_HINTS = ("initial", "birth", "10s", "t10", "start")


def _hosted_viewer_urls(ws_root) -> dict:
    """study -> hosted viewer/models URL from ui.viz_viewer_urls (best-effort)."""
    try:
        from vivarium_workbench.lib.workspace_config import read_ui_config  # existing reader
        cfg = read_ui_config(ws_root) or {}
        return dict(cfg.get("viz_viewer_urls") or {})
    except Exception:  # noqa: BLE001
        return {}


def _pack_name_rank(name: str) -> int:
    n = (name or "").lower()
    return 0 if any(h in n for h in _INITIAL_HINTS) else 1


def studies_with_3d_pack(ws_root) -> list[dict]:
    saved = (build_saved_visualizations(ws_root) or {}).get("saved") or []
    by_study: dict[str, list[dict]] = {}
    for entry in saved:
        study = entry.get("study")
        if not study:
            continue
        by_study.setdefault(study, []).append(
            {"name": entry.get("name") or "snapshot",
             "file": entry.get("pack_url")})
    hosted = _hosted_viewer_urls(ws_root)
    out = []
    studies = set(by_study) | set(hosted)
    for study in sorted(studies):
        packs = sorted(by_study.get(study, []),
                       key=lambda p: (_pack_name_rank(p["name"]), p["name"]))
        rec = {"study": study, "packs": packs}
        if hosted.get(study):
            rec["viewer_url"] = hosted[study]
        out.append(rec)
    return out


def study_models_manifest(ws_root, study) -> list[dict]:
    for s in studies_with_3d_pack(ws_root):
        if s["study"] == study:
            return sorted(s.get("packs", []),
                          key=lambda p: (_pack_name_rank(p["name"]), p["name"]))
    return []
```

(If `workspace_config.read_ui_config` does not exist, read `ui.viz_viewer_urls`
the same way `saved_visualizations.py:114-120` already does and factor that read
into `_hosted_viewer_urls`.)

Add the route (api/app.py):

```python
@app.get("/api/study/{study}/3d/models.json")
def api_study_3d_models(study: str):
    from vivarium_workbench.lib.analysis_tools_3d import study_models_manifest
    from vivarium_workbench.lib import _root
    return study_models_manifest(_root.get(), study)
```

Add a fixture pack: create two tiny valid `parsimony.pack.v1` JSON files under
`tests/_fixtures/<existing-study-ws>/studies/<study>/viz/3d/initial.pack.json`
and `division.pack.json` (minimal: `{"format":"parsimony.pack.v1","bounds":
{"min":[0,0,0],"max":[1,1,1]},"compartments":[],"ingredients":[],"placements":[]}`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_tools_3d.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/analysis_tools_3d.py vivarium_workbench/api/app.py tests/test_analysis_tools_3d.py tests/_fixtures
git commit -m "feat: 3d_pack capability + per-study model gallery manifest"
```

---

### Task 8: Tools-first frontend + remove H2/paragraph

**Files:**
- Modify: `vivarium_workbench/static/walkthrough.js` (`_loadAnalysesPage` ~1538; new `_renderToolCard`; reuse `_render3dVizCard` ~1386, `_renderExplorerCard` ~1502)
- Modify: `vivarium_workbench/templates/index.html.j2` (page `#page-visualizations`, lines 642–648)
- Test: `tests/test_analyses_page_render.py`

**Interfaces:**
- Consumes: `GET /api/analysis-tools`; per-study `GET /api/study/{study}/3d/models.json`; `window.Explorer.mount(mountEl, {run_id})`.
- Produces: one `.tool-card` per tool with a `.tool-requires` line and matched rows; per-tool empty-state text.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analyses_page_render.py
def test_tab_has_no_h2_or_paragraph(dashboard_client):
    html = dashboard_client.get("/").text
    # the redundant in-page H2 and the descriptive paragraph are gone
    assert ">Analysis Tools</h2>" not in html
    assert "Interactive scenes saved as workspace artifacts" not in html

def test_analysis_tools_json_drives_cards(dashboard_client):
    # the tools payload is the data source for the tab
    body = dashboard_client.get("/api/analysis-tools").json()
    assert any(t["id"] == "parsimony-viewer" for t in body["tools"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analyses_page_render.py -v`
Expected: FAIL — H2/paragraph still present.

- [ ] **Step 3: Write minimal implementation**

In `index.html.j2`, page `#page-visualizations`: delete the
`<h2 class="page-title">Analysis Tools</h2>` line (642) and the
`<p ...>Interactive scenes saved as workspace artifacts…</p>` line (646).
Retitle the card heading (645) from "Saved visualizations" to "Tools"; keep the
`#analyses-gallery` mount (647).

In `walkthrough.js`, replace `_loadAnalysesPage`'s body to fetch the unified
endpoint and render tool cards:

```javascript
async _loadAnalysesPage() {
  const gallery = document.getElementById('analyses-gallery');
  if (!gallery) return;
  gallery.innerHTML = '';
  let tools = [];
  try { tools = (await this._api('/api/analysis-tools')).tools || []; }
  catch (e) { gallery.innerHTML = '<p class="muted">Tools unavailable.</p>'; return; }
  const count = document.getElementById('viz-count');
  if (count) count.textContent = '(' + tools.length + ')';
  tools.forEach(t => gallery.appendChild(this._renderToolCard(t)));
}

_renderToolCard(t) {
  const card = document.createElement('div');
  card.className = 'tool-card';
  const req = (t.requires && t.requires.length)
    ? '<div class="tool-requires">Needs: ' + t.requires.join(', ') + '</div>' : '';
  card.innerHTML = '<h4>' + this._esc(t.title) + '</h4>' +
    '<p>' + this._esc(t.description || '') + '</p>' + req;
  const rows = document.createElement('div');
  rows.className = 'tool-matches';
  const items = (t.matched && t.matched.length) ? t.matched : (t.targets || []);
  if (!items.length) {
    rows.innerHTML = '<p class="muted">' +
      this._esc(t.unmatched_reason || 'No compatible runs.') + '</p>';
  } else {
    items.forEach(m => rows.appendChild(this._renderToolRow(t, m)));
  }
  card.appendChild(rows);
  return card;
}

_renderToolRow(tool, m) {
  const row = document.createElement('div');
  row.className = 'tool-row';
  const label = m.label || m.ref || m.study || '';
  const detail = m.detail ? ' · ' + m.detail : '';
  row.innerHTML = '<span class="tool-row-label">' + this._esc(label) +
    '</span><span class="muted">' + this._esc(detail) + '</span>';
  const btn = document.createElement('button');
  btn.className = 'btn';
  if (tool.kind === 'embed-explorer') {
    btn.textContent = 'Launch';
    btn.onclick = () => this._mountExplorerForRun(m.ref);
  } else if (tool.kind === 'embed-3d') {
    btn.textContent = 'Open';
    btn.onclick = () => this._open3dViewer(m);
  } else {
    btn.textContent = 'Launch';
    btn.onclick = () => this._launchViewer(tool.id, m.study || m.ref);
  }
  row.appendChild(btn);
  return row;
}

_mountExplorerForRun(runId) {
  const mount = document.getElementById('explorer-mount') || (() => {
    const el = document.createElement('div'); el.id = 'explorer-mount';
    document.getElementById('analyses-gallery').appendChild(el); return el;
  })();
  if (window.Explorer) window.Explorer.mount(mount, { run_id: runId });
}

_open3dViewer(m) {
  // Prefer a hosted viewer_url; else the bundled viewer with a synthesized gallery.
  const base = this._base || '';
  const url = m.viewer_url
    ? m.viewer_url
    : base + '/parsimony-viewer/index.html?models=' +
      encodeURIComponent(base + '/api/study/' + encodeURIComponent(m.ref || m.study) + '/3d/models.json');
  this._render3dIframe(url);  // extract the iframe-build tail of _render3dVizCard
}
```

Refactor the iframe-building tail of the existing `_render3dVizCard` (1386–1421)
into a `_render3dIframe(url)` helper that `_open3dViewer` reuses (mount the
`<iframe class="viz-embed">` + "Open ↗" link into the gallery). Remove the
top-level per-pack loop that previously called `_render3dVizCard`. Add minimal
CSS for `.tool-card/.tool-requires/.tool-row` to the existing stylesheet (match
current card styles).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analyses_page_render.py -v`
Expected: PASS

- [ ] **Step 5: Manual smoke + commit**

Serve against a workspace with a 3D pack and a run; confirm the Parsimony
Viewer card lists the study and Open renders the gallery; Data Explorer lists a
run and Launch mounts the explorer.

```bash
git add vivarium_workbench/static/walkthrough.js vivarium_workbench/templates/index.html.j2 tests/test_analyses_page_render.py
git commit -m "feat: tools-first Analysis Tools tab; remove redundant header/paragraph"
```

---

### Task 9: Regenerate TS types + full suite

**Files:**
- Modify: generated TS types (via `lib/generate_ts.py`)

- [ ] **Step 1: Regenerate types**

Run: `python -m vivarium_workbench.lib.generate_ts` (or the documented generator entry). Expected: `SimRow.capabilities` and `AnalysisToolsPayload` appear in the generated types.

- [ ] **Step 2: Run the full suite + mypy**

Run: `pytest -q && mypy vivarium_workbench/lib/run_capabilities.py vivarium_workbench/lib/analysis_tools.py vivarium_workbench/lib/analysis_tools_3d.py`
Expected: PASS (no regressions).

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: regenerate TS types for capabilities + analysis-tools"
```

---

## Self-Review

**Spec coverage:**
- Capability vocabulary → Task 1. ✔
- Runs advertise (derive) → Task 2. ✔
- Persistence lazy+cache, completed-only → Tasks 3, 4. ✔
- `SimRow.capabilities` / `/api/simulations` → Task 4. ✔
- `requires` contract → Task 5. ✔
- Matcher + unified payload → Tasks 5, 6. ✔
- `/api/analysis-tools` + publish snapshot → Task 6. ✔
- `3d_pack` capability (disk + hosted) → Task 7. ✔
- Saved-views gallery / `models.json` route / default-initial → Task 7. ✔
- Parsimony Viewer tool + Data Explorer tool → Tasks 5, 8. ✔
- Tools-first UI + remove H2/paragraph → Task 8. ✔
- Omics stays targets-verbatim → Task 5 (`requires` empty path). ✔
- TS types regen → Task 9. ✔
- Sub-project B → out of scope (separate spec), noted. ✔

**Placeholder scan:** No TBD/TODO; every code step has concrete code. Two explicit "if the existing reader differs" notes (Task 3 finalize path, Task 7 `read_ui_config`) point at the exact existing code to mirror (`saved_visualizations.py:114-120`), not vague instructions.

**Type consistency:** `derive_capabilities(db_path, run_id, workspace)` used identically in Tasks 2/3/4. `match(requires, candidates)` and candidate dicts carry `capabilities` in Tasks 5/7. `matched` row shape `{ref,label,detail}` consumed by `_renderToolRow` in Task 8. `studies_with_3d_pack`/`study_models_manifest` defined in Task 7, consumed in Tasks 5/8. `write_run_capabilities(conn, run_id, tags)` defined Task 3, used Task 4.
