# Increment G — Surface the Audit-Grade Apparatus (adopt-now)

> **For agentic workers:** implement subagent-driven with per-task review. Steps use `- [ ]`.
> **Depends on:** the declutter (PR #706) + **Increment A "stop the noise"** — in particular A#6 (delete `#study-subnav`/pillar indirection) must land before G1 (the act rail edits the same nav markup). Build G off Increment A's tip.

**Goal:** Make the study page *audit-grade by rendering the rigor that already exists* — with **no schema changes and no policy**. Fable's key finding: `spine_acceptance`, `rigor.py`, `study_audit` L0–L5, and the frozen `conclusion_card` are all computed (some run in CI) and **never shown on the page**. This increment surfaces them, relabels the six status axes as the six gates, unifies the outcome vocabulary, and advertises attribution (with an explicit `unattributed`).

**Design source of truth:** `docs/superpowers/specs/2026-08-01-study-design-fable-pass.md` — v2 §9 (conceptual model + §9.3 tab rail), §10 (Tests → Assurance record), §11 (Decide → authorized verdict), §13 (gating model), §14/§14.1 (reconciled increments + adopt-now path). Each task below cites the section an implementer must read.

**Tech stack:** Jinja template (`templates/study-detail.html`), vanilla JS (`static/study-detail.js`), a few thin FastAPI read-routes in `api/app.py` backed by `lib/`. pytest via the live-server `dashboard_client` factory fixture.

## Global constraints
- **No schema changes.** Everything here renders data that already exists or is already computed. If a task needs a value that isn't computed yet, it is out of scope (that's Increment D1) — render `unattributed` / `not assessable` / `unavailable(reason)` per the R2 "absent ≠ empty" rule, never a fabricated value or an empty box.
- **One outcome vocabulary** (G3) is a shared helper used by every other G task — land it early.
- **Absent ≠ empty** (spec §2 R2): a set that couldn't be computed says `unavailable(reason)`, not empty.
- **Attribution is honest:** where no actor is recorded, render `unattributed` explicitly (never blank).
- **Computed, not claimed:** gate/verdict states show computed-vs-authored divergence where both exist; independence/basis default to `unknown`, never to a flattering value.
- Test env: `/Users/eranagmon/code/vivarium-workbench--study-declutter/.venv/bin/python -m pytest <file> -v`; `dashboard_client` is a FACTORY `dashboard_client(ws)->client`; run only focused files, foreground; grep `tests/`+`vivarium_workbench/testing/` for fallout on any deletion/relabel.
- **Concurrency:** one editing subagent at a time in the worktree; reviewers are read-only and must never run git stash/reset/checkout/clean (compare via `git show <rev>:<path>`).

---

## Task G3 (do first): One outcome vocabulary
**Kind:** T · **Fable §:** §10.1, §14.1(4), C5.
Map the existing verdict/test tokens `PASS / FAIL / PARTIAL / SKIP` (and `within_tol/drift/mismatch/ungraded`) → the four-value vocabulary **`met` / `conditional-pass` / `not met` / `not assessable`**, as a single shared Jinja filter (`outcome_label`) + a matching JS helper, with consistent glyphs/colors. Every later G task uses it. Do NOT change the underlying stored tokens — only the display vocabulary.
- Test: unit-test the mapping (each input token → expected label, unknown → `not assessable`); a render assertion that a study's Tests/verdict shows the new vocabulary.

## Task G1: The act rail + five-act tab bar
**Kind:** T · **Fable §:** §9.3 (revised tab bar), §9.2 (five acts). **Requires A#6 landed.**
Add a hairline **act-label rail** above the tab buttons grouping the 8 tabs into five acts — **The Study** (Overview) · **Design** (Model, Readouts) · **Evidence** (Simulations, Visualizations) · **Assurance** (Tests) · **Decision** (Decide) — with **Exports** set apart as the Record drawer. Each act label carries a **gate dot** reflecting that act's gate state (computed from the axis it maps to — see G2). Tab order is the declutter order; Readouts reposition (Model→Readouts→Simulations) rides with Increment B, so if B hasn't landed keep current order and just add the rail over the existing order.
- Test: render assertion that the act labels (`The Study`/`Design`/`Evidence`/`Assurance`/`Decision`) render above the tab nav, one row, and each has a gate-dot element.

## Task G2: Six axes → six gates (in `status ▾`)
**Kind:** T · **Fable §:** §13 (gating model), §13.1 (gates in UI), C4.
Relabel the existing six status axes (design/implementation/simulation/evaluation/gate/expert_review) as the **six gates**: **Plan / Execution / Evidence / Quality / Decision / Release**. Turn the `status ▾` disclosure into the **gate ladder**: each gate shows its state and, where a machine evaluator exists beside the authored axis (`study_verify`, run manifests, `study_audit`, `rigor.py`, `conclusion_verdicts`, `conclusion_card`), a **computed-vs-authored** indicator. Feed the act-rail gate dots (G1) from these states.
- Test: render assertion that `status ▾` shows the six gate names and per-gate state; where computed differs from authored, a divergence marker renders.

## Task G4: Acceptance criteria band on Tests (C1)
**Kind:** T · **Fable §:** §10.1 (band 1). 
Render `spine_acceptance` (already attached to the spec via `load_study_detail_spec`, currently never displayed — confirm the field) as Tests' **Acceptance criteria** band: each criterion with its outcome in the G3 vocabulary, linked to the evidence (test/run/finding) it rests on. If `spine_acceptance` is absent for a study, render nothing (not an empty box) — or a Plan-gate readiness gap, not inline furniture.
- Test: a study fixture with `spine_acceptance` renders the criteria band with outcomes + evidence links; a study without it renders no empty band.

## Task G5: Rigor scorecard → Tests Quality check group (C2)
**Kind:** T + thin B · **Fable §:** §10.1 (Checks band, automated group), §14.1(2).
Expose the deterministic `rigor.py` scorecard (already run in CI) via a thin read-route (`GET /api/study-rigor?study=<slug>` → `lib` wrapper over `rigor.py`) and render it as the **automated** "Quality" check group in Tests, severities included. Degrade to `unavailable(reason)` if rigor can't compute.
- Test: route returns the rigor payload for a fixture study; render assertion the Quality group shows the scored checks + severities (or `unavailable` when it can't compute).

## Task G6: L0–L5 reproducibility audit → Tests check group (C3)
**Kind:** T + thin B · **Fable §:** §10.1, §14.1(2).
Expose `study_audit` L0–L5 (already run in CI) via a thin read-route and render it as the **Reproducibility** check group in Tests, each level with its state in the G3 vocabulary. Degrade to `unavailable(reason)`.
- Test: route + render assertion (levels shown; `unavailable` when it can't compute).

## Task G7: Attribution from existing fields (C6)
**Kind:** T · **Fable §:** §11.2 (actor model), §14.1(5).
Wherever an actor is *already* recorded — `feedback_tracked.author` / `.responded_by`, `expert_decisions_needed.asked_to`, the conclusion-card write time — render **who + when** on the relevant verdict/approval/gate, with **human vs agent** distinguished (glyph; agents show model where available). Where **no** actor is recorded, render **`unattributed`** explicitly (never blank). No new fields — read what exists.
- Test: a fixture with a recorded author renders "…by <actor>"; a fixture with none renders `unattributed` on the verdict.

## Task G8: Show the verdict is frozen (C7)
**Kind:** T + tiny B · **Fable §:** §11.4 (locking).
`conclusion_card` already freezes the verdict; surface that in Decide as a **frozen record** indicator with its timestamp + a content **digest** (a small backend hash over the frozen verdict payload). This is display of an existing freeze, not a new locking system (that's D2.4).
- Test: render assertion that a study with a frozen conclusion shows the frozen indicator + a digest; an unfrozen one does not.

---

## Out of scope (later increments)
- Real `acceptance_criteria[]` / `severity` / `deviations`/`waivers` / `gates{}` objects / the ordered audit-package export — **Increment D1 (schema)**.
- `attributions[]`/`sign_off{}`, the computed basis meter, computed independence — **D2**.
- Immutable hash-chained records + who-signs-what policy — **D2 aspirational** (a product, build when someone's on the hook).
- Readouts instrument + tab reposition — **Increment B**. Findings ledger, Model merge, Plan-&-provenance dissolution — **Increment C**.

## Success criteria (from Fable §14.2)
- The tab rail shows five acts with per-act gate dots; Assurance is a visible act.
- Tests opens with acceptance criteria in the four-value vocabulary, each linked to its evidence.
- The rigor scorecard and the L0–L5 audit are visible on the page, not just in CI.
- `status ▾` reads as six named gates, each with a computed state; computed-vs-authored divergence is visible per gate.
- Every verdict/approval/gate shows its actor (human/agent) and basis — or `unattributed`, never blank.
- No fabricated values, no empty boxes: uncomputable sets say `unavailable(reason)`.
