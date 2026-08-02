# Store data-flow refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Make a config study's comparison verdict flow to the matrix through the composite's stores (the `run_study` reply), retiring the disk-persistence read, the `study_dir` seam, and the parquet-harness double-attempt.

**Architecture:** `run_study` invokes the study's per-study `analyses:` directly with `{study_dir, runs_db}` context and returns their verdicts in the reply; `InvestigationAnalysisStep` assembles `config_verdicts` from the wired study results; `comparison_matrix` uses the wired dict. Design: `docs/superpowers/specs/2026-08-02-store-dataflow-refactor-design.md`.

**Tech Stack:** `env_worker.py` / `study_runs.py` (substrate), `investigation_steps.py` (substrate), `comparison_matrix.py` (v2ecoli); pytest via the v2ecoli venv + PYTHONPATH.

## Global Constraints
- Tasks 1-2: worktree `~/code/vivarium-workbench--inv-composite`, branch `inv-composite` (#715). Task 3: worktree `~/code/v2ecoli--compare-generalize`, branch `compare-generalize` (#448).
- Commit by explicit path (never `git add -A`).
- Test env: `PYTHONPATH=/Users/eranagmon/code/vivarium-workbench--inv-composite /Users/eranagmon/code/v2ecoli--compare-generalize/.venv/bin/python -m pytest <file> -v`.
- Additive to `run_study`'s reply (new `analyses` key); existing `verdict`/`run_refs` unchanged. No study `analyses:` → `analyses: {}`, no behavior change.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Task 1 — `run_study` invokes per-study analyses directly + returns their verdicts

**Files:** Modify `vivarium_workbench/env_worker.py` (`_run_study`); Modify `vivarium_workbench/lib/study_runs.py` (thread a `skip_analyses` flag so the parquet post-flush doesn't double-attempt); Test `tests/test_run_study_analyses_in_reply.py`.

**Interfaces:**
- `_run_study` reply gains `"analyses": {name: <analysis output incl. "verdict">}`. It loads the study spec's `analyses:`, and for each entry invokes `ANALYSIS_REGISTRY[name]({**entry.params, "study_dir": <study_dir>, "runs_db": <study runs.db>}, core=allocate_core()).update()` (mirror `_run_investigation_analysis`), capturing the output. Never raises (errors → `errors`).
- `run_study_baseline`/`run_study_variant` / `_run_post_run_flush` accept `skip_analyses: bool` (default False → unchanged for all other callers). `_run_study` passes `skip_analyses=True` so the parquet post-flush's analysis stage is skipped (run_study handles them directly). Confirm the flag threads through and stage 3 is skipped when set.

- [ ] **Step 1:** Write the failing test — stub `study_runs.run_study_baseline`/`run_study_variant` (write a fake runs.db row) + monkeypatch `ANALYSIS_REGISTRY` with a fake analysis returning `{"verdict": {"overall": "within_tol"}}`; a fixture study.yaml declaring `analyses: [{name: fake_cmp, params: {candidate_run: demo, reference_run: reference}}]`; assert `_run_study` reply has `analyses["fake_cmp"]["verdict"] == {...}` and the analysis was called with `study_dir`+`runs_db` in its config.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement `_run_study` direct-invocation + the `skip_analyses` thread-through.
- [ ] **Step 4:** Run → pass; re-run `tests/test_run_study_capability.py` (must stay green — additive).
- [ ] **Step 5:** Commit.

## Task 2 — `InvestigationAnalysisStep` assembles verdicts from the wired stores

**Files:** Modify `vivarium_workbench/lib/investigation_steps.py` (`InvestigationAnalysisStep.update` config_verdicts extraction); Test extend `tests/test_investigation_analysis_step.py`.

**Interfaces:**
- `config_verdicts[slug]` = `state[f"study_{slug}"]["analyses"][<name>]["verdict"]` when present, else `state[f"study_{slug}"].get("verdict")`, else the raw result. The analysis-name to read: use the analysis's own `name` (e.g. `comparison_cards`) — pass it via the step config (`verdict_analysis` param, default `comparison_cards`) or extract the sole `analyses` entry's verdict. Keep it general (a `verdict_analysis` config field, defaulting sensibly).

- [ ] **Step 1:** Write the failing test — two config studies whose wired results are `{"analyses": {"comparison_cards": {"verdict": {...A}}}}` / `{...B}`; assert `config_verdicts == {"A": {...A}, "B": {...B}}` (verdicts extracted from the stores).
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement the extraction (+ a `verdict_analysis` config field).
- [ ] **Step 4:** Run → pass; re-run the substrate suite.
- [ ] **Step 5:** Commit.

## Task 3 — `comparison_matrix` reads the wired `config_verdicts` (v2ecoli)

**Files:** Modify `v2ecoli/workflow/analyses/comparison_matrix.py`; Test update `tests/test_comparison_matrix_disk_verdicts.py`.

**Interfaces:**
- Restore `config_verdicts` as the primary source (the wired, now-verdict-shaped dict). Keep `config_studies`+`workspace` disk-load as an OPTIONAL fallback only when `config_verdicts` is absent/empty. Revert the Task-4 precedence flip (config_verdicts wins when present).

- [ ] **Step 1:** Write/adjust the failing test — `comparison_matrix(config_verdicts={A:.., B:..})` renders those verdicts (primary path); the disk fallback still works when `config_verdicts` is empty. The existing explicit-`config_verdicts` matrix test stays green.
- [ ] **Step 2:** Run → fail (if the precedence currently ignores config_verdicts).
- [ ] **Step 3:** Implement the precedence restore (config_verdicts primary; disk fallback).
- [ ] **Step 4:** Run → pass; re-run `tests/test_comparison_matrix_analysis.py` + `tests/test_comparison_matrix_disk_verdicts.py`.
- [ ] **Step 5:** Commit.

---

## Task 4 — Integration: the matrix gets verdicts from the stores (stubbed worker)

**Files:** Update `v2ecoli/tests/test_phase_b_substrate_integration.py`.
- [ ] Extend the stubbed-worker integration test so each config's `run_study` stub returns `{"analyses": {"comparison_cards": {"verdict": {...}}}}`; assert the `comparison_matrix` step receives those verdicts via `config_verdicts` from the wired stores (no disk file written/read). Confirm the full chain: materialize → write → `run_investigation_composite` → matrix renders from wired verdicts.
- [ ] Commit.

## Self-Review Notes
- Coverage: design §1→T1; §2→T2; §3→T3; integration→T4.
- Retires: Task-4 disk-read primacy (T3), the `study_dir` seam (T1 provides context), the parquet double-attempt (T1 skip flag).
- Backward-compat: additive `analyses` reply key; `skip_analyses` default-false; no-`analyses:` studies unaffected. Existing substrate + Phase B suites are the gate.
- Cross-repo: T1-T2 on #715 (substrate), T3-T4 on #448 (v2ecoli). Same PYTHONPATH test env.
