# Config → Composite: Workbench Glue (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the Phase-1 config→composite translator reachable from the workbench and renderable in the loom — an env-worker method + an HTTP route + a "View as bigraph" control in the loom's Config panel — so a user can load a vEcoli config JSON and see its declared process layer as a bigraph.

**Architecture:** The workbench stays generic. A new env-worker method `config_to_composite` runs in the *workspace's* interpreter (where the fork + the `v2ecoli.library.config_to_composite` translator live): it builds a core, calls `register_declared_processes` + `config_to_composite`, and returns a loom-ready `{schema, state}` document. A thin lib handler + `POST /api/config-to-composite` route expose it. The loom's `ConfigPanel` gains a control that POSTs a config and renders the returned document via the existing `setState`/`composite:load` path — no new renderer (`convert.ts::stateToReactFlow` already draws the document).

**Tech Stack:** Python 3.12 (FastAPI, the pooled env-worker), the loom SPA (React + Vite + vitest), pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-config-to-composite-translator-design.md` §3.4 (lives in the v2ecoli repo; the design is shared across both phases).

## Global Constraints

- **Repo/worktree:** vivarium-workbench, worktree `~/code/vivarium-workbench--loom-config-overrides` (branch `feat/config-as-bigraph-loom`, off `origin/main`). Never touch the canonical `~/code/vivarium-workbench` checkout.
- **CROSS-REPO DEPENDENCY:** the env-worker method imports `v2ecoli.library.config_to_composite`, which reaches the sms-ecoli workspace only after **v2ecoli PR #605 merges + `scripts/sync_upstream.sh` runs**. Until then: (a) Python unit tests mock the env-worker (monkeypatch `get_pool`), needing no real translator; (b) end-to-end/manual verification requires the translator present — either #605 merged+synced, or `PYTHONPATH` prepending the `~/code/v2ecoli--config-to-composite` worktree for the env-worker's interpreter. Do the mockable backend tasks first; gate the e2e step on translator availability.
- **Editable install:** the sms-ecoli venv already runs this worktree's `vivarium_workbench` editable, so backend changes are picked up on `/viva-workbench restart`. Frontend (loom) changes need a Vite rebuild — `node`/`npm` + `node_modules` are present in `vivarium_workbench/loom/`; build with `npm --prefix vivarium_workbench/loom run build` (writes the gitignored `_dist/` the server serves).
- **Generic-workbench principle:** the workbench must not hard-require v2ecoli. The env-worker method imports the translator **guarded** — ImportError → an `{"__unavailable__": true}` result the route turns into a clean 501/"translator not available in this workspace", never a 500.
- **No AI attribution** in commits.

---

### Task 1: env-worker `config_to_composite` method

Add the workspace-interpreter method that builds the loom document from a config.

**Files:**
- Modify: `vivarium_workbench/env_worker.py` (the `_CAPABILITIES` list ~line 88; the method-dispatch chain ~line 2796–2820; add the handler near `_resolve_composite_state` ~line 1016)
- Test: `tests/test_env_worker_config_to_composite.py`

**Interfaces:**
- Produces (env-worker method `config_to_composite`, params `{"config": <dict>}`): returns `{"state": <dict>, "schema": <dict>}` on success; `{"__unavailable__": true}` if the workspace has no translator; `{"__error__": <str>}` if translation/registration raised.

- [ ] **Step 1: Write the failing test** (drives the handler directly, fork-backed; skip if fork/translator absent)

```python
# tests/test_env_worker_config_to_composite.py
import os, importlib.util, pytest

FORK = os.environ.get("V2E_VECOLI_DIR", "")
_have_translator = importlib.util.find_spec("v2ecoli.library.config_to_composite") is not None

@pytest.mark.skipif(not (FORK and os.path.isdir(FORK) and _have_translator),
                    reason="needs the vEcoli fork + the v2ecoli translator (post-#605 sync)")
def test_config_to_composite_handler_returns_loom_document():
    import ecoli.processes  # noqa: F401 — fork registry first
    from vivarium_workbench.env_worker import _config_to_composite
    cfg = {"add_processes": ["pg-shape"], "topology": {}}
    out = _config_to_composite({"config": cfg})
    assert "state" in out and "schema" in out
    node = out["state"]["pg-shape"]
    assert node["_type"] == "process" and node["address"] == "local:PGShape"

def test_config_to_composite_handler_unavailable_without_translator(monkeypatch):
    # Simulate a workspace whose package has no translator: force the import to fail.
    import builtins, vivarium_workbench.env_worker as ew
    real_import = builtins.__import__
    def _boom(name, *a, **k):
        if name.startswith("v2ecoli.library.config_to_composite"):
            raise ImportError("no translator")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _boom)
    assert ew._config_to_composite({"config": {}}) == {"__unavailable__": True}
```

- [ ] **Step 2: Run — verify it fails**

Run: `cd ~/code/vivarium-workbench--loom-config-overrides && PYTHONPATH=$PWD ~/code/sms-ecoli/.venv/bin/python -m pytest tests/test_env_worker_config_to_composite.py -q`
Expected: FAIL (`_config_to_composite` undefined). The fork-backed case may `skip` if the translator isn't synced yet — that's fine; the `unavailable` case must run.

- [ ] **Step 3: Implement the handler + register it**

Add near `_resolve_composite_state` in `env_worker.py`:

```python
def _config_to_composite(params: dict) -> dict:
    """Translate a vEcoli-style config into a loom-renderable {state, schema}
    document, in the workspace interpreter (the fork + translator live here).

    Guarded import: a workspace without the v2ecoli-family translator returns
    ``{"__unavailable__": True}`` so the route can answer cleanly rather than 500.
    """
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    _import_workspace_package(_workspace)
    try:
        from v2ecoli.library.config_to_composite import (
            config_to_composite, register_declared_processes)
    except Exception:  # noqa: BLE001 — no translator in this workspace
        return {"__unavailable__": True}
    try:
        from v2ecoli.core import build_core
        cfg = (params or {}).get("config") or {}
        core = build_core()
        register_declared_processes(core, cfg)
        doc = config_to_composite(cfg)
        # numpy-free already (declared-layer shapes are plain JSON); summarize
        # defensively in case a process_config carried an array.
        doc = _summarize_large_values(doc)
        return {"state": doc.get("state", {}), "schema": doc.get("schema", {})}
    except Exception as e:  # noqa: BLE001
        return {"__error__": str(e)}
```

Add `"config_to_composite"` to `_CAPABILITIES`, and in the dispatch chain (next to `resolve_composite_state`):

```python
    if method == "config_to_composite":
        return _config_to_composite(params)
```

- [ ] **Step 4: Run — verify pass** (the `unavailable` test must pass; the fork case passes when the translator is available)

Run: same as Step 2. Expected: `unavailable` PASS; fork case PASS or SKIP.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/env_worker.py tests/test_env_worker_config_to_composite.py
git commit -m "feat(env-worker): config_to_composite method — config JSON -> loom document"
```

---

### Task 2: lib handler + `POST /api/config-to-composite` route

Expose the method over HTTP, returning a `CompositeState`-shaped payload the loom already consumes.

**Files:**
- Create: `vivarium_workbench/lib/config_to_composite_views.py`
- Modify: `vivarium_workbench/api/app.py` (add the route near `/api/composite-config-translate`)
- Test: `tests/test_config_to_composite_route.py`

**Interfaces:**
- Consumes: env-worker method `config_to_composite` (Task 1) via `get_pool().call`.
- Produces: `build_config_composite(ws_root, config) -> tuple[dict, int]`; route `POST /api/config-to-composite` body `{config_json: dict}` → `{state, schema, kind: "config-composite"}` (200) / `{error}` (400/422/501).

- [ ] **Step 1: Write the failing test** (mock the worker — no fork/translator needed)

```python
# tests/test_config_to_composite_route.py
from pathlib import Path
from vivarium_workbench.lib.config_to_composite_views import build_config_composite

class _FakePool:
    def __init__(self, ret): self._ret = ret
    def call(self, ws, method, params):
        assert method == "config_to_composite"
        assert params["config"] == {"add_processes": ["p"]}
        return self._ret

def test_build_returns_state_on_success(monkeypatch):
    import vivarium_workbench.lib.config_to_composite_views as m
    monkeypatch.setattr(m, "get_pool", lambda: _FakePool({"state": {"p": {"_type": "process"}}, "schema": {}}))
    body, status = build_config_composite(Path("/ws"), {"add_processes": ["p"]})
    assert status == 200 and body["kind"] == "config-composite"
    assert body["state"]["p"]["_type"] == "process"

def test_build_501_when_translator_unavailable(monkeypatch):
    import vivarium_workbench.lib.config_to_composite_views as m
    monkeypatch.setattr(m, "get_pool", lambda: _FakePool({"__unavailable__": True}))
    body, status = build_config_composite(Path("/ws"), {})
    assert status == 501 and "error" in body

def test_build_422_on_non_object_config():
    body, status = build_config_composite(Path("/ws"), ["not", "a", "dict"])
    assert status == 422
```

- [ ] **Step 2: Run — verify it fails** (`ModuleNotFoundError`).

Run: `PYTHONPATH=$PWD ~/code/sms-ecoli/.venv/bin/python -m pytest tests/test_config_to_composite_route.py -q`

- [ ] **Step 3: Implement the lib handler**

```python
# vivarium_workbench/lib/config_to_composite_views.py
"""POST /api/config-to-composite handler — vEcoli config JSON -> loom document.

Routes to the workspace env worker's ``config_to_composite`` method (the fork +
translator live on the workspace interpreter) and shapes the result into the
``{state, schema, kind}`` envelope the loom already renders."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from vivarium_workbench.lib.env_worker_pool import get_pool


def build_config_composite(ws_root: "Path | str", config: Any) -> "tuple[dict, int]":
    if not isinstance(config, dict):
        return {"error": "config must be a JSON object"}, 422
    try:
        res = get_pool().call(Path(ws_root), "config_to_composite", {"config": config})
    except Exception as e:  # noqa: BLE001 — worker unavailable, etc.
        return {"error": f"env worker unavailable: {e}"}, 503
    if not isinstance(res, dict):
        return {"error": "translator returned no document"}, 500
    if res.get("__unavailable__"):
        return {"error": "config→composite translator not available in this workspace"}, 501
    if res.get("__error__"):
        return {"error": res["__error__"]}, 400
    return {"state": res.get("state", {}), "schema": res.get("schema", {}),
            "kind": "config-composite"}, 200
```

- [ ] **Step 4: Add the route** in `api/app.py` (mirror the `composite-config-translate` route, ~line 1443):

```python
    @app.post("/api/config-to-composite", tags=["Composites"],
              summary="Translate a vEcoli config JSON into a loom-renderable composite document")
    def config_to_composite_route(req: dict, ws: Path = Depends(get_workspace)) -> JSONResponse:
        from vivarium_workbench.lib.config_to_composite_views import build_config_composite
        body, status = build_config_composite(ws, req.get("config_json"))
        return JSONResponse(status_code=status, content=body)
```

- [ ] **Step 5: Run tests + commit**

Run: `PYTHONPATH=$PWD ~/code/sms-ecoli/.venv/bin/python -m pytest tests/test_config_to_composite_route.py -q` → PASS.
```bash
git add vivarium_workbench/lib/config_to_composite_views.py vivarium_workbench/api/app.py tests/test_config_to_composite_route.py
git commit -m "feat(api): POST /api/config-to-composite route (config JSON -> loom document)"
```

---

### Task 3: loom "View as bigraph" control in the Config panel

Add a control that POSTs a loaded config and renders the returned document in the loom.

**Files:**
- Modify: `vivarium_workbench/loom/src/api.ts` (add `configToComposite(configJson)` fetch wrapper)
- Modify: `vivarium_workbench/loom/src/panels/ConfigPanel.tsx` (a "View as bigraph" button in the existing **External config** section, ~lines 206–259)
- Modify: `vivarium_workbench/loom/src/App.tsx` (thread a callback that calls the existing `setState` with the returned document — reuse the same setter `onApplied`/`composite:load` uses)
- Test: `vivarium_workbench/loom/src/__tests__/config-to-composite.test.ts` (vitest — mock `fetch`, assert the wrapper posts to `/api/config-to-composite` and returns `{state}`)

**Interfaces:**
- Consumes: `POST /api/config-to-composite` (Task 2).
- Produces: `configToComposite(configJson: Record<string, unknown>): Promise<{state: unknown; schema: unknown}>`; a button whose click renders the document via the loom's existing state setter.

**Design note — additive, not an Apply overload.** The existing **Apply** builds the target composite (`resolveComposite`). "View as bigraph" is a *distinct* action: it renders the config's declared structure, no build. Placing it in the External-config section (which already file-picks/pastes a config JSON) reuses that input. A later, deliberate UX pass can decide whether to fold this into a single Apply; do NOT overload Apply here.

- [ ] **Step 1: Write the failing vitest** for the api wrapper

```ts
// vivarium_workbench/loom/src/__tests__/config-to-composite.test.ts
import { describe, it, expect, vi } from 'vitest';
import { configToComposite } from '../api';

describe('configToComposite', () => {
  it('posts the config to /api/config-to-composite and returns the document', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ state: { p: { _type: 'process' } }, schema: {} }) }));
    vi.stubGlobal('fetch', fetchMock);
    const out = await configToComposite({ add_processes: ['p'] });
    expect(fetchMock).toHaveBeenCalledWith('/api/config-to-composite', expect.objectContaining({ method: 'POST' }));
    expect((out.state as any).p._type).toBe('process');
  });
});
```

- [ ] **Step 2: Run — verify it fails**

Run: `cd vivarium_workbench/loom && npm run test -- config-to-composite` (vitest). Expected: FAIL (`configToComposite` not exported).

- [ ] **Step 3: Implement `configToComposite` in `api.ts`** (mirror `translateExternalConfig`, api.ts:241)

```ts
export async function configToComposite(
  configJson: Record<string, unknown>,
): Promise<{ state: unknown; schema: unknown }> {
  const r = await fetch('/api/config-to-composite', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config_json: configJson }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data?.error || `config-to-composite failed (${r.status})`);
  return data as { state: unknown; schema: unknown };
}
```

- [ ] **Step 4: Wire the button** in `ConfigPanel.tsx`'s External-config block: a "View as bigraph" button next to the existing paste/upload + Apply. On click: parse the same `extConfigText` JSON (reuse the existing validation from `handleApplyExtConfig`), call `configToComposite(parsed)`, and hand the returned `state` to a new prop `props.onBigraphDocument(state)`. In `App.tsx`, pass `onBigraphDocument={(state) => setState(state)}` (the same setter `onApplied`/`composite:load` use, App.tsx:329/683/1970). Show `extConfigError` on throw.

- [ ] **Step 5: Run vitest + build the loom**

Run: `cd vivarium_workbench/loom && npm run test -- config-to-composite` → PASS. Then `npm run build` (writes `_dist/`).

- [ ] **Step 6: Commit**

```bash
git add vivarium_workbench/loom/src/api.ts vivarium_workbench/loom/src/panels/ConfigPanel.tsx vivarium_workbench/loom/src/App.tsx vivarium_workbench/loom/src/__tests__/config-to-composite.test.ts
git commit -m "feat(loom): View-as-bigraph control — render a config JSON as a composite document"
```

---

### Task 4: End-to-end verification (gated on translator availability)

**Precondition:** the workspace has `v2ecoli.library.config_to_composite` — i.e. **#605 merged + synced into sms-ecoli**, OR run the workbench with `PYTHONPATH` prepending `~/code/v2ecoli--config-to-composite`. If neither holds yet, STOP and report this task as BLOCKED-ON-#605 (do not fake it).

**Files:** none (verification only).

- [ ] **Step 1: restart the workbench** (sms-ecoli workspace, editable install picks up backend changes)

Run: `cd ~/code/sms-ecoli && .venv/bin/python -m viva_superpowers.workbench restart` and wait for `/api/workspace-manifest` → 200.

- [ ] **Step 2: POST a real config, confirm a document comes back**

Run (P = the workbench port from `.pbg/dashboard/dashboard-info`):
```bash
curl -s -m120 -X POST "http://localhost:$P/api/config-to-composite" -H 'Content-Type: application/json' \
  -d "$(V2E_VECOLI_DIR=/Users/eranagmon/code/vEcoli-private ~/code/sms-ecoli/.venv/bin/python -c 'import json,os; print(json.dumps({"config_json": json.load(open(os.path.join(os.environ["V2E_VECOLI_DIR"],"configs","final_mec.json")))}))')"
```
Expected: 200 with `{"state": {...process nodes...}, "kind": "config-composite"}`; the state has ≥5 process nodes incl. wired inputs.

- [ ] **Step 3: Render it in the loom** — open `http://localhost:$P/bigraph-loom/index.html`, load `final_mec.json` in the Config panel's External-config box, click **View as bigraph**, confirm the process stack renders as nodes with ports. Capture what you see (or a note that the backend 200 + a `?composite=<base64>` render confirms it if the UI can't be driven headlessly).

- [ ] **Step 4: PR** — `git push -u origin feat/config-as-bigraph-loom`; open a PR to `vivarium-collective/vivarium-workbench` against `main` (reference this plan + the Phase-1 PR #605). Do NOT merge.

---

## Follow-ons (not this plan)

- **Generic translator discovery:** replace the hardcoded `v2ecoli.library.config_to_composite` import with a workspace-declared hook (e.g. `workspace.yaml` names its config translator, or a `<pkg>.workbench_config_translator` convention), so the workbench names no specific package.
- **Apply unification:** a deliberate UX pass to decide whether "View as bigraph" folds into the main Apply, once both the build-composite and translate-config paths are live side by side.
- **Settle the editable install:** once this lands, repoint the sms-ecoli venv's `vivarium_workbench` editable at canonical `main` and drop the `--loom-config-overrides` worktree.
