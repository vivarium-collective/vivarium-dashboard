# Investigation Execution Hook — Phase A (workbench core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Make `prepare_investigation` run member studies in prerequisite (topological) order and run investigation-level `analyses:` after all studies complete — both backward-compatible (no-op / additive) for existing investigations.

**Architecture:** Two localized additions to `lib/prepare_investigation.py` + one small pure helper. (A1) A stable topological sort over each study's `pipeline_gate.prerequisites` edges — declared order is the tie-break, so a no-prerequisite investigation is byte-identical to today by construction. (A2) After the study loop, run any `analyses:` the `investigation.yaml` declares, reading member studies' outputs — additive, fires only when declared. Per-study `analyses:` already run today inside the study-run post-flush (`study_runs.py:126`), so they are out of scope.

**Tech Stack:** Python, FastAPI workbench, `graphlib`-style stable toposort (hand-rolled for declared-order stability), pytest against a real server subprocess (`dashboard_client` fixture) + hermetic unit tests.

## Global Constraints
- Worktree `~/code/vivarium-workbench--exec-hook`, branch `exec-hook` (off `origin/main`). Commit by explicit path (never `git add -A`).
- **Backward-compatibility is the gate.** A1 must be a provable no-op for any investigation with no `pipeline_gate.prerequisites` edges: declared member order preserved exactly. A2 must be a no-op for any investigation with no `analyses:` key.
- No new dependency on the deleted `server.py`; add logic in `lib/`, routes (if any) in `api/app.py`.
- The `analyses:` declaration key reuses the existing Analysis-framework naming — `analyses: [{name, params}]` — not a second concept.
- Adding `analyses:` to `investigation.yaml` is schema-safe (no jsonschema on that spec; pydantic models are `extra="allow"`; `StudyDetail.analyses` already exists) — no validator changes needed.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Task 1 — Stable prerequisite topological-order helper (pure)

**Files:**
- Create: `vivarium_workbench/lib/investigation_order.py`
- Test: `tests/test_investigation_order.py`

**Interfaces:**
- Produces: `prerequisite_order(declared: list[str], prereqs_of: Callable[[str], list[str]]) -> list[str]` — returns `declared` reordered so every slug follows all its prerequisites that are also in `declared` (prerequisites outside `declared` are ignored — they are external/already-run and impose no intra-investigation constraint). Stable: among ready nodes, the one earliest in `declared` wins, so **no edges → returns `declared` unchanged**. Raises `CycleError(cycle_slugs)` naming the unresolved slugs on a cycle.
- Consumes (by Task 2): `normalize_dag_edges(spec)` from `lib/investigations.py` (returns `[{study, condition}]`) to build `prereqs_of`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_investigation_order.py
import pytest
from vivarium_workbench.lib.investigation_order import prerequisite_order, CycleError

def _prereqs(mapping):
    return lambda slug: mapping.get(slug, [])

def test_no_edges_preserves_declared_order():
    declared = ["a", "b", "c"]
    assert prerequisite_order(declared, _prereqs({})) == ["a", "b", "c"]

def test_prerequisite_runs_before_dependent():
    declared = ["configs", "parca"]           # declared out of order
    order = prerequisite_order(declared, _prereqs({"configs": ["parca"]}))
    assert order.index("parca") < order.index("configs")

def test_stable_among_independent_after_dependency():
    # parca first (a prereq of both), then the two configs in declared order
    declared = ["cfgA", "cfgB", "parca"]
    order = prerequisite_order(
        declared, _prereqs({"cfgA": ["parca"], "cfgB": ["parca"]}))
    assert order == ["parca", "cfgA", "cfgB"]

def test_external_prerequisite_ignored():
    # 'seed' is not a member of this investigation -> imposes no constraint
    declared = ["a", "b"]
    assert prerequisite_order(declared, _prereqs({"a": ["seed"]})) == ["a", "b"]

def test_cycle_raises_naming_slugs():
    declared = ["x", "y"]
    with pytest.raises(CycleError) as exc:
        prerequisite_order(declared, _prereqs({"x": ["y"], "y": ["x"]}))
    assert {"x", "y"} <= set(exc.value.slugs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_investigation_order.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the helper**

```python
# vivarium_workbench/lib/investigation_order.py
"""Stable topological ordering of investigation member studies by their
``pipeline_gate.prerequisites`` edges. Declared order is the tie-break, so an
investigation with no prerequisites is returned unchanged (backward-compatible
with the historical flat declared-order loop in prepare_investigation)."""
from __future__ import annotations
from typing import Callable


class CycleError(Exception):
    """A prerequisite cycle among member studies."""
    def __init__(self, slugs):
        self.slugs = list(slugs)
        super().__init__(f"prerequisite cycle among studies: {sorted(self.slugs)}")


def prerequisite_order(declared: list[str],
                       prereqs_of: Callable[[str], list[str]]) -> list[str]:
    members = set(declared)
    # Only intra-investigation prerequisites constrain ordering.
    unmet = {s: [p for p in prereqs_of(s) if p in members and p != s]
             for s in declared}
    done: list[str] = []
    done_set: set[str] = set()
    remaining = list(declared)
    while remaining:
        # First slug in declared order whose prerequisites are all satisfied.
        pick = next((s for s in remaining
                     if all(p in done_set for p in unmet[s])), None)
        if pick is None:
            raise CycleError(remaining)
        done.append(pick)
        done_set.add(pick)
        remaining.remove(pick)
    return done
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_investigation_order.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/investigation_order.py tests/test_investigation_order.py
git commit -m "feat: stable prerequisite topological-order helper for investigations"
```

---

## Task 2 — Run studies in prerequisite order in `prepare_investigation`

**Files:**
- Modify: `vivarium_workbench/lib/prepare_investigation.py` (the `studies` list build at `:185` and/or the loop at `:206`)
- Test: `tests/test_prepare_investigation_order.py`

**Interfaces:**
- Consumes: `prerequisite_order` (Task 1); `normalize_dag_edges` (`lib/investigations.py`); the existing `_study_slugs(ws, inv)` (declared order) and `prepare_study`.
- Produces: `prepare_investigation` runs `prepare_study` over the prerequisite-ordered slugs; `result["studies"]` order reflects execution order. Behavior for no-prerequisite investigations is unchanged.

**Note for implementer:** `prepare_study` POSTs to a live dashboard (`dash`) — the ordering test must NOT require engine runs. Assert ordering by patching `prepare_study` to record the slug sequence (monkeypatch `prepare_investigation.prepare_study`), and drive `prepare_investigation` against a tmp workspace of study.yaml stubs. Load each member spec via `WorkspacePaths.load(ws).studies / slug / "study.yaml"` (`yaml.safe_load`) to build `prereqs_of`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prepare_investigation_order.py
import yaml
from pathlib import Path
import vivarium_workbench.lib.prepare_investigation as pi

def _mk(ws: Path, inv: str, members: list[str], specs: dict[str, dict]):
    (ws / "investigations" / inv).mkdir(parents=True)
    (ws / "investigations" / inv / "investigation.yaml").write_text(
        yaml.safe_dump({"name": inv, "studies": members}))
    for slug, spec in specs.items():
        d = ws / "studies" / slug
        d.mkdir(parents=True)
        (d / "study.yaml").write_text(yaml.safe_dump(spec))

def _record(monkeypatch):
    seq = []
    monkeypatch.setattr(pi, "prepare_study",
                        lambda ws, slug, *a, **k: seq.append(slug) or {"study": slug})
    return seq

def test_no_prereq_preserves_declared_order(tmp_path, monkeypatch):
    _mk(tmp_path, "inv", ["a", "b", "c"],
        {"a": {}, "b": {}, "c": {}})
    seq = _record(monkeypatch)
    pi.prepare_investigation(tmp_path, investigation="inv", render_only=True)
    assert seq == ["a", "b", "c"]

def test_prereq_runs_before_dependent(tmp_path, monkeypatch):
    # 'cfg' declares parca as a prerequisite but is declared FIRST
    _mk(tmp_path, "inv", ["cfg", "parca"], {
        "cfg": {"pipeline_gate": {"prerequisites": [{"study": "parca", "relation": "leads-to"}]}},
        "parca": {},
    })
    seq = _record(monkeypatch)
    pi.prepare_investigation(tmp_path, investigation="inv", render_only=True)
    assert seq.index("parca") < seq.index("cfg")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prepare_investigation_order.py -v`
Expected: FAIL (second test — declared order runs `cfg` before `parca`).

- [ ] **Step 3: Implement the reordering**

In `prepare_investigation.py`, after `studies = [study] if study else _study_slugs(ws, inv)` (`:185`), reorder when running the full investigation (not a single `--study`):

```python
from vivarium_workbench.lib.investigation_order import prerequisite_order, CycleError
from vivarium_workbench.lib.investigations import normalize_dag_edges

def _study_prereqs(ws, slug):
    p = WorkspacePaths.load(ws).studies / slug / "study.yaml"
    if not p.exists():
        return []
    spec = yaml.safe_load(p.read_text()) or {}
    return [e["study"] for e in normalize_dag_edges(spec) if e.get("study")]

# after `studies = ...`:
if study is None:
    studies = prerequisite_order(studies, lambda s: _study_prereqs(ws, s))
```

(Keep imports at module top per file convention. On `CycleError`, let it propagate — fail loud, per spec.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prepare_investigation_order.py -v`
Expected: PASS (both).

- [ ] **Step 5: Regression — the existing suite is unchanged**

Run: `pytest tests/test_rerun_run.py tests/test_api_rerun.py tests/test_investigation_graph_views.py -v`
Expected: PASS (no behavior change for `inputs[].from`-based rerun or graph views).

- [ ] **Step 6: Commit**

```bash
git add vivarium_workbench/lib/prepare_investigation.py tests/test_prepare_investigation_order.py
git commit -m "feat: prepare_investigation runs studies in prerequisite order"
```

---

## Task 3 — Investigation-level `analyses:` phase (post-loop)

**Files:**
- Create: `vivarium_workbench/lib/investigation_analyses.py`
- Modify: `vivarium_workbench/lib/prepare_investigation.py` (after the study loop at `:206`, before the return at `:227`)
- Test: `tests/test_investigation_analyses.py`

**Interfaces:**
- Produces: `run_investigation_analyses(ws_root, inv_slug, spec, study_results) -> (written_files: list[str], errors: list[dict])` — reads `spec.get("analyses")` on the `investigation.yaml`; for each `{name, params}` entry, dispatches the named Analysis (via the same env-worker capability the per-study path uses, `run_study_analyses`'s `get_pool().call(ws_root, "run_study_analyses", {...})`, scoped to the investigation report dir) and writes each output under `WorkspacePaths.load(ws).report_dir(inv_slug)`. Never raises — collects errors like `study_run_post.run_study_analyses`. Returns `([], [])` when no `analyses:` key.
- Consumes: `study_results` (the per-study dicts from the loop) so an investigation-level analysis (e.g. the cross-config matrix) can locate each member study's outputs.
- Integration into `prepare_investigation`: after the loop, call it and add `{"analysis_files", "analysis_errors"}` to the returned dict.

**Note for implementer:** model the dispatch on `lib/study_run_post.run_study_analyses` (`:183-239`) — same `get_pool().call(...)` env-worker capability, but scoped to the investigation report dir rather than a study's parquet sweep. The exact params dict the worker expects is whatever `run_study_analyses` passes at `study_run_post.py:230`; read that and mirror its shape, substituting the investigation report dir + the investigation-level entries. Do NOT invent a new worker capability in this task — reuse `run_study_analyses`. If the worker capability cannot accept an investigation-scoped call without a study parquet, stop and report BLOCKED with the specific mismatch (this is the one integration risk).

- [ ] **Step 1: Write the failing test (no-op + wiring)**

```python
# tests/test_investigation_analyses.py
import yaml
from pathlib import Path
from vivarium_workbench.lib.investigation_analyses import run_investigation_analyses

def test_no_analyses_key_is_noop(tmp_path):
    (tmp_path / "investigations" / "inv").mkdir(parents=True)
    files, errors = run_investigation_analyses(tmp_path, "inv", {"name": "inv"}, [])
    assert files == [] and errors == []

def test_declared_analysis_is_dispatched(tmp_path, monkeypatch):
    import vivarium_workbench.lib.investigation_analyses as ia
    calls = []
    monkeypatch.setattr(ia, "_dispatch_analysis",
                        lambda ws, inv, entry, results: calls.append(entry["name"]) or ["out.html"])
    spec = {"name": "inv", "analyses": [{"name": "comparison_matrix", "params": {}}]}
    (tmp_path / "investigations" / "inv").mkdir(parents=True)
    files, errors = run_investigation_analyses(tmp_path, "inv", spec, [])
    assert calls == ["comparison_matrix"] and files == ["out.html"] and errors == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_investigation_analyses.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `investigation_analyses.py`**

Structure (fill `_dispatch_analysis` per the note above — mirror `study_run_post.run_study_analyses`'s `get_pool().call`):

```python
# vivarium_workbench/lib/investigation_analyses.py
"""Investigation-level post-sim analyses: after all member studies run, execute
any `analyses:` the investigation.yaml declares (e.g. a cross-config matrix that
aggregates each member study's verdict). Additive — a no-op when unset."""
from __future__ import annotations
from pathlib import Path
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _dispatch_analysis(ws_root, inv_slug, entry, study_results) -> list[str]:
    # Mirror study_run_post.run_study_analyses: get_pool().call(ws_root,
    # "run_study_analyses", {...}) scoped to the investigation report dir.
    # Returns the list of written output paths for this entry.
    ...  # implement per the note; reuse the existing worker capability


def run_investigation_analyses(ws_root, inv_slug, spec, study_results):
    entries = spec.get("analyses") or []
    written, errors = [], []
    for entry in entries:
        try:
            written.extend(_dispatch_analysis(ws_root, inv_slug, entry, study_results))
        except Exception as exc:
            errors.append({"analysis": entry.get("name"),
                           "error": f"{type(exc).__name__}: {exc}"})
    return written, errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_investigation_analyses.py -v`
Expected: PASS (both).

- [ ] **Step 5: Wire into `prepare_investigation`**

After the study loop (`:206`), before building the return dict (`:227`):

```python
from vivarium_workbench.lib.investigation_analyses import run_investigation_analyses
# `inv_spec` = the loaded investigation.yaml dict (already loaded for _study_slugs;
# load it once and reuse). `results` = the per-study list.
analysis_files, analysis_errors = run_investigation_analyses(ws, inv, inv_spec, results)
```

Add `"analysis_files": analysis_files, "analysis_errors": analysis_errors` to the returned dict. If `inv_spec` is not already in scope, load it via `WorkspacePaths.load(ws).investigations / inv / "investigation.yaml"`.

- [ ] **Step 6: Run the no-op regression**

Run: `pytest tests/test_prepare_investigation_order.py -v`
Expected: PASS — the fixtures declare no `analyses:`, so the returned dict gains empty `analysis_files`/`analysis_errors` and ordering is unaffected.

- [ ] **Step 7: Commit**

```bash
git add vivarium_workbench/lib/investigation_analyses.py vivarium_workbench/lib/prepare_investigation.py tests/test_investigation_analyses.py
git commit -m "feat: investigation-level analyses phase after study loop"
```

---

## Task 4 — Golden backward-compat run (real fixture, no engine)

**Files:**
- Test: `tests/test_prepare_investigation_golden.py`

**Interfaces:**
- Consumes: an on-disk multi-study fixture with NO prerequisites and NO `analyses:` (e.g. `tests/_fixtures/ws_federation_collision` — 2 studies — or a purpose-built 3-study fixture under `tests/_fixtures/`). Asserts `prepare_investigation` visits studies in the exact declared order and returns empty analysis lists — the byte-identical-behavior proof the spec's gate requires.

- [ ] **Step 1: Write the golden test**

```python
# tests/test_prepare_investigation_golden.py
import vivarium_workbench.lib.prepare_investigation as pi
from vivarium_workbench.lib.investigation_members import investigation_member_slugs
from vivarium_workbench.lib.workspace_paths import WorkspacePaths
import yaml

FIXTURE = "tests/_fixtures/ws_federation_collision"  # or the chosen no-prereq fixture

def test_declared_order_and_no_analyses(tmp_path, monkeypatch):
    # copy fixture to tmp so we never mutate it
    import shutil
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE, ws)
    inv = "local_inv"  # confirm the fixture's investigation slug
    spec = yaml.safe_load(
        (WorkspacePaths.load(ws).investigations / inv / "investigation.yaml").read_text())
    declared = investigation_member_slugs(spec)
    seq = []
    monkeypatch.setattr(pi, "prepare_study",
                        lambda ws_, slug, *a, **k: seq.append(slug) or {"study": slug})
    result = pi.prepare_investigation(ws, investigation=inv, render_only=True)
    assert seq == [s if isinstance(s, str) else (s.get("study") or s.get("name")) for s in declared]
    assert result["analysis_files"] == [] and result["analysis_errors"] == []
```

- [ ] **Step 2: Run it**

Run: `pytest tests/test_prepare_investigation_golden.py -v`
Expected: PASS. If the fixture slug/members differ, adjust `inv`/`FIXTURE` to a real no-prereq multi-study fixture (list `tests/_fixtures/*/investigations/*/investigation.yaml` to pick one); if none exists, create a minimal 3-study one under `tests/_fixtures/ws_exec_hook_golden/`.

- [ ] **Step 3: Full non-sim suite**

Run: `pytest -q` (classify any failure against the base branch — pre-existing failures are not ours).
Expected: no NEW failures introduced by this branch.

- [ ] **Step 4: Commit**

```bash
git add tests/test_prepare_investigation_golden.py
git commit -m "test: golden backward-compat order + no-analyses for prepare_investigation"
```

---

## Self-Review Notes
- **Coverage:** spec A1 (topological order) → Tasks 1+2; A2 (post-sim analyses) → Task 3 (investigation-level only; per-study already runs via `study_runs.py:126`, noted as out of scope); the "suite + golden run" backward-compat gate → Task 2 Step 5 + Task 4.
- **No-op proof:** Task 1's stable sort returns `declared` unchanged with no edges (`test_no_edges_preserves_declared_order`); Task 4 proves it end-to-end on a real fixture. A2 returns `([], [])` with no `analyses:` key (`test_no_analyses_key_is_noop`).
- **Type consistency:** `prerequisite_order(declared, prereqs_of)` and `run_investigation_analyses(ws_root, inv_slug, spec, study_results) -> (files, errors)` are used with those exact signatures in Tasks 2 and 3.
- **Integration risk (flagged in Task 3):** whether the `run_study_analyses` env-worker capability accepts an investigation-scoped call without a study parquet is the one unknown — the task instructs BLOCKED-with-specifics rather than inventing a new capability. Phase B (v2ecoli comparison_matrix as an investigation-level analysis) is the first real consumer and will exercise this end-to-end.
- **Phase B (separate plan, in v2ecoli):** re-model the comparison materializer to native single-study-per-config (baseline=candidate, variant=reference) + `comparative_visualizations` + per-study `analyses:[comparison_cards]` + investigation-level `analyses:[comparison_matrix]` + parca prerequisite; resolve the `<run>::comparison_cards` token via this investigation-level phase; gated e2e. Blocked on Phase A landing.
