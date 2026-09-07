# Composite Run Auto-Results Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a composite run auto-run its config-declared analyses and visualizations on completion — locally and on GovCloud — producing the standard results contract without creating a persisted study.

**Architecture:** Borrow the study flush's *results* stages via a shared driver (`run_declared_results`) fed by an **ephemeral** single-composite study spec built at completion and discarded. Wire it at both completion seams (local `composite_flush.run_flush`; GovCloud dispatch injection). Gate it with a default-on workspace `ui:` setting both seams read.

**Tech Stack:** Python (vivarium-workbench `lib/`), process-bigraph (`composite_generator`), v2ecoli analysis engine (`run_analyses`), pytest. Frontend: vanilla JS (`static/`).

**Spec:** `docs/superpowers/specs/2026-09-06-composite-run-auto-results-design.md`

## Global Constraints

- No AI attribution in commits or PRs (no `Co-Authored-By: Claude`, no "Generated with Claude Code"). Verbatim from the workspace rule.
- No persisted study: never write a `study.yaml` into `workspace/studies/`, never register the ephemeral spec, never surface it in the studies list.
- The ephemeral spec MUST be a strict subset of the study schema so the extracted driver accepts real and ephemeral specs without special-casing.
- `auto_results` defaults to `true`; both completion seams read it.
- Analyses run where the data is: locally in the env worker; on GovCloud server-side via `analysis_options` injection at dispatch (never on the landing machine).
- Cross-repo prerequisites tracked, NOT implemented here: process-bigraph decorator change (Task 1, ships in the pin the workbench uses); sms#233 registration reaching the dispatch path and v2ecoli #706 (all-zeros-lineage stub filter) for correct GovCloud ptools — those are `issue-166`'s PRs.

---

### Task 1: `GeneratorEntry.analyses` — carry composite-declared analyses (process-bigraph)

**Files:**
- Modify: `~/code/process-bigraph/process_bigraph/composite_generator.py` (GeneratorEntry dataclass ~L44; `composite_generator` decorator ~L177-187; `_entry_for` ~L71-85)
- Test: `~/code/process-bigraph/tests/test_composite_generator_analyses.py` (new)

**Interfaces:**
- Produces: `GeneratorEntry.analyses: list[dict]` (each entry a study-spec analysis dict `{name, params?}` / scale-grouped block as stored on `CompositeSpec.analyses`). Consumed by workbench Task 5.

Work in a process-bigraph worktree off origin/main (create via `git worktree add`), not the shared checkout.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_composite_generator_analyses.py
from process_bigraph.composite_generator import composite_generator, _REGISTRY

def test_decorator_carries_analyses():
    @composite_generator(
        name="probe_gen",
        analyses=[{"name": "ptools_rna_multigeneration"}],
        visualizations=[{"name": "v", "address": "local:X"}],
    )
    def build(core=None, **kw):
        return {}
    entry = _REGISTRY["probe_gen"]
    assert entry.analyses == [{"name": "ptools_rna_multigeneration"}]
    assert entry.visualizations  # unchanged path still works
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/process-bigraph--<slug> && python -m pytest tests/test_composite_generator_analyses.py -v`
Expected: FAIL — `composite_generator()` got an unexpected keyword `analyses` (or `entry.analyses` AttributeError).

- [ ] **Step 3: Add the `analyses` field to `GeneratorEntry`**

In the dataclass (mirror the existing `visualizations` field block ~L44), add:

```python
    # Canonical analyses that ship with this composite. Each entry is a
    # Study-spec analysis dict ({name, params?}) or a scale-grouped block,
    # matching CompositeSpec.analyses. Merged under a run's config-declared
    # analyses when a composite runs standalone (config wins).
    analyses: list[dict] = field(default_factory=list)
```

- [ ] **Step 4: Thread `analyses` through the decorator**

Add `analyses: list[dict] | None = None` to the `composite_generator(...)` signature (alongside `visualizations`), and pass it into the `process_bigraph.composite_spec` registration call the same way `visualizations` is passed (find the `_cs.register`/spec-construction call in the decorator body and add `analyses=analyses or []`). `CompositeSpec.analyses` already exists (`composite_spec.py:251`).

- [ ] **Step 5: Copy `analyses` in `_entry_for`**

In `_entry_for` (~L71-85) add `analyses=spec.analyses,` to the `GeneratorEntry(...)` constructor, next to `visualizations=spec.visualizations,`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_composite_generator_analyses.py -v`
Expected: PASS. Also run the existing sidecar test noted in `_RegistryView` (`_composite_generator_entry is entry`) to confirm identity caching still holds: `python -m pytest tests/ -k composite_generator -v`.

- [ ] **Step 7: Commit**

```bash
git add process_bigraph/composite_generator.py tests/test_composite_generator_analyses.py
git commit -m "feat(composite-generator): carry composite-declared analyses on GeneratorEntry"
```

---

### Task 2: `ephemeral_study_spec` builder (workbench)

**Files:**
- Create: `vivarium_workbench/lib/ephemeral_study.py`
- Test: `tests/lib/test_ephemeral_study.py` (new)

**Interfaces:**
- Consumes: composite defaults (`GeneratorEntry.analyses`/`.visualizations` from Task 1) and a config-declared block.
- Produces:
  - `merge_declarations(composite_defaults: dict, config_declared: dict) -> dict` → `{"analyses": [...], "visualizations": [...]}`; per-scale shallow-merge for analyses (config entries override composite entries of the same `name`), config-wins concat for visualizations (dedupe by `name`).
  - `ephemeral_study_spec(composite_ref: str, declared: dict) -> dict` → study-shaped dict with keys ONLY: `{"name", "baseline": {"composite": composite_ref}, "analyses", "visualizations", "_ephemeral": True}`. No `variants`, no `findings`, no `verdicts`, no `behavior_tests`.

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_ephemeral_study.py
from vivarium_workbench.lib.ephemeral_study import merge_declarations, ephemeral_study_spec

def test_merge_config_wins_by_name():
    composite = {"analyses": [{"name": "ptools_rna_multigeneration"}],
                 "visualizations": [{"name": "growth"}]}
    config = {"analyses": [{"name": "ptools_rna_multigeneration", "params": {"n_tp": 12}},
                           {"name": "ptools_rxns_multigeneration"}],
              "visualizations": [{"name": "titer"}]}
    m = merge_declarations(composite, config)
    rna = [a for a in m["analyses"] if a["name"] == "ptools_rna_multigeneration"]
    assert rna == [{"name": "ptools_rna_multigeneration", "params": {"n_tp": 12}}]  # config won
    assert {a["name"] for a in m["analyses"]} == {"ptools_rna_multigeneration", "ptools_rxns_multigeneration"}
    assert {v["name"] for v in m["visualizations"]} == {"growth", "titer"}

def test_ephemeral_spec_shape_is_study_subset():
    spec = ephemeral_study_spec("ecoli_baseline",
        {"analyses": [{"name": "ptools_rna_multigeneration"}], "visualizations": []})
    assert spec["baseline"]["composite"] == "ecoli_baseline"
    assert spec["_ephemeral"] is True
    assert "variants" not in spec and "verdicts" not in spec
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_ephemeral_study.py -v`
Expected: FAIL — module `ephemeral_study` does not exist.

- [ ] **Step 3: Implement `ephemeral_study.py`**

```python
# vivarium_workbench/lib/ephemeral_study.py
"""Build a transient single-composite study spec to drive the results driver.
Never persisted, never registered — the input struct for run_declared_results only."""
from __future__ import annotations


def _by_name(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in items or []:
        n = it.get("name")
        if n:
            out[n] = it
    return out


def merge_declarations(composite_defaults: dict, config_declared: dict) -> dict:
    """Config wins over composite defaults, keyed by analysis/viz name."""
    a = _by_name((composite_defaults or {}).get("analyses"))
    a.update(_by_name((config_declared or {}).get("analyses")))
    v = _by_name((composite_defaults or {}).get("visualizations"))
    v.update(_by_name((config_declared or {}).get("visualizations")))
    return {"analyses": list(a.values()), "visualizations": list(v.values())}


def ephemeral_study_spec(composite_ref: str, declared: dict) -> dict:
    return {
        "name": f"__ephemeral__{composite_ref}",
        "baseline": {"composite": composite_ref},
        "analyses": (declared or {}).get("analyses", []),
        "visualizations": (declared or {}).get("visualizations", []),
        "_ephemeral": True,
    }
```

Note: `merge_declarations` assumes a FLAT `analyses` list of `{name, params?}`. If the codebase's canonical shape is scale-grouped (`{single: [...], multigeneration: [...]}`), first normalise both inputs to a flat list before merging — check the shape stored on real `study.yaml` (`workspace/studies/cd2-antibiotic-cocktail/study.yaml:19`) and on `CompositeSpec.analyses`, and add a `_flatten_analyses` helper with its own unit test if they differ. `build_analysis_options` (Task 3) consumes a flat list of entries, so flatten before handing off regardless.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/lib/test_ephemeral_study.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/ephemeral_study.py tests/lib/test_ephemeral_study.py
git commit -m "feat(composite-results): ephemeral single-composite study spec builder"
```

---

### Task 3: `run_declared_results` shared driver (workbench)

**Files:**
- Create: `vivarium_workbench/lib/declared_results.py`
- Modify: `vivarium_workbench/lib/study_run_post.py` (reuse `build_analysis_options:184`, `run_study_analyses:251`, `render_study_visualizations:328`)
- Modify: `vivarium_workbench/lib/composite_flush.py` (reuse `render_report_card:245`)
- Test: `tests/lib/test_declared_results.py` (new)

**Interfaces:**
- Consumes: an ephemeral or real study spec (Task 2), the run's output store + resolved `sim_data`, `ws_root`, `run_id`.
- Produces: `run_declared_results(run_dir, spec, *, ws_root, run_id, store, sim_data, core) -> dict` returning `{"status": "OK"|"PARTIAL", "analyses": <path>, "report": <path>, "viz": [<names>], "errors": [...]}`; writes `analyses.json`, `report.html`, viz files under `run_dir`. Consumed by Tasks 4 and 5.

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_declared_results.py
import json
from pathlib import Path
from vivarium_workbench.lib import declared_results

def test_empty_spec_is_noop(tmp_path):
    spec = {"analyses": [], "visualizations": [], "baseline": {"composite": "c"}}
    out = declared_results.run_declared_results(
        tmp_path, spec, ws_root=tmp_path, run_id="r1", store=None, sim_data=None, core=None)
    assert out["status"] == "OK"
    assert not (tmp_path / "analyses.json").exists()  # nothing declared → nothing written

def test_unregistered_analysis_is_partial(tmp_path, monkeypatch):
    # build_analysis_options returns an error for an unknown name
    monkeypatch.setattr(declared_results, "build_analysis_options",
                        lambda entries, ws: ({}, [{"analysis": "nope", "error": "unknown"}]))
    spec = {"analyses": [{"name": "nope"}], "visualizations": [], "baseline": {"composite": "c"}}
    out = declared_results.run_declared_results(
        tmp_path, spec, ws_root=tmp_path, run_id="r1", store=None, sim_data=None, core=None)
    assert out["status"] == "PARTIAL"
    assert any(e["analysis"] == "nope" for e in out["errors"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_declared_results.py -v`
Expected: FAIL — module `declared_results` does not exist.

- [ ] **Step 3: Implement `declared_results.py`**

Compose the existing study stages. Read the exact call signatures of `run_study_analyses` (`study_run_post.py:251`), `render_study_visualizations` (`:328`), and `render_report_card` (`composite_flush.py:245`) and call them; the skeleton:

```python
# vivarium_workbench/lib/declared_results.py
"""Shared results driver: run declared analyses + viz + report card for a run.
Called by BOTH the study flush and the composite completion seam so studies and
composite runs emit an identical results contract."""
from __future__ import annotations
from pathlib import Path

from vivarium_workbench.lib.study_run_post import (
    build_analysis_options, run_study_analyses, render_study_visualizations,
)
from vivarium_workbench.lib.composite_flush import render_report_card


def run_declared_results(run_dir, spec, *, ws_root, run_id, store, sim_data, core) -> dict:
    analyses = spec.get("analyses") or []
    viz = spec.get("visualizations") or []
    if not analyses and not viz:
        return {"status": "OK", "analyses": None, "report": None, "viz": [], "errors": []}

    errors: list[dict] = []
    # 1. analyses (where the data is → env worker, same as study path)
    if analyses:
        options, opt_errors = build_analysis_options(analyses, Path(ws_root))
        errors.extend(opt_errors)
        # Mirror run_study_analyses' dispatch; it writes analyses.json under run_dir.
        ana_result = run_study_analyses(Path(run_dir), spec, run_id,
                                        store=store, sim_data=sim_data, core=core,
                                        analysis_options=options)  # adapt kwargs to the real signature
        errors.extend(ana_result.get("errors", []))
    # 2. visualizations (cheap; render on the run's output)
    viz_names = []
    if viz:
        viz_names = render_study_visualizations(ws_root, Path(run_dir), spec, spec.get("baseline", {}).get("composite"))
    # 3. report card
    report_path = render_report_card(req=None, viz_names=viz_names, analyses=analyses)  # adapt to real signature

    status = "PARTIAL" if errors else "OK"
    return {"status": status, "analyses": str(Path(run_dir) / "analyses.json"),
            "report": report_path, "viz": viz_names, "errors": errors}
```

The kwargs above are illustrative — read each callee's real signature and adapt. If `run_study_analyses` does not accept a precomputed `analysis_options`, pass `spec` (it calls `build_analysis_options` internally from `spec["analyses"]`) and drop the local `build_analysis_options` call, keeping only its error surfacing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/lib/test_declared_results.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/declared_results.py tests/lib/test_declared_results.py
git commit -m "feat(composite-results): shared run_declared_results driver (analyses+viz+report)"
```

---

### Task 4: Refactor the study flush to call `run_declared_results` (workbench)

**Files:**
- Modify: `vivarium_workbench/lib/study_runs.py` (`_run_post_run_flush:135`, stages at L143-146)
- Test: `tests/lib/test_study_flush_uses_driver.py` (new) + run the existing study-flush regression suite

**Interfaces:**
- Consumes: `run_declared_results` (Task 3).
- Produces: no new public signature; `_run_post_run_flush` delegates its analyses+viz+report stages to the driver, keeps stages 4-8 (outcomes sync, conclusion card, param capture, auto-evaluate, investigation roll-up) unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_study_flush_uses_driver.py
from unittest.mock import patch
from vivarium_workbench.lib import study_runs

def test_flush_delegates_results_to_driver(study_run_fixture):
    with patch("vivarium_workbench.lib.study_runs.run_declared_results") as drv:
        drv.return_value = {"status": "OK", "errors": [], "viz": [], "analyses": None, "report": None}
        study_runs._run_post_run_flush(**study_run_fixture)
        assert drv.called  # results stages go through the shared driver
```

(Use/extend the existing study-run test fixtures in `tests/lib/`; if none exists, build a minimal `study_run_fixture` from the args `_run_post_run_flush` takes — read its signature at `study_runs.py:135`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_study_flush_uses_driver.py -v`
Expected: FAIL — `run_declared_results` not imported/called by `study_runs`.

- [ ] **Step 3: Delegate the results stages**

In `_run_post_run_flush`, replace the inline calls to `render_study_visualizations` + `run_study_analyses` + report rendering (stages 1 + 3, L162/L256 per the map) with a single `run_declared_results(run_dir, spec, ...)` call, passing the real study `spec`. Leave stages 2 and 4-8 in place. Import at top.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/lib/test_study_flush_uses_driver.py -v && python -m pytest tests/ -k "study and (flush or post_run or analyses or viz)" -v`
Expected: PASS, and the existing study-flush regression tests stay green.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/study_runs.py tests/lib/test_study_flush_uses_driver.py
git commit -m "refactor(study-flush): route results stages through run_declared_results"
```

---

### Task 5: Local composite seam — `composite_flush` uses ephemeral spec + driver (workbench)

**Files:**
- Modify: `vivarium_workbench/lib/composite_flush.py` (`run_flush:267`, `_dispatch_analyses:219`, `_composite_analyses:162`)
- Test: `tests/lib/test_composite_flush_autoresults.py` (new)

**Interfaces:**
- Consumes: `ephemeral_study_spec` + `merge_declarations` (Task 2), `run_declared_results` (Task 3), `GeneratorEntry.analyses` (Task 1).
- Produces: `run_flush` now emits `analyses.json`/`report.html` for a composite whose declaration is non-empty.

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_composite_flush_autoresults.py
from unittest.mock import patch
from vivarium_workbench.lib import composite_flush

def test_run_flush_runs_declared_analyses(composite_run_fixture):
    # fixture: a completed composite run whose composite declares ptools_rna_multigeneration
    with patch("vivarium_workbench.lib.composite_flush.run_declared_results") as drv:
        drv.return_value = {"status": "OK", "errors": [], "viz": [], "analyses": "a.json", "report": "r.html"}
        composite_flush.run_flush(**composite_run_fixture)
        drv.assert_called_once()
        spec = drv.call_args.kwargs.get("spec") or drv.call_args.args[1]
        assert spec["_ephemeral"] is True
        assert any(a["name"] == "ptools_rna_multigeneration" for a in spec["analyses"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_composite_flush_autoresults.py -v`
Expected: FAIL — `run_flush` still calls `_dispatch_analyses`, `run_declared_results` not wired.

- [ ] **Step 3: Wire the ephemeral spec + driver into `run_flush`**

In `run_flush`, replace the `_dispatch_analyses(...)`/`_composite_analyses(spec_id, core)` block (L273) with:
1. Resolve the composite's declared defaults from the generator entry: `entry = core...registry[spec_id]` (mirror how `_composite_analyses` reaches the entry today) → `composite_defaults = {"analyses": entry.analyses, "visualizations": entry.visualizations}`.
2. Read the config-declared block off `req` (Task 6 adds it): `config_declared = getattr(req, "declared_results", {})`.
3. `declared = merge_declarations(composite_defaults, config_declared)`; `spec = ephemeral_study_spec(spec_id, declared)`.
4. `run_declared_results(run_dir, spec, ws_root=..., run_id=run_id, store=<db_file store>, sim_data=<resolved>, core=core)`.

Keep the existing `has_viz_refresh` study-sibling branch (L356) untouched — it only fires for real studies. Leave `_composite_analyses`/`_dispatch_analyses` in place if other callers use them; otherwise delete and note it in the commit.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/lib/test_composite_flush_autoresults.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/composite_flush.py tests/lib/test_composite_flush_autoresults.py
git commit -m "feat(composite-flush): auto-run declared analyses via ephemeral study spec"
```

---

### Task 6: Config declaration surface (workbench)

**Files:**
- Modify: the composite-run request model (`vivarium_workbench/lib/composite_test_run_views.py:54` request parsing; add `declared_results` to the request struct written at `:122`)
- Modify: run-config JSON schema (locate the composite run-config schema; add optional `analyses` + `visualizations`)
- Test: `tests/lib/test_run_config_declares_results.py` (new)

**Interfaces:**
- Produces: the run request carries `declared_results: {"analyses": [...], "visualizations": [...]}`, read by Task 5 (local) and Task 8 (remote).

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_run_config_declares_results.py
from vivarium_workbench.lib import composite_test_run_views as v

def test_config_analyses_reach_request():
    req = v.parse_composite_run_request({
        "composite": "ecoli_baseline",
        "analyses": [{"name": "ptools_rxns_multigeneration"}],
        "visualizations": [{"name": "titer"}],
    })
    assert req.declared_results["analyses"] == [{"name": "ptools_rxns_multigeneration"}]
    assert req.declared_results["visualizations"] == [{"name": "titer"}]
```

(Adapt to the real request parser name/shape — read `composite_test_run_views.py:54-122`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_run_config_declares_results.py -v`
Expected: FAIL — request has no `declared_results`.

- [ ] **Step 3: Add the declaration to the request + schema**

Parse optional `analyses`/`visualizations` from the incoming config into `req.declared_results` (default `{"analyses": [], "visualizations": []}`), and persist them into `.pbg/runs/<run_id>/request.json` (L122) so the detached runner and the remote dispatch both see them. Add the two optional keys to the run-config schema.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/lib/test_run_config_declares_results.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/composite_test_run_views.py tests/lib/test_run_config_declares_results.py
git commit -m "feat(composite-run): config-declared analyses & visualizations on the run request"
```

---

### Task 7: `auto_results` default-on workspace setting (workbench)

**Files:**
- Modify: `vivarium_workbench/lib/models.py:1133` (UI-settings model — add `auto_results: bool = True` next to `composite_view`)
- Modify: `vivarium_workbench/lib/system_info.py:145,155` (default + read from `workspace.yaml` `ui:` block)
- Modify: `vivarium_workbench/lib/deploy_config.py:4` (document the key)
- Modify: `vivarium_workbench/lib/composite_flush.py` (gate the Task-5 driver call on the setting) and the remote seam (Task 8)
- Test: `tests/lib/test_auto_results_setting.py` (new)

**Interfaces:**
- Produces: `auto_results` readable via the same accessor as `composite_view`; both seams skip `run_declared_results` when false.

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_auto_results_setting.py
from vivarium_workbench.lib import system_info

def test_auto_results_defaults_true(tmp_workspace):
    assert system_info.ui_settings(tmp_workspace).auto_results is True

def test_auto_results_respects_false(tmp_workspace_with_ui):
    # tmp_workspace_with_ui writes workspace.yaml ui: {auto_results: false}
    assert system_info.ui_settings(tmp_workspace_with_ui).auto_results is False
```

(Adapt accessor name to the real one used for `composite_view`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_auto_results_setting.py -v`
Expected: FAIL — `auto_results` unknown.

- [ ] **Step 3: Add the setting + default + gate**

Add `auto_results: bool = True` to the settings model (models.py:1133), default it in `system_info.py` (mirror `composite_view` at :145,155), document in `deploy_config.py`. In `composite_flush.run_flush`, wrap the Task-5 driver call in `if ui_settings(ws_root).auto_results:`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/lib/test_auto_results_setting.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/models.py vivarium_workbench/lib/system_info.py vivarium_workbench/lib/deploy_config.py vivarium_workbench/lib/composite_flush.py tests/lib/test_auto_results_setting.py
git commit -m "feat(settings): default-on auto_results workspace setting gating composite results"
```

---

### Task 8: GovCloud composite seam — inject analyses at dispatch, render viz at land (workbench)

**Files:**
- Modify: `vivarium_workbench/lib/run_runner.py:802` (`_execute_remote` — composite branch)
- Modify: `vivarium_workbench/lib/remote_run.py:94` (`run_remote` — pass `analysis_options` to the sms-api submit) and/or `remote_run_views.py:384` (reuse the study injection)
- Modify: `vivarium_workbench/lib/remote_run_landing.py:54` (`_fold_analyses`) — ensure composite land renders viz + report via `run_declared_results` on landed output
- Test: `tests/lib/test_remote_composite_results.py` (new; mock `SmsApiClient`)

**Interfaces:**
- Consumes: `req.declared_results` (Task 6), `build_analysis_options`, `ephemeral_study_spec`, `run_declared_results`, `auto_results` (Task 7).
- Produces: composite deployment submit includes `analysis_options`; land writes `analyses.json` + renders viz/report.

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_remote_composite_results.py
from unittest.mock import MagicMock, patch
from vivarium_workbench.lib import run_runner

def test_composite_remote_injects_analysis_options(remote_composite_req):
    remote_composite_req.declared_results = {"analyses": [{"name": "ptools_rxns_multigeneration"}], "visualizations": []}
    with patch("vivarium_workbench.lib.remote_run.SmsApiClient") as C:
        client = C.return_value
        client.run_simulation = MagicMock(return_value={"job": "j1"})
        run_runner._execute_remote(remote_composite_req)
        # analysis_options threaded into the submit (server-side analyses)
        kwargs = client.run_simulation.call_args.kwargs
        assert "multigeneration" in kwargs["analysis_options"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_remote_composite_results.py -v`
Expected: FAIL — composite remote path submits no `analysis_options`.

- [ ] **Step 3: Inject at dispatch + render at land**

In the composite branch of `_execute_remote` (guarded by `auto_results`): build `declared = merge_declarations(composite_defaults, req.declared_results)`, `spec = ephemeral_study_spec(req.composite, declared)`, `options, errs = build_analysis_options(spec["analyses"], ws_root)`, and pass `analysis_options=options` into `remote_run.run_remote`'s sms-api submit exactly as the study path does (`remote_run_views.py:384`). In `remote_run_landing._fold_analyses` (or right after land), if the landed run has `declared_results` viz, call `run_declared_results` in a viz-only mode (analyses already folded server-side) to render `report.html` + viz from the landed output.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/lib/test_remote_composite_results.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/run_runner.py vivarium_workbench/lib/remote_run.py vivarium_workbench/lib/remote_run_landing.py tests/lib/test_remote_composite_results.py
git commit -m "feat(remote): composite GovCloud runs inject declared analyses at dispatch, render viz at land"
```

---

### Task 9: Loom viewer default-on checkbox (workbench frontend)

**Files:**
- Modify: `vivarium_workbench/static/loom-embed.js:63` and `static/walkthrough.js:515,528` (read `auto_results` like `composite_view`; render a checkbox; POST changes to the settings endpoint)
- Modify: the UI-settings write endpoint if one is needed (mirror `/api/composite/loom-view` pattern, `app.py:1181`)
- Test: `tests/static/test_loom_auto_results_checkbox.*` (follow the repo's existing JS test convention; if none, a Python API test that the settings round-trip persists `auto_results`)

**Interfaces:**
- Consumes: the `auto_results` setting (Task 7).
- Produces: a default-on checkbox in the composite loom viewer that reflects and writes the workspace setting; it is a mirror, not the source of truth.

- [ ] **Step 1: Write the failing test**

If the repo has JS tests, assert the checkbox renders checked when `cfg.auto_results !== false`. Otherwise (Python side): assert the settings endpoint persists `auto_results` and `system_info.ui_settings` reads it back:

```python
# tests/lib/test_ui_settings_roundtrip.py
def test_auto_results_roundtrip(client, tmp_workspace):
    client.post("/api/ui-settings", json={"auto_results": False})
    from vivarium_workbench.lib import system_info
    assert system_info.ui_settings(tmp_workspace).auto_results is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_ui_settings_roundtrip.py -v`
Expected: FAIL — no settings write path for `auto_results` / checkbox absent.

- [ ] **Step 3: Add the checkbox + settings write**

In the loom embed chrome, render `<input type=checkbox>` bound to `cfg.auto_results` (default checked); on change POST to the UI-settings endpoint (add `auto_results` to its accepted keys, mirroring how `composite_view` persists). Read the value from the same config the frontend already reads `composite_view` from (`walkthrough.js:515`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/lib/test_ui_settings_roundtrip.py -v`
Expected: PASS. Manually verify the checkbox appears default-on in a composite card.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/static/loom-embed.js vivarium_workbench/static/walkthrough.js vivarium_workbench/api/app.py tests/lib/test_ui_settings_roundtrip.py
git commit -m "feat(loom): default-on auto-results checkbox mirroring the workspace setting"
```

---

## Self-Review

**Spec coverage:**
- Declaration + ephemeral spec → Tasks 1, 2, 6. ✓
- Shared results driver → Task 3; study path refactor → Task 4. ✓
- Local seam → Task 5; GovCloud seam → Task 8. ✓
- Default-on switch → Task 7; loom surface → Task 9. ✓
- Error handling (empty no-op, PARTIAL for unregistered, per-item failures) → Task 3 tests. ✓
- Non-goals (no persisted study) → Global Constraints + Task 2 shape test. ✓
- Cross-repo prerequisites (sms#233, v2ecoli #706, OOM) → Global Constraints; NOT implemented here (correctly out of scope; `issue-166` owns them).

**Placeholder scan:** Illustrative kwargs in Tasks 3/5/6/8 are explicitly flagged "read the real signature and adapt" with the exact anchor to read — a legitimate instruction, not a vague TODO. No "add error handling"/"write tests for the above" left unspecified.

**Type consistency:** `run_declared_results(run_dir, spec, *, ws_root, run_id, store, sim_data, core)` used identically in Tasks 3, 4, 5, 8. `merge_declarations`/`ephemeral_study_spec` signatures consistent Tasks 2→5, 8. `auto_results` name consistent Tasks 7→9. `declared_results` request field consistent Tasks 6→5, 8.

**Note for executor:** the OOM mitigation (one analysis per worker invocation for the ptools family) is a driver-level concern — if the env-worker `run_study_analyses` runs all analyses in one process and OOMs on a full hive, add a per-scale/per-name loop in `run_declared_results` (Task 3) with its own test. Deferred as a hardening follow-up unless it blocks a real run.
