# Phase 2d — Evidence From Computed Verdict Nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the investigation graph's evidence chain source Finding→Evidence(→Decision→Conclusion) nodes from a study's **computed report-card verdicts** (Phase 2c artifacts) when the study has no persisted or authored-derived chain — realizing the design's L4 ("evidence nodes are computed workflow artifacts, not read-time derivations") while keeping authored/persisted content as override.

**Architecture:** The design (§4.1): "`chain_derivation` becomes a *reader* of computed evidence nodes rather than a deriver from authored fields — authored content remains allowed as enrichment/override." `build_investigation_graph` already has a precedence: `load_study_nodes` (persisted human/API nodes) → else `derive_chain_nodes(study_spec)` (authored study.yaml fields). Phase 2d adds a THIRD tier below those: computed report-card findings (from `report_card_findings_for_study`, which reads the `verdict.json` artifacts 2c emits) lifted into the SAME typed chain-node shape. Computed report-card findings share the exact shape (`{statement, status, evidence:{observed}}`) of the v4 authored `findings` list that `derive_chain_nodes` already lifts, so the lift logic is extracted and reused (DRY, and guarantees the computed chains pass `investigation_contracts.validate_chain` by construction).

**Tech Stack:** Python, pytest, `lib/chain_derivation.py` (pure), `lib/investigation_graph_views.py` (I/O caller), `lib/study_spec.report_card_findings_for_study`.

## Global Constraints

- **Worktree:** `~/code/vwb-phase2d`, branch `feat/evidence-from-computed-nodes` (off `origin/main` @ `6b80e7d`, which has Phase 2c). Verify `git branch --show-current` + HEAD before every commit.
- **Tests:** `/Users/eranagmon/code/venv/bin/python -m pytest` (NOT the venv `pytest` binary). `read_text(encoding="utf-8")` everywhere (ASCII-locale CI).
- **`chain_derivation.py` stays PURE** (no I/O / clock / RNG) — the module docstring guarantees it. All verdict.json reading happens in the I/O caller (`investigation_graph_views` / `study_spec`), which passes an already-computed findings list into the pure lifter.
- **Status→verdict vocabulary (fixed):** report-card verdict → finding status is `within_tol→confirms`, `drift→partial`, `mismatch→contradicts`, `ungraded→novel` (`study_spec._VERDICT_TO_STATUS`); the lifter maps status→verdict via `confirms→supported`, `contradicts→refuted`, `partial→partial`, else `""` (novel → Finding+Evidence only, no Decision). Do not redefine these maps.
- **Precedence is strict fallback, never merge:** persisted nodes win outright; authored-derived only when no persisted; computed-report-card only when neither. Authored/persisted content is never clobbered.

---

### Task 1: Extract the finding-list lifter (behavior-preserving refactor)

**Files:**
- Modify: `vivarium_workbench/lib/chain_derivation.py`
- Test: `tests/test_chain_derivation.py` (locate/extend; if absent, create)

**Interfaces:**
- Produces: `_lift_finding_list(findings: list, slug: str, *, id_tag: str, prov: callable) -> dict[str, dict]` — the exact loop currently at `chain_derivation.py:87-127` (the `isinstance(findings, list)` branch), parameterized by `id_tag` (the node-id infix, currently `"fl"`) and `prov` (a `(source:str)->dict` provenance builder, currently `_prov`). Node ids: `finding/derived-<slug>-<id_tag><k>` etc. Returns the same nodes it does today.
- Consumes: `_DECISION_OUTCOME`, `_EVIDENCE_STATE`, the module `_STATUS_VERDICT` (promote it to module scope if still local to the branch).

- [ ] **Step 1: Write/confirm a characterization test** — if `tests/test_chain_derivation.py` exists, note the tests covering the v4-`findings`-list path; if not, write one: a `study_spec` with `findings=[{statement:"X reproduces Y", status:"confirms", evidence:{observed:"n=3"}}]` → `derive_chain_nodes(spec,"s1")` yields `finding/derived-s1-fl0` (statement "X reproduces Y", `runs:["run/s1"]`), `evidence/derived-s1-fl0` (state `accepted`), `decision/derived-s1-fl0` (outcome `accept`), `conclusion/derived-s1-fl0`.
- [ ] **Step 2: Run → PASS** (documents current behavior) or FAIL-then-fix if newly written. Run: `/Users/eranagmon/code/venv/bin/python -m pytest tests/test_chain_derivation.py -v`
- [ ] **Step 3: Refactor** — lift lines 87-127 into `_lift_finding_list(findings, slug, *, id_tag="fl", prov=_prov)`; promote `_STATUS_VERDICT` to module scope; in `derive_chain_nodes` replace the inline loop with `nodes.update(_lift_finding_list(findings, slug, id_tag="fl", prov=lambda src: _prov(slug, src)))` (or keep `_prov(slug, src)` signature — match the current call). Behavior identical.
- [ ] **Step 4: Run test → PASS** (unchanged behavior), plus the whole `tests/test_chain_derivation.py` green.
- [ ] **Step 5: Commit** `git add -A && git commit -m "refactor(chain): extract reusable _lift_finding_list from derive_chain_nodes"`

---

### Task 2: Lift computed report-card findings + wire the third precedence tier

**Files:**
- Modify: `vivarium_workbench/lib/chain_derivation.py` (add `lift_report_card_findings`)
- Modify: `vivarium_workbench/lib/investigation_graph_views.py` (precedence at ~L118-123)
- Test: `tests/test_investigation_graph_route.py` OR a focused new `tests/test_evidence_from_computed_nodes.py` (prefer the focused new file — the route test file hits the FastAPI-app-import collection error unrelated to this change).

**Interfaces:**
- Produces:
  - `lift_report_card_findings(findings: list, slug: str) -> dict[str, dict]` in chain_derivation.py — a thin wrapper: `_lift_finding_list(findings, slug, id_tag="rc", prov=lambda src: _prov_computed(slug, src))`, where `_prov_computed` stamps `actor="derived"` (proven shape → validate_chain-safe) with `justification="computed from report-card verdict"` / `source_objects=["study/<slug>"]`, `tool="2d/report-card-evidence"`. The findings already carry `statement`/`status`/`evidence`, so the lifter needs no report-card-specific logic.
  - `build_investigation_graph` gains a third fallback tier.
- Consumes: `study_spec.report_card_findings_for_study(ws_root, slug) -> (findings, rc_urls)` (the I/O read of the computed verdict.json artifacts).

- [ ] **Step 1: Write the failing test** `tests/test_evidence_from_computed_nodes.py`:
  - `lift_report_card_findings`: feed a findings list `[{id:"report-card-standard", statement:"cell mass: within tolerance", status:"confirms", evidence:{observed:"5 ✓"}}]` → assert it yields `finding/derived-<slug>-rc0` (statement preserved, `runs:["run/<slug>"]`), `evidence/derived-<slug>-rc0` (state `accepted`), `decision/derived-<slug>-rc0` (outcome `accept`).
  - end-to-end precedence: build a tmp workspace `studies/s1/` with a `viz/report_card/standard.{html,verdict.json}` (`{"overall":"within_tol"}`) and a `study.yaml` with NO authored `findings`/`conclusion_verdicts`; call `build_investigation_graph(ws_root, inv_slug)` (scaffold a minimal `investigations/<inv>/investigation.yaml` with `members:[s1]`); assert `result["chains"]["s1"]` contains a computed `finding/…-rc0` node and `chains["s1"]["derived"] is True`. Add a negative case: a study WITH authored `findings` → the chain uses the authored `-fl`/`-fe` nodes, NOT `-rc` (persisted/authored wins).
- [ ] **Step 2: Run → FAIL** (`lift_report_card_findings` missing / no `-rc` nodes in the chain).
- [ ] **Step 3: Implement** `lift_report_card_findings` + `_prov_computed` in chain_derivation.py; in `investigation_graph_views.build_investigation_graph`, after the existing `if not nodes: nodes = derive_chain_nodes(...)` block, add:
  ```python
  if not nodes:
      from vivarium_workbench.lib.study_spec import report_card_findings_for_study
      rc_findings, _ = report_card_findings_for_study(ws_root, slug)
      nodes = lift_report_card_findings(rc_findings, slug)
      derived = derived or bool(nodes)
  ```
  (import `lift_report_card_findings` at module top alongside `derive_chain_nodes`.)
- [ ] **Step 4: Run test → PASS**, plus `tests/test_chain_derivation.py` still green and (if it collects) the investigation-graph view tests.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(2d): lift computed report-card verdicts into the investigation evidence chain"`

---

## Self-Review

- **Spec coverage:** L4 "evidence nodes are computed workflow artifacts, not read-time derivations" → Task 2 (computed report-card verdicts become typed chain nodes); "authored content remains override" → strict fallback precedence (persisted → authored → computed). DRY reuse (Task 1) guarantees `validate_chain` compatibility.
- **Type consistency:** `_lift_finding_list` return shape identical across authored (`fl`) and computed (`rc`) callers; status→verdict maps unchanged; `report_card_findings_for_study` returns `(findings, rc_urls)` — Task 2 destructures both.
- **No placeholders:** real test code, real anchors, real signatures.
- **Purity:** all verdict.json I/O stays in the caller; the lifter is pure. `chain_derivation.py` module contract preserved.
- **Out of scope (Phase 3):** the audit module (L0–L5 runnable checks + CI gate + read-only workbench Audit view). 2d only surfaces computed evidence in the existing graph.

## Notes

- `_prov_computed` keeps `actor="derived"` deliberately — a computed-from-artifact chain is still non-human-gated, and reusing the proven provenance shape avoids risking `investigation_contracts.validate_chain`. The distinguishing signal is `justification`/`tool`, not `actor`.
- Ungraded cards (`overall:"ungraded"` → status `novel` → verdict `""`) produce Finding+Evidence only (no Decision/Conclusion) — correct: an ungraded card is not a gated result.
