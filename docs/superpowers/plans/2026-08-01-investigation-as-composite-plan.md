# Investigation as a Composite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Run an investigation as a process-bigraph Composite — studies as `StudyStep`s, `pipeline_gate.prerequisites` as store wiring, so the scheduler orders execution; analysis steps wired to study results; both runners delegate to it.

**Architecture:** A `StudyStep` (process-bigraph `Step`) dispatches each study run to the persistent JSON-RPC worker (`run_study`) and blocks; an `InvestigationComposite` generator compiles `investigation.yaml` + prerequisites into wired steps; `run_investigation`/`prepare_investigation` build and run that composite in-process (server runs in the workspace venv, which has `process_bigraph`). Ordering + cross-study analysis data-flow both come from the graph.

**Tech Stack:** `process_bigraph` (`Composite`, `Step`, `scheduling.py` engine), `bigraph_schema.allocate_core`, the workbench env-worker pool (`get_pool().call`), pytest.

## Global Constraints
- Worktree `~/code/vivarium-workbench--inv-composite`, branch `inv-composite` (off `origin/main`). Commit by explicit path (never `git add -A`).
- **Test env:** the workbench dev venv lacks `process_bigraph`. Run all tests that touch the engine with the v2ecoli venv + this worktree on PYTHONPATH:
  `PYTHONPATH=/Users/eranagmon/code/vivarium-workbench--inv-composite /Users/eranagmon/code/v2ecoli--compare-generalize/.venv/bin/python -m pytest <file> -v`
  Verify the branch code wins: `... python -c "import vivarium_workbench, process_bigraph; print(vivarium_workbench.__file__)"` must show the `--inv-composite` path.
- **Model each study as a `Step`, not a `Process`** (temporal misclassification → clock never advances; the metabolism_redux tick-2 trap).
- Keep prerequisite input ports in the default trigger set (do NOT list them in a `triggers()` silent-set) — silent inputs create no ordering edge.
- Design reference: `docs/superpowers/specs/2026-08-01-investigation-as-composite-design.md`. Engine facts: `process_bigraph/scheduling.py:307` (`build_step_network`), `:479` (`determine_steps`); `composite.py:2253` (`run_steps`), `:2747` (`process_update`), `:567/774` (Step vs Process); ParCa precedent `v2ecoli/processes/parca/composite.py`.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Task 1 — Walking skeleton: StudyStep + scheduler ordering on the real engine

**De-risks the whole plan.** Prove that a `Step` whose input is wired to another step's output makes the engine order them, using a trivial StudyStep whose `update()` just records a marker (no real run yet).

**Files:**
- Create: `vivarium_workbench/lib/investigation_steps.py`
- Test: `tests/test_investigation_steps_skeleton.py`

**Interfaces:**
- Produces: `class StudyStep(process_bigraph.Step)` with `config_schema = {"workspace": "string", "study_slug": "string", "prereqs": "list[string]"}`; `inputs()` returns one port per prereq (`{f"prereq_{slug}": "any"}`) plus nothing else; `outputs()` returns `{"result": "any"}`; `update(state)` returns `{"result": {"study": self.config["study_slug"], "ran": True}}`. A module-level hook `_run_study_hook` (default = the trivial marker) that Task 3 replaces with the real worker dispatch — so this task's behavior is pure and testable.

- [ ] **Step 1: Write the failing ordering test**

```python
# tests/test_investigation_steps_skeleton.py
from bigraph_schema import allocate_core
from process_bigraph import Composite
from vivarium_workbench.lib.investigation_steps import StudyStep

def _core():
    core = allocate_core()
    core.register_process("StudyStep", StudyStep)
    return core

def test_prereq_wiring_orders_two_steps():
    # B depends on A: B's prereq input wired to the store A's result writes.
    core = _core()
    state = {
        "A_result": {"_type": "any"},
        "B_result": {"_type": "any"},
        "A": {"_type": "step", "address": "local:StudyStep",
              "config": {"workspace": "/ws", "study_slug": "A", "prereqs": []},
              "inputs": {}, "outputs": {"result": ["A_result"]}},
        "B": {"_type": "step", "address": "local:StudyStep",
              "config": {"workspace": "/ws", "study_slug": "B", "prereqs": ["A"]},
              "inputs": {"prereq_A": ["A_result"]}, "outputs": {"result": ["B_result"]}},
    }
    order = []
    import vivarium_workbench.lib.investigation_steps as m
    m._RUN_ORDER = order  # skeleton records order via the hook
    Composite({"state": state, "run_steps_on_init": True}, core=core)
    assert order == ["A", "B"]
```

- [ ] **Step 2: Run it — verify it fails** (module missing).
  `PYTHONPATH=... /Users/eranagmon/code/v2ecoli--compare-generalize/.venv/bin/python -m pytest tests/test_investigation_steps_skeleton.py -v`

- [ ] **Step 3: Implement the skeleton `StudyStep`**

```python
# vivarium_workbench/lib/investigation_steps.py
"""Investigation-as-composite building blocks. A StudyStep is a process-bigraph
Step wrapping one study; prerequisite edges are expressed as input wires so the
engine orders StudySteps by dependency (see the design spec)."""
from __future__ import annotations
import process_bigraph

_RUN_ORDER: list | None = None  # skeleton test hook; None in production


def _run_study_hook(workspace: str, study_slug: str) -> dict:
    """Default (skeleton) run: record order + return a marker. Task 3 replaces
    the body with the real worker dispatch."""
    if _RUN_ORDER is not None:
        _RUN_ORDER.append(study_slug)
    return {"study": study_slug, "ran": True}


class StudyStep(process_bigraph.Step):
    config_schema = {
        "workspace": "string",
        "study_slug": "string",
        "prereqs": {"_type": "list[string]", "_default": []},
    }

    def inputs(self):
        return {f"prereq_{p}": "any" for p in self.config.get("prereqs", [])}

    def outputs(self):
        return {"result": "any"}

    def update(self, state=None):
        result = _run_study_hook(self.config["workspace"], self.config["study_slug"])
        return {"result": result}
```

- [ ] **Step 4: Run it — verify PASS** (order == ["A", "B"]). If the engine's step-doc shape differs (address/inputs/outputs keys), adapt the test's `state` to the real process-bigraph step-document schema — read `process_bigraph/run_step.py` and ParCa's `composite.py` `_wires()` for the exact shape, and note the adaptation. The load-bearing assertion (A before B via wiring) must hold.

- [ ] **Step 5: Add the no-prereq declared-order case**

```python
def test_no_prereq_priority_preserves_declared_order():
    core = _core()
    order = []
    import vivarium_workbench.lib.investigation_steps as m
    m._RUN_ORDER = order
    # three independent steps; priority set by declared index → serial declared order
    state = {}
    for i, slug in enumerate(["x", "y", "z"]):
        state[f"{slug}_result"] = {"_type": "any"}
        state[slug] = {"_type": "step", "address": "local:StudyStep",
                       "config": {"workspace": "/ws", "study_slug": slug, "prereqs": []},
                       "_priority": -i,  # confirm the engine's priority key/sign vs scheduling.py
                       "inputs": {}, "outputs": {"result": [f"{slug}_result"]}}
    Composite({"state": state, "run_steps_on_init": True}, core=core)
    assert order == ["x", "y", "z"]
```

Read `scheduling.py:503-510` for the exact priority key name + tie-break direction; fix the `_priority` field accordingly so declared order is preserved. If the engine cannot deterministically order independent steps by a priority field, record the finding — declared-order preservation for no-prereq investigations may need the generator to add explicit serial wiring instead (fallback noted in the design).

- [ ] **Step 6: Commit** (`investigation_steps.py`, `tests/test_investigation_steps_skeleton.py`).

---

## Task 2 — `run_study` worker capability

**Files:**
- Modify: `vivarium_workbench/env_worker.py` (`_CAPABILITIES` ~:87, dispatch ~:2360, new `_run_study`)
- Test: `tests/test_run_study_capability.py`

**Interfaces:**
- Produces: worker method `run_study(params) -> {"run_refs": [...], "verdict": {...}, "errors": [...]}`. `params = {"workspace", "study_slug", "run_spec"?}`. Runs the study's baseline (+ any variants named in `run_spec`) to completion **synchronously** (blocking), reusing the composite/params/sim_name resolution of `lib/study_runs.run_study_baseline`/`run_study_variant` but awaiting the run rather than detaching; reads the resulting run refs from `studies/<slug>/runs.db`. Never raises.
- Consumes (by Task 3): the StudyStep calls this via `get_pool().call(ws_root, "run_study", params)`.

**Note for implementer:** read `lib/study_runs.py` (`run_study_baseline` :328, `run_study_variant` :418, `_launch_run_and_flush` :168, `launch_into_study` :241) and `lib/composite_subprocess.py` (how a run is launched + how completion is detected in `runs.db`, sim_name written at :591). The existing path DETACHES; here you must await completion. Prefer reusing the resolution helpers and running the composite subprocess to completion inline (block on the subprocess), then harvest the run row. If awaiting a detached run cleanly is not feasible without larger changes, report BLOCKED with the specific `study_runs`/`composite_subprocess` seam that forces detachment.

- [ ] **Step 1: Write the failing test** — hermetic: monkeypatch the study-run resolution + subprocess launch to a fake that writes a fake `runs.db` row, assert `_run_study` returns the run ref + verdict shape and records errors instead of raising. (Test the capability's contract + await/harvest logic, not a real sim.)
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement `_run_study` + register in `_CAPABILITIES` + dispatch branch.**
- [ ] **Step 4: Run → pass** (workbench dev venv is fine — hermetic, no process_bigraph).
- [ ] **Step 5: Commit** (`env_worker.py`, `tests/test_run_study_capability.py`).

---

## Task 3 — Wire `StudyStep.update()` to the worker

**Files:**
- Modify: `vivarium_workbench/lib/investigation_steps.py` (`_run_study_hook` body)
- Test: `tests/test_study_step_dispatch.py`

**Interfaces:**
- `_run_study_hook(workspace, study_slug)` now calls `get_pool().call(workspace, "run_study", {"workspace": workspace, "study_slug": study_slug})` (import `get_pool` from the same module `study_run_post`/`composite_flush` use) and returns its reply. The skeleton `_RUN_ORDER` hook remains usable in tests via monkeypatch.

- [ ] **Step 1: Write the failing test** — monkeypatch `get_pool().call` to a recorder returning `{"run_refs": ["r1"], "verdict": {"overall": "pass"}}`; build a 2-step composite (A→B) on the real engine; assert both dispatched in order and each StudyStep's `result` store holds the reply.
- [ ] **Step 2: Run → fail** (still returns the marker).
- [ ] **Step 3: Implement** — replace the hook body with the `get_pool().call(...)` dispatch; keep the `_RUN_ORDER` skeleton branch for the ordering tests (guard: if a test injects a fake pool, use it).
- [ ] **Step 4: Run → pass** (v2ecoli venv + PYTHONPATH). Re-run Task 1's ordering tests — still green.
- [ ] **Step 5: Commit.**

---

## Task 4 — Investigation-level analysis Step + `run_investigation_analysis` capability

**Files:**
- Modify: `vivarium_workbench/lib/investigation_steps.py` (add `AnalysisStep`)
- Modify: `vivarium_workbench/env_worker.py` (`run_investigation_analysis` capability)
- Test: `tests/test_investigation_analysis_step.py`

**Interfaces:**
- Worker `run_investigation_analysis(params) -> {"written": [...], "errors": [...]}`, `params = {"workspace", "name", "config", "report_dir"}`: resolves `ANALYSIS_REGISTRY[name]`, instantiates `step = cls(config, core=allocate_core())`, calls `step.update()`, writes each string-valued output (e.g. `matrix_html`) to `report_dir/<name>_<key>.html`. Bypasses `build_cell_records`/`group_for_scale` (the #712 blocker). Never raises.
- `AnalysisStep(process_bigraph.Step)`: `config = {workspace, name, params, study_slugs}`; `inputs()` = one port per study slug wired to that study's `result` store (so it runs after them AND receives their verdicts); `update(state)` assembles `config_verdicts` from the wired study results + static params, dispatches `get_pool().call(ws, "run_investigation_analysis", {...})`, returns `{written: [...]}`.

- [ ] **Step 1: Write failing tests** — (a) hermetic worker test with a fake `ANALYSIS_REGISTRY` entry returning `{"matrix_html": "<div/>"}`, assert the file is written under report_dir; (b) engine test: an `AnalysisStep` wired to two StudySteps runs AFTER both and receives their results as `config_verdicts` (stub the pool).
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** the worker capability (+ register/dispatch) and `AnalysisStep`.
- [ ] **Step 4: Run → pass** (worker test in dev venv; step test in v2ecoli venv).
- [ ] **Step 5: Commit.**

---

## Task 5 — `InvestigationComposite` generator

**Files:**
- Create: `vivarium_workbench/lib/investigation_composite.py`
- Test: `tests/test_investigation_composite_generator.py`

**Interfaces:**
- Produces: `build_investigation_composite(ws_root, inv_slug) -> dict` (a composite **state dict**, not a running Composite): one `StudyStep` doc per member study (config incl. `prereqs` = intra-investigation `pipeline_gate.prerequisites`), each study's `result` store, prereq input wires, priority by declared index; plus one `AnalysisStep` per `investigation.yaml` `analyses:` entry wired to the relevant studies' result stores. Reuses `investigation_member_slugs` + the strict `pipeline_gate.prerequisites` read (carried from #712's `_study_prereqs`).

- [ ] **Step 1: Write failing tests** — compile a fixture investigation (a) no prereqs → N independent StudyStep docs, priority by index, no cross-wires; (b) with a prereq → the dependent StudyStep has a `prereq_<A>` input wired to A's result store; (c) with an `analyses:` entry → an AnalysisStep wired to each study result store. Assert the produced state dict's shape (steps, stores, wires).
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** the generator (pure dict construction; hermetic — no engine needed for shape tests).
- [ ] **Step 4: Run → pass** (dev venv is fine — pure dict shape).
- [ ] **Step 5: End-to-end engine test** — build the composite from a prereq fixture, run it on the real engine with the pool stubbed, assert study run order + the analysis ran last with the studies' verdicts. (v2ecoli venv.)
- [ ] **Step 6: Commit.**

---

## Task 6 — Unify the runners onto the composite

**Files:**
- Modify: `vivarium_workbench/lib/investigations.py` (`run_investigation` :1622) and `vivarium_workbench/lib/prepare_investigation.py`
- Test: `tests/test_runner_unification.py` + carry over #712's golden test

**Interfaces:**
- Both `run_investigation` and `prepare_investigation` build the composite (`build_investigation_composite`) + run it (`Composite({"state": state, "run_steps_on_init": True}, core=build_core())`), replacing their imperative loops. Signatures + return shapes preserved (additive). The long run is launched detached (not on the HTTP thread), reporting progress via runs.db/generation as today.

- [ ] **Step 1: Write the golden backward-compat test** — a no-prereq multi-study fixture (reuse #712's `ws_exec_hook_golden`, copied into this branch): the unified runner produces the SAME run set as the member list, in declared order (pool stubbed to record slugs). Plus a prereq fixture → dependency order.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — replace `run_investigation`'s `spec.runs` loop and `prepare_investigation`'s POST loop with composite build+run. Preserve the detached-launch + progress-reporting behavior. Keep the single-study (`--study`) path working (a one-StudyStep composite).
- [ ] **Step 4: Run → pass** (v2ecoli venv). Re-run the full carried-over backward-compat suite; classify any failure vs base.
- [ ] **Step 5: Remove the superseded #712-style code** if any was ported (the `investigation_order.py` toposort is NOT ported — the scheduler replaces it). Commit.

---

## Self-Review Notes
- **Coverage:** spec §Architecture 1 (StudyStep) → Tasks 1+3; §2 (run_study worker) → Task 2; §2 (analysis dispatch) + §3 analysis steps → Task 4; §3 (generator) → Task 5; §4 (runner unification) → Task 6. A1 ordering = Task 1's wiring proof; A2 = Task 4; the `<run>::comparison_cards` token elimination = Task 4/5 wiring.
- **De-risking:** Task 1 is a walking skeleton proving the load-bearing scheduler-ordering property on the real engine before any real run machinery — if the engine's step-doc/priority shape differs from assumed, it surfaces there, cheaply.
- **Backward-compat gate:** Task 6 golden test (no-prereq → same run set + declared order), carried from #712.
- **Type consistency:** `StudyStep` (config `{workspace, study_slug, prereqs}`, output `result`), `run_study` reply `{run_refs, verdict, errors}`, `build_investigation_composite(ws_root, inv_slug) -> state dict`, `run_investigation_analysis` reply `{written, errors}` — used consistently across tasks.
- **The two real integration risks, each with a BLOCKED escape hatch:** Task 2 (awaiting a normally-detached run) and Task 1 Step 5 (deterministic no-prereq ordering via priority vs explicit serial wiring). Both instruct report-with-specifics rather than hacking.
- **Follow-on (separate v2ecoli plan):** the comparison investigation as an InvestigationComposite (per config a StudyStep with native baseline=candidate + variant=reference, `comparison_matrix` AnalysisStep, ParCa StudyStep upstream) + gated mini e2e. Blocked on this substrate landing.
