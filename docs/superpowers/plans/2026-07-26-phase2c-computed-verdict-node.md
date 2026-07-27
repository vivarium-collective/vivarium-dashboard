# Phase 2c — Computed Verdict Artifact in the Engine Flush Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the content-addressed engine flush emit a real, machine-readable `verdict` artifact (rolled up from the run's own report cards), content-address it, and have readers prefer it over the `size < 64` HTML-stub heuristic.

**Architecture:** "Layer verdict emission" (user decision, 2026-07-26): keep the two flush paths, but the engine flush (`composite_flush.run_flush`) now writes `run_dir/verdict.json` rolled up from the report-card `*.verdict.json` files it just produced; `pipeline._default_compute` content-addresses it via the existing `_record_pointer` seam; the `study_spec.py` report-card reader prefers a computed `verdict.json` over the file-size heuristic. This realizes the design's L4 "each declared report card emits a computed verdict; verdict is a computed workflow artifact, not a read-time derivation" for the engine path, without the larger flush-convergence refactor.

**Tech Stack:** Python, pytest, the existing `vivarium_workbench/lib/artifacts` engine + `composite_flush`, the `_CANON_SEVERITY` verdict vocabulary.

## Global Constraints

- **Worktree:** `~/code/vwb-phase2cd`, branch `feat/verdict-nodes-evidence` (off `origin/main` @ `ab046e1`). Verify `git branch --show-current` + HEAD before every commit.
- **Tests:** run with the repo's venv: `/Users/eranagmon/code/venv/bin/python -m pytest` (use `python -m pytest`, NOT the venv `pytest` binary — stale-binary sys.path artifacts). CI runs ASCII locale → all file reads use `read_text(encoding="utf-8")` / `write_text(..., encoding="utf-8")`.
- **Verdict vocabulary (canonical):** `mismatch` (severity 3) > `drift` (2) > `within_tol` (1) > `ungraded` (0). Roll-up `overall` = the WORST (max-severity) card verdict; no cards → `ungraded`. This mirrors `conclusion_card._CANON_SEVERITY` — reuse/import it, do not redefine the numbers.
- **Verdict artifact schema:** `run_dir/verdict.json` = `{"schema": "run_verdict/v1", "overall": <canon>, "cards": [{"name": <card>, "overall": <canon>}, ...]}`. Deterministic key order in `cards` (sort by name) so the content hash is stable.
- **Best-effort, never fail the run:** verdict emission wraps in try/except and logs — a verdict error must never turn a successful run into a failure (matches the existing `flush must never fail the run` posture at `run_runner.py:695`).

---

### Task 1: Verdict roll-up helper (pure function)

**Files:**
- Modify: `vivarium_workbench/lib/composite_flush.py`
- Test: `tests/test_composite_flush_verdict.py` (create)

**Interfaces:**
- Produces: `rollup_run_verdict(verdict_json_paths: list[Path]) -> dict` — reads each `*.verdict.json`, extracts its `overall` (canonicalized), returns `{"schema": "run_verdict/v1", "overall": <worst>, "cards": [{"name","overall"}...]}`. `name` = the file stem minus `.verdict` (e.g. `standard.verdict.json` → `standard`). Unreadable / missing-`overall` files contribute a card with `overall: "ungraded"` (never raise). Empty input → `{"schema":"run_verdict/v1","overall":"ungraded","cards":[]}`.
- Consumes: `conclusion_card._CANON_SEVERITY` (import the mapping; do not redefine).

- [ ] **Step 1: Write the failing test** `tests/test_composite_flush_verdict.py`:

```python
import json
from pathlib import Path
from vivarium_workbench.lib.composite_flush import rollup_run_verdict


def _wc(p: Path, overall):
    p.write_text(json.dumps({"overall": overall}), encoding="utf-8")


def test_rollup_takes_worst_and_sorts_cards(tmp_path):
    _wc(tmp_path / "standard.verdict.json", "drift")
    _wc(tmp_path / "statistical.verdict.json", "mismatch")
    _wc(tmp_path / "config.verdict.json", "within_tol")
    out = rollup_run_verdict(sorted(tmp_path.glob("*.verdict.json")))
    assert out["schema"] == "run_verdict/v1"
    assert out["overall"] == "mismatch"                 # worst wins
    assert [c["name"] for c in out["cards"]] == ["config", "standard", "statistical"]
    assert {c["name"]: c["overall"] for c in out["cards"]}["config"] == "within_tol"


def test_rollup_empty_is_ungraded(tmp_path):
    assert rollup_run_verdict([]) == {
        "schema": "run_verdict/v1", "overall": "ungraded", "cards": []}


def test_rollup_bad_file_is_ungraded_card(tmp_path):
    bad = tmp_path / "broken.verdict.json"
    bad.write_text("{not json", encoding="utf-8")
    out = rollup_run_verdict([bad])
    assert out["cards"] == [{"name": "broken", "overall": "ungraded"}]
    assert out["overall"] == "ungraded"
```

- [ ] **Step 2: Run it → FAIL** (`ImportError: rollup_run_verdict`). Run: `/Users/eranagmon/code/venv/bin/python -m pytest tests/test_composite_flush_verdict.py -v`
- [ ] **Step 3: Implement** `rollup_run_verdict` in `composite_flush.py` (near `render_report_card`, top-level). Read each path with `json.loads(p.read_text(encoding="utf-8"))` inside try/except → canonicalize `overall` (unknown/missing → `"ungraded"`); card `name` = `p.name[:-len(".verdict.json")]` (or `p.stem` split on `.verdict`). Sort `cards` by `name`. `overall` = the card whose `_CANON_SEVERITY` is max (default `"ungraded"`). Import `from vivarium_workbench.lib.conclusion_card import _CANON_SEVERITY`.
- [ ] **Step 4: Run test → PASS.**
- [ ] **Step 5: Commit** `git add vivarium_workbench/lib/composite_flush.py tests/test_composite_flush_verdict.py && git commit -m "feat(flush): rollup_run_verdict helper — worst-severity run verdict from report cards"`

---

### Task 2: Engine flush writes `run_dir/verdict.json`

**Files:**
- Modify: `vivarium_workbench/lib/composite_flush.py` (`run_flush`, L119-153)
- Test: `tests/test_composite_flush_verdict.py` (extend)

**Interfaces:**
- Consumes: `rollup_run_verdict` (Task 1); the `analyses` list (`[{name, written, errors}]`) already computed in `run_flush`; each `written` entry is a path string, some ending `.verdict.json`.
- Produces: `run_flush(...)` now writes `run_dir/verdict.json` and its return dict gains `"has_verdict": bool`.

- [ ] **Step 1: Write the failing test** — a unit test that drives `run_flush`'s verdict step in isolation by monkeypatching `_dispatch_analyses` to return a fixed `analyses` list whose `written` includes two `.verdict.json` files it creates under `run_dir`, plus a viz.json, then asserts `run_dir/verdict.json` exists with `overall == "mismatch"` and `result["has_verdict"] is True`. (Patch `_dispatch_analyses` via `monkeypatch.setattr("vivarium_workbench.lib.composite_flush._dispatch_analyses", fake)`; pass `req=types.SimpleNamespace(steps=1, spec_id="x.y")`, `core=None`.)
- [ ] **Step 2: Run → FAIL** (`verdict.json` not written / `has_verdict` KeyError).
- [ ] **Step 3: Implement** in `run_flush`, after the report.html block (L152) and before `return`:
  - Collect verdict paths: `vpaths = [Path(w) for a in analyses for w in (a.get("written") or []) if str(w).endswith(".verdict.json")]`.
  - `has_verdict = False; try: (run_dir / "verdict.json").write_text(json.dumps(rollup_run_verdict(vpaths)), encoding="utf-8"); has_verdict = True; except Exception: traceback.print_exc()`.
  - Add `"has_verdict": has_verdict` to the returned dict.
- [ ] **Step 4: Run test → PASS.**
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(flush): engine flush emits run_dir/verdict.json rolled up from report cards"`

---

### Task 3: Content-address the verdict via `_record_pointer`

**Files:**
- Modify: `vivarium_workbench/lib/artifacts/pipeline.py` (`_default_compute`, after the success guard at L335)
- Test: `tests/test_study_pipeline_resolve.py` (extend)

**Interfaces:**
- Consumes: `_record_pointer(runs_db, stage, oid)` (pipeline.py:83); `hashing` (already imported); `out_dir / "verdict.json"` (written by Task 2 when the engine path runs).
- Produces: when `out_dir/verdict.json` exists after a successful run, `_default_compute` records a pointer `("verdict", <content-hash-of-verdict.json>)` into the run's `runs.db` `artifact_pointers` table before returning `out_dir`.

- [ ] **Step 1: Write the failing test** in `tests/test_study_pipeline_resolve.py`: a `compute_fn`-injected `resolve_study` won't exercise `_default_compute`, so test `_default_compute`'s pointer step directly — call a small helper or assert via a stub. Simplest: add a focused unit test that (a) creates an `out_dir` with a `verdict.json`, (b) calls the new `_maybe_record_verdict_pointer(db_path, out_dir)` helper, (c) opens `db_path` and asserts a row `("verdict", <hash>)` in `artifact_pointers`. (Extract the pointer logic into `_maybe_record_verdict_pointer(db_path: Path, out_dir: Path) -> None` so it is unit-testable without a full run.)
- [ ] **Step 2: Run → FAIL** (`AttributeError` / no such helper).
- [ ] **Step 3: Implement** `_maybe_record_verdict_pointer(db_path, out_dir)` in pipeline.py: `vf = Path(out_dir) / "verdict.json"; if not vf.is_file(): return`; compute `vid = hashing.content_id(vf.read_bytes())` (use the existing hashing primitive — check `hashing.py` for the content-hash fn; if only `artifact_id` exists, hash the bytes with the same hasher it uses). Then `try: _record_pointer(db_path, "verdict", vid) except Exception: pass` (best-effort). Call it from `_default_compute` right before `return out_dir` (after the terminal-status guard).
- [ ] **Step 4: Run test → PASS**, plus the full `tests/test_study_pipeline_resolve.py` still green.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(engine): content-address the computed verdict via artifact_pointers"`

---

### Task 4: Reader prefers the computed verdict over the size heuristic

**Files:**
- Modify: `vivarium_workbench/lib/study_spec.py` (both report-card readers: ~L840-850 and ~L1298-1308)
- Test: `tests/test_study_spec_report_cards.py` (create or extend the existing report-card test file — locate via `grep -l html_stub tests/`)

**Interfaces:**
- Consumes: per-card `<card>.verdict.json` sibling of `<card>.html`.
- Produces: when a sibling `<card>.verdict.json` with a valid `overall` exists, the reader sets that card's `verdict` from the json and `html_stub = False` regardless of html size; the `size < 64` heuristic remains ONLY as the fallback when no computed verdict is present.

- [ ] **Step 1: Write the failing test**: build a tmp study `viz/report_card/` with `standard.html` of 3 bytes (`"<i>"`) AND `standard.verdict.json` = `{"overall":"drift"}`; call the reader (identify the public fn wrapping L840 / L1298 — likely `discover_report_card_urls` / the card-list builder) and assert the returned card has `verdict == "drift"` and `html_stub is False`. Add a second case: tiny html, NO verdict.json → `html_stub is True` (heuristic preserved).
- [ ] **Step 2: Run → FAIL** (tiny html currently forces `html_stub True` even with a verdict.json).
- [ ] **Step 3: Implement** at both sites: before `html_stub = html.stat().st_size < 64`, check `vj = html.with_suffix("")...` → the sibling `<card>.verdict.json`; if it exists and parses with a known `overall`, set `verdict` from it and `html_stub = False`; else fall through to the size heuristic. Factor the sibling-verdict lookup into one small helper to avoid duplicating logic across the two sites.
- [ ] **Step 4: Run test → PASS**, plus `pytest -k "report_card or html_stub"` green.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(reader): prefer computed verdict.json over html-size stub heuristic"`

---

## Self-Review

- **Spec coverage:** L4 "report card emits a computed verdict; verdict is a computed workflow artifact not a read-time derivation" → Tasks 1-3 (emit + content-address); "kills the HTML stub [heuristic]" → Task 4. Design's "layer" choice (keep both flush paths) honored — no flush convergence.
- **Type consistency:** `rollup_run_verdict` returns the `run_verdict/v1` dict used verbatim in Task 2's write and Task 3's hash; `_CANON_SEVERITY` imported once (Task 1), reused implicitly. Verdict vocab identical across all tasks.
- **No placeholders:** each task has real test code, real anchors (file:line), real signatures.
- **Out of scope (own plans):** Phase 2d (evidence/findings read computed verdict nodes — the `load_study_nodes`→`derive_chain_nodes` precedence) and Phase 3 (audit module + CI gate + read-only Audit view). Task 3 lays the `artifact_pointers` seam 2d will consume.

## Notes

- `hashing.py`: confirm the content-hash primitive name in Task 3 (`content_id` vs hashing the bytes with the module's hasher) — read the module first; reuse, don't invent a second hash scheme.
- The engine verdict reflects the run's OWN report-card verdicts (this-run-accurate), independent of the study's authored `conclusion` tracks — that's the point of the layered approach. The richer three-track `conclusion_card` verdict stays a live-flush concern until (if ever) the paths converge.
