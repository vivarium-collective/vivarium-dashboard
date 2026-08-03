# Store data-flow refactor — verdicts flow through the composite, not disk

**Date:** 2026-08-02
**Status:** design (for approval before implementation)
**Repos:** `vivarium-workbench` (`inv-composite` / #715) + `v2ecoli` (`compare-generalize` / #448)

## Problem

The investigation-as-composite gets *ordering* from the graph but routes *data*
through the filesystem: each config study's `comparison_cards` verdict is written
to `studies/<slug>/report_card_verdict.json`, and `comparison_matrix` reads it
back by slug. That hybrid is the sole reason for four open seams —
verdict-to-disk persistence, `ComparisonCards`-Step `study_dir` forwarding, the
matrix disk-read, and the per-study-vs-investigation analysis-path split. The
composite promised "data flows through wiring"; the actual data goes around it.

## Principle

**A study's verdict is part of its result.** The `StudyStep`'s output store
already carries the `run_study` reply and the matrix Step is already wired to
every config's result store. So the config verdict should travel *in the reply*,
through the wiring the composite already has — not through disk.

## Design

### 1. `run_study` returns per-study analysis verdicts (substrate, #715)

`env_worker._run_study`, after running the study (baseline + variants), invokes
each of the study's declared per-study `analyses:` **directly** —
`ANALYSIS_REGISTRY[name](config, core=allocate_core()).update()`, the same
invocation `run_investigation_analysis` already uses — with
`config = entry.params` merged with the run context `run_study` uniquely holds:
`{study_dir, runs_db}` (+ the resolved run refs). It captures each analysis
output and adds it to the reply:

```
{"run_refs": [...], "verdict": <conclusion verdict, unchanged>,
 "analyses": {name: {"verdict": ..., ...}}, "errors": [...]}
```

Because `run_study` supplies `study_dir`/`runs_db`, the `ComparisonCards`-Step
`study_dir` seam disappears **by construction** — the analysis is handed its
context, not left to discover it.

**Avoid the double-run.** The per-study parquet post-flush
(`study_runs._run_post_run_flush` stage 3 → `run_study_analyses` →
`run_analyses`) also reads `analyses:` and today *fails* `comparison_cards` there
(scale=single, no `study_dir` → run-store lookup fails, logged into
`analysis_errors`). Resolution: `run_study` invokes the verdict-producing
analyses directly (this new path) and the parquet post-flush **skips** them —
add a `skip_analyses` (or "analyses handled by caller") flag threaded from
`_run_study` through `run_study_baseline/variant` into `_run_post_run_flush`, so
each analysis runs exactly once, in the context that has its runs. The parquet
post-flush remains for genuine timeseries/viz analyses (none in the comparison
today). Alternatively (implementer's call if cleaner): keep the post-flush as-is
and filter its `comparison_cards` failure out — but the skip flag is preferred
(one run, no noise).

### 2. `InvestigationAnalysisStep` assembles verdicts from the wired stores (substrate)

Its `config_verdicts` is already built from `state[f"study_{slug}"]` (the wired
study result). Refine the extraction: `config_verdicts[slug] =
study_result["analyses"][<verdict_analysis>]["verdict"]` (fall back to
`study_result["verdict"]`). The matrix now receives real, verdict-shaped
`config_verdicts` from the composite wiring.

### 3. `comparison_matrix` reads from `config_verdicts` (v2ecoli, #448)

Revert Task 4's disk-read + the `config_studies`-precedence flip: with the wired
`config_verdicts` now verdict-shaped, the matrix uses it directly (its original,
simplest contract). Keep `config_studies`/`workspace` as an *optional* fallback
(harmless), but the primary path is the wired dict. `comparison_cards`' disk
persistence (`write_study_verdict`, Task A) stays only for the dashboard's
per-study card display — it is no longer the matrix's source, so its absence
never yields a placeholder.

## What this retires

- `ComparisonCards`-Step `study_dir` forwarding seam → gone (run_study provides it).
- Matrix disk-read of `report_card_verdict.json` (Task 4) → reverted to the wired dict.
- The verdict's dependence on a filesystem path/timestamp → gone.
- The per-study analysis silently failing in the parquet harness → gone (skip flag).

Net: less code than finishing the hybrid, and the cross-study data-flow finally
matches the composite model.

## Backward-compatibility

- `run_study`'s reply gains an additive `analyses` key; existing callers
  (`prepare_investigation`, the run API) ignore unknown keys. The existing
  `verdict` (conclusion card) is unchanged.
- A study with no `analyses:` → `run_study` returns `analyses: {}`, no behavior
  change; the skip flag is a no-op.
- The existing substrate + Phase B hermetic suites are the gate; add tests that
  a config study's `run_study` reply carries the comparison verdict and the
  matrix renders it from the wired store (no disk).

## Testing

- **Substrate:** `_run_study` with stubbed baseline/variant + a fake
  `ANALYSIS_REGISTRY` comparison analysis → assert the reply's `analyses[name].verdict`
  is captured and `study_dir`/`runs_db` were passed; assert the parquet post-flush
  did not double-run it.
- **Substrate:** `InvestigationAnalysisStep` wired to two config studies whose
  results carry `analyses.comparison_cards.verdict` → `config_verdicts` assembled
  from the stores (no disk).
- **v2ecoli:** `comparison_matrix` renders from a wired `config_verdicts` dict;
  the disk-read fallback still works but isn't required.
- **Integration (stubbed worker):** the Phase B substrate test asserts the matrix
  receives verdicts from the config studies' result stores.

## Non-goals

- Refactoring the parquet-sweep analysis path itself (only add the skip flag).
- Removing `write_study_verdict` (kept for dashboard display).
- The real-run/e2e (separate).
