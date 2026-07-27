# Phase 3 PR C — Read-only Workbench Audit View Implementation Plan

> **For agentic workers:** implement task-by-task, TDD where practical. Steps use checkbox (`- [ ]`).

**Goal:** Surface the L0–L5 study-reproducibility audit in the workbench as a read-only view: a `GET /api/audit` endpoint returning `viva_superpowers.study_audit.audit_workspace(ws_root).as_dict()`, and a frontend Audit panel rendering it (per-study L0–L5 checks with ✓/⚠/✗ + details + a summary). Read-only — no mutations, no gate; this is the *visible* companion to the CI gate (PR B2).

**Architecture:** Mirror the existing read-only endpoint pattern (`GET /api/investigation-graph` → `lib/investigation_graph_views.build_investigation_graph(ws, ...)` returns `(body, status)`). New `lib/audit_views.py::build_audit(ws_root) -> tuple[dict, int]` wraps `viva_superpowers.study_audit.audit_workspace`, deriving the workspace's own package (via `WorkspacePaths` / `workspace.yaml`) as `extra_packages` so its composites resolve (same lever the CLI `--package` provides). Frontend follows the vanilla-JS view module pattern (e.g. `static/aig-graph.js`), wired into the existing nav rail + `data-source.js` (live + snapshot). Publish adds `api/audit.json` and degrades gracefully.

**Tech Stack:** FastAPI (`api/app.py`), Python `lib/`, vanilla JS (`static/`), pytest + the `dashboard_client` fixture.

## Global Constraints

- **Worktree:** `~/code/vwb-audit-view`, branch `feat/audit-view` (off `origin/main` @ `a051510`). Verify branch/HEAD before commits.
- **Tests:** `/Users/eranagmon/code/venv/bin/python -m pytest` from the worktree. The FastAPI app import hits a pre-existing unrelated `process_bigraph.composite_spec` error in some test modules — do NOT try to fix that; test `lib/audit_views.py` directly and (if the app imports in this env) the route; otherwise cover the lib function + a unit-level route test.
- **`viva_superpowers` is a dependency** (workbench deps `pbg-superpowers`); import `from viva_superpowers import study_audit`. Do not vendor or reimplement it.
- **Read-only.** No POST/DELETE, no CSRF surface, no workspace writes. The endpoint is a pure GET.
- **Tolerant:** a workspace with no studies / a study_audit failure must yield a valid empty-ish report + 200, never a 500 (mirror `build_investigation_graph`'s tolerance). Wrap the audit call; on unexpected error return `({"error": "..."}, 200)` with an empty studies list so the UI degrades.
- **Self-contained frontend** (CSP-safe, no external assets), and it must render in BOTH live and published-snapshot modes (`data-source.js`).

---

### Task 1: `lib/audit_views.py` + `/api/audit` endpoint

**Files:** Create `vivarium_workbench/lib/audit_views.py`; Modify `vivarium_workbench/api/app.py`; Create `tests/test_audit_views.py`.

**Interface:**
```python
# lib/audit_views.py
def build_audit(ws_root) -> tuple[dict, int]:
    """Run the L0–L5 audit and return (report.as_dict(), 200). Derives the
    workspace's own package from WorkspacePaths as extra_packages so its
    composites resolve. Tolerant: any failure -> ({"error": str, "studies": [],
    "investigations": []}, 200)."""
```
- Derive the workspace package: read `workspace.yaml` via the workbench `WorkspacePaths` (there is a `package`/`package_path`/`name` resolution — reuse it); pass `["<pkg>", "<pkg>.composites"]` as `extra_packages` to `audit_workspace`, best-effort.
- Endpoint in `app.py`, mirroring `investigation_graph` (~L1986):
  ```python
  @app.get("/api/audit")
  def audit(ws: Path = Depends(get_workspace)):
      body, status = _audit_views.build_audit(ws)
      return JSONResponse(body, status_code=status)
  ```
  (match the module's existing import + JSONResponse conventions.)

- [ ] **Step 1: Failing test** `tests/test_audit_views.py`: build a tmp workspace (`workspace.yaml` + one canonical `studies/s1/study.yaml`), call `build_audit(ws)` → returns `(dict, 200)` with `"studies"` a list, JSON-serializable (`json.dumps` round-trips), and `summary.hard_failures` present. A second case: empty workspace → `("studies": [])`, still 200.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `build_audit` + the route. Reuse `study_audit.audit_workspace`; do NOT pass a gate/allowlist (view is informational).
- [ ] **Step 4:** Run → PASS. If the app imports in this env, add a route test via the `dashboard_client` fixture hitting `/api/audit` (200, JSON has `studies`); if the app import fails (pre-existing), skip the route test with a clear reason and keep the lib test.
- [ ] **Step 5:** Commit: `feat(audit-view): /api/audit endpoint + build_audit lib`.

---

### Task 2: `data-source.js` accessor (live + snapshot)

**Files:** Modify `vivarium_workbench/static/data-source.js`.

- Add `getAudit()` mirroring the existing accessors: live mode → `_get(_base() + "/api/audit")`; snapshot mode → `_get(_base() + "/api/audit.json")`. Follow the exact `_get`/`_base` conventions already in the file.

- [ ] **Step 1:** Read the existing accessor pattern (e.g. the investigation-graph / study accessors) and add `getAudit()` consistently. (No JS test harness exists; correctness is by matching the established pattern — keep it a 3–5 line function identical in shape to its neighbors.)
- [ ] **Step 2:** Commit: `feat(audit-view): data-source getAudit (live + snapshot)`.

---

### Task 3: Frontend Audit view + nav entry

**Files:** Create `vivarium_workbench/static/audit.js`; Modify `vivarium_workbench/templates/index.html.j2` (nav rail entry + a view container + `<script>` include); reference `static/aig-graph.js` as the structural model.

- A module that, when its view activates, calls `dataSource.getAudit()` and renders: a summary header (`N studies, M investigations, K hard failures`), then per study/investigation a compact block listing its checks as `✓/⚠/✗ L# check-name — detail`, grouped/colored by status (fail=red, warn=amber, pass=green). Purely presentational, self-contained CSS (reuse existing classes where present).
- Wire ONE nav-rail entry ("Audit") in `index.html.j2`'s `role="tablist"` rail (mirror how "Investigation Graph"/`aig-graph` is registered — find its `data-view`/onclick wiring and replicate), a matching view container div, and include `audit.js`.
- Must render in snapshot mode too (guard for missing backend → show "audit unavailable in this snapshot" if `getAudit` 404s).

- [ ] **Step 1:** Study `aig-graph.js` + how it's registered in `index.html.j2` and activated in `client.js`. Replicate that wiring for `audit.js` with the same lifecycle (lazy render on first activation).
- [ ] **Step 2:** Implement `audit.js` + the nav/template wiring. Keep it dependency-free and CSP-safe (no external fetch beyond the same-origin `/api/audit`).
- [ ] **Step 3:** Manual smoke: serve the worktree against the v2ecoli workspace and confirm the Audit tab renders the 49 studies with the 11 hard failures flagged. (Document the serve command used in the commit body.)
- [ ] **Step 4:** Commit: `feat(audit-view): read-only Audit tab rendering L0–L5 report`.

---

### Task 4: Publish/snapshot support

**Files:** Modify `vivarium_workbench/publish.py` (or the publish module that writes `api/*.json`).

- During publish, call `audit_views.build_audit(ws)` and write `api/audit.json` (sanitize non-finite floats per the existing `allow_nan=False` convention — the audit emits only str/int/list so this should be a no-op, but route it through the same writer). The Audit tab then works in the static bundle.

- [ ] **Step 1:** Find where publish writes the per-view `api/*.json` (e.g. `api/investigation-graph*.json` or similar) and add `api/audit.json` the same way.
- [ ] **Step 2:** A publish test (if one exists for the bundle) asserting `api/audit.json` is written + parses; else a direct call test.
- [ ] **Step 3:** Commit: `feat(audit-view): include api/audit.json in the published bundle`.

---

## Self-Review

- **Coverage:** endpoint (T1), data access (T2), UI + nav (T3), snapshot (T4) — the full read-only surface.
- **Consistency:** `build_audit` returns `(dict, int)` like `build_investigation_graph`; `getAudit()` matches sibling accessors; the nav entry matches the `aig-graph` registration.
- **Read-only / tolerant:** no mutations; a broken workspace yields a 200 empty-ish report, never a 500.
- **Out of scope:** any gate/allowlist logic (that's PR B2, already merged and enforcing); per-check drill-downs beyond the flat list.

## Notes

- Confirm the workbench `WorkspacePaths` package-resolution helper name before use (grep `package_path`/`package_slug` in `lib/workspace_paths.py`); if the workbench lacks one, derive from `workspace.yaml`'s `name`/`package_path` directly.
- The audit runs `discover_generators` (imports packages) → may print to stdout; the endpoint should not let that corrupt the JSON response (FastAPI serializes the return value, so stdout noise is harmless here — unlike the CLI `--json`; no redirect needed).
