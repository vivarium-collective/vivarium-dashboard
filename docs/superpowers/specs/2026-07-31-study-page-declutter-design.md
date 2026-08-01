# Study Detail Page — Declutter & Science-Lead Redesign

**Date:** 2026-07-31
**Status:** Design approved, ready for implementation plan
**Scope:** `templates/study-detail.html`, `static/study-detail.js`, `lib/study_spec.py`, `lib/study_page.py` (+ CSS in `static/study-detail.*`)

## Problem

The study detail page opens with governance metadata instead of science, and
says the same facts multiple times. Measured against the screenshot in the
brainstorming session:

- **The header stacks seven elements** — title, gate badge, computed-divergence
  chip, a loud yellow readiness banner, a six-axis status stepper, and a "Spine
  at a glance" table — before any content.
- **Three signals are duplicated:**
  - *Readiness/gaps* renders twice — the yellow `#readiness-panel` banner **and**
    the "Spine at a glance" READINESS row, both from the same `/api/report-lint`
    fetch.
  - *Gate/verdict* renders three times — the `gate: passed` badge, the "● Gate
    passed" status chip, and the "Spine at a glance" VERDICT row (which can even
    read `blocked` while the badge reads `passed`, appearing contradictory).
  - *The lead finding* renders two–three times — the "Spine at a glance" WHY row,
    the "Biology — derived from findings" block, and the Findings cards.
- **A "biology lean" that misrepresents non-biological studies.** The Overview
  hardcodes headings like "BIOLOGY — WHAT THIS STUDY IS ABOUT" and "Open
  biological questions," and the Decide tab hardcodes a "biological_validation"
  verdict track — even for a purely **computational** comparison study. Studies
  can be biological, computational, or theoretical; the page assumes biology.

## Primary reader (design frame)

**Lead with the science.** The page's job is to answer *"what did this study
find and how?"* — not *"where does this study stand in the process?"* Status,
readiness, and gating shrink to a single honest line; the tabs carry the
narrative. (Frame chosen over "can I trust this?" and "what's left to do?".)

## Design

### 1. Header — seven elements → three

New header is two rows plus the promoted question:

```
<title>                                         [Reproduce] [Run spec]
● <status>    ⚠ N readiness gaps                                status ▾

Q   <the study's question>
```

- **One status pill** (`● passed`) is the single source for "where does this
  stand." It is the study's `gate_status`, else `_effective_status`.
- **`⚠ N readiness gaps`** is a quiet inline link (not a banner). Clicking
  expands the gap list. The `/api/report-lint` result now feeds exactly one
  place. When there are zero gaps, show a quiet `✓ ready` instead.
- **`status ▾`** is a disclosure holding the full audit trail on demand: the
  six-axis stepper (Design / Implementation / Simulation / Evaluation / Gate /
  Expert review) and the computed-vs-authored divergence chip. Hidden by default.
- **"Spine at a glance" is deleted.** Its three rows had no unique content:
  Verdict = the status pill, Why = the lead finding (shown in Overview →
  Findings), Readiness = the inline gaps link.
- **The Question is promoted into the header** as the page headline, above the
  tab bar, so the page opens with the science rather than governance metadata.
  The full **"Question & Approach"** section is *retained* in Overview (see
  below) — the header carries the one-line question as the headline; Overview
  carries the question plus the approach (expected outcome + mechanism).

Every governance fact now appears exactly once. (The question intentionally
appears as the header headline and again, with its approach, as Overview's lead
section — a headline echo, not a governance duplicate.)

### 2. Study `kind` — remove the biology lean

Add a study-level field **`kind`** with values `biological | computational |
theoretical`.

- **Authored** in the study spec; **defaults to inferred** from the study's
  findings' `kind` values (report-card-derived findings are already tagged
  `computational` in `study_spec.py`). If findings are mixed or absent, default
  to `computational` (the safest neutral default for this workspace) — never
  silently assume `biological`.
- **Rendered as a small tag beside the title** so the reader knows the study's
  nature at a glance.
- **Neutralizes hardcoded biology chrome:**
  - Overview's "BIOLOGY — WHAT THIS STUDY IS ABOUT" section is **removed**
    entirely (redundant with Question & Approach); see Overview below.
  - "Open biological questions" → **"Open questions"** (kind-agnostic).
  - Decide's "Biological validation" verdict-track *label* is renamed to
    **"Empirical validation"** — the honest general term (validation against
    empirical evidence, biological or not), applied universally (not kind-aware).
    The underlying `conclusion_verdicts.biological_validation` data key stays for
    back-compat; only the visible label changes.

### 3. Tabs — 8 pillars stay 8, each redesigned to one job

Narrative order preserved: *what we asked & found → what system → what runs →
what it saves → what the figures show → what the evidence says → the verdict →
the data.* Principles: **(a) each tab owns its facts; nothing is restated across
tabs; (b) strip the explanatory/tutorial paragraphs from every tab** — the
primary reader (frame B) does not need them, and they are pure noise on Model,
Simulations, and Report Cards alike.

**Pillar count drops 8 → 7:** Readouts merges into Model (readouts are a property
of a model — see below and §4); the Model+Interventions+Readouts reframe is
**Increment 2** (§6). Tests' two sub-tabs merge into one concept.

| Pillar | One job | Cut | Enhance |
|---|---|---|---|
| **Overview** | The answer, one screen | The **entire** "Biology — what this study is about" block (both the auto-derived restatement *and* the standalone heading — redundant with Q&A above it and visually sloppy); the counts strip | Keep **"Question & Approach"** as the polished, enforced lead section (see §5) — three color-coded cards (Question / Hypothesis-Expected outcome / Mechanism-Model change). Fold an authored `biological_summary` in as a **matching fourth "Summary" card**, never its own section. Then Findings → Conclusion. |
| **Model (+Readouts)** | What runs, and what it records | The explanatory paragraph; **Analyses** (→ Exports); the redundant "Config that runs" vs "Conditions/Baseline" split | **Increment 2 (§6).** One **Runs** list of composite/config pairs (baseline first; interventions add pairs), each showing its **emitter + ●saved/○excluded readouts**; **interventions** (merge/override) replace `variants`; a "needs a value" callout. Absorbs the Readouts pillar. |
| **Simulations** | The record of what ran | **All** run controls — Configure-&-Run, "Run on remote (smsvpctest)", run-protocol, CLI-reproduce card, and the "Simulation set (planned)" cards; both explanatory paragraphs | A **single read-only table**, one row per run: model/intervention, simulation time, seeds, status, **where the data lives**, **how to retrieve it**, **download**. Launching moves entirely to the header buttons. |
| **Visualizations** | What the figures show | The "VISUALIZATIONS" explanatory paragraph; the three subsection headings (Baseline analysis gallery / Embedded visualizations / Latest-run charts); the verbose empty-state sentence | **Just the figures** — one continuous gallery merging the three mounts, no section chrome. Minimal quiet empty state (not a tutorial). Per-figure captions stay but muted. |
| **Tests** | The study's audit — did it pass its own bar | The explanatory paragraph; **the two sub-tabs** | **Merge Report Cards + Behavioral Tests into one tab and one concept** — a single unified list of graded checks, led by the **gate/audit summary** (which checks gate the verdict, and pass/fail). No sub-nav. |
| **Decide** | The reasoned verdict + what's next | The "VERDICT & CONCLUSION Synthesises…" paragraph and the "Each track is independent…" explainer | **Increment 1:** rename "Biological validation" → **"Empirical validation"** (§2); strip prose. **Increment 3 (§6):** transparent verdict inputs (show the actual run-status / gate-evaluator + report-cards / finding-tier values feeding each PASS/PARTIAL/PENDING, not "computed from X" text); follow-ups **always propose ≥1** derived study, seedable, enforced by a `missing_followup` gap. |
| **Exports** | Download artifacts | — | Gains the **Analyses** config (relocated from Model), co-located with the analysis outputs it produces. |

### 4. Readouts (merged into Model — Increment 2) — detail

Job: *"what a model records, and what it deliberately does not."* Readouts are a
property of a model (a composite has an observable surface; its emitter selects
what is saved), so they render **per-model inside the Model tab's Runs list**,
not as a standalone pillar. Today the old Readouts tab only shows what **is**
saved, as a long flat list; the excluded set is invisible, so a reader cannot
tell whether an omission was deliberate.

Per-model **Records** subsection, top to bottom:

1. **Selected emitter** — the emitter name + type for that model.
2. **● Saved** — the observables that will be written (store path + authored
   name + units), browsable rather than flat.
3. **○ Not saved** — the rest of that composite's observable surface that is
   *available but excluded* from the emitter selection.

Interaction (read-only for this iteration):

- Grouped by store path as a **collapsible tree** rather than one flat list.
- **Searchable / filterable** by path or name.
- ●saved / ○excluded state obvious at a glance (glyph + styling).
- **No write path.** Toggling an observable in/out of the emitter (which would
  rewrite the emitter config and commit to the study) is explicitly **out of
  scope** for this iteration and deferred.

**Data dependency:** rendering ○excluded requires the composite's *full*
observable surface (available) minus the emitter's selection (saved). The
"available" surface comes from the composite's observable enumeration
(`lib/observables_views.py` / `_observables_for_ref`); "saved" comes from the
emitter config. The implementation plan must confirm the available-surface
source can be computed for a study's baseline composite and reconcile it against
the saved set (set difference on resolved store paths).

### 5. Enforce "Question & Approach"

The "Question & Approach" section is the study's science lead and must not be
skippable. Enforce it:

- The **report linter** (`/api/report-lint`, `lib/report_views.py`) gains a
  deterministic gap when a study has no question (and no approach /
  expected-outcome). Surfaces in the header's `⚠ N gaps` link like the existing
  `incomplete_summaries` / `missing_readouts` findings.
- The gap keys are stable slugs (e.g. `missing_question`) so the header link and
  any CI over the linter can reference them.
- This is a **soft gate** (a readiness gap), consistent with the other linter
  findings — it flags, it does not block save. No new hard validation error.

### 6. Interventions & the unified Model tab (Increment 2)

The Model-tab reframe is large enough to be its own spec+plan increment. Its
design decisions, settled here so nothing is lost:

- **Runs list.** The redundant "Config that runs" (resolved params) and
  "Conditions/Baseline" (composite + override chips) collapse into **one** list
  of `(composite, resolved config)` pairs that execute — the baseline is pair 1.
  Each row shows the composite address (explore & run), a collapsible resolved
  config table (with override markers), and the per-model **Records** subsection
  (§4: emitter + ●saved/○excluded).
- **Interventions** author the additional pairs. An intervention is
  `base composite + operation + operand`, where **operation ∈ {merge, override}**:
  - `merge` — compose another composite subtree into the base (structural).
  - `override` — apply parameter overrides (parametric).
- **Interventions replace `variants`.** They are the typed successor; existing
  loose `variants` migrate to `override` interventions (a bare param-variant
  `{name, params}` → `{name, base: <baseline>, op: override, operand: <params>}`).
- **"Needs a value"** callout retains the one genuinely-unique bit of the old
  Conditions block: `model_settings` still lacking a human-set value.
- Requires process-bigraph merge/compose semantics to resolve a `merge`
  intervention into a runnable variant composite — the Increment 2 plan must
  confirm the available primitive (templates/compose in process-bigraph).

### 7. Verdict transparency & follow-up enforcement (Increment 3)

Settled scope (the user chose **transparent inputs only** for verdicts — *not*
rule-redefinition, *not* gate-coupling — and **derive-and-enforce** follow-ups):

- **Transparent verdict inputs.** Each of the three tracks (Regression
  compatibility · Empirical validation · Explanatory gain) shows the *actual
  values* that produced its PASS/PARTIAL/PENDING — run status; gate-evaluator
  result + which report cards; finding-tier counts — replacing the vague
  "computed from X" captions. **The computation rules are unchanged**; this is
  presentation + honesty, not new logic. No new gate coupling.
- **Follow-ups always propose ≥1.** The Follow-ups & Decisions section derives at
  least one concrete follow-up study from the verdict state + open findings /
  epistemic debts (e.g. Empirical = PENDING → a validation study; an open debt →
  a study that closes it). Each proposal is seedable (new study) or linkable
  (existing). Enforced by a **`missing_followup`** readiness gap (sibling of
  `missing_question`, §5) when none is present.

**Increment split:**
- **Increment 1 (declutter — regenerate this plan):** header, `kind`, de-biology
  Overview, enforce Question & Approach, Simulations→read-only table,
  Visualizations single gallery, Tests merge-to-one-concept, **Empirical
  validation** rename, strip explanatory prose from every tab. Includes the
  backend **readouts excluded-set** (feeds Increment 2's per-model Records).
- **Increment 2 (separate spec+plan):** the unified Model tab — Runs list,
  interventions (merge/override, replacing variants + migration), per-model
  emitter+readouts, Analyses→Exports relocation, and the 8→7 pillar change.
- **Increment 3 (separate spec+plan):** Decide — transparent verdict inputs and
  derive-and-enforce follow-ups (`missing_followup`).

## Out of scope

- Editable/interactive emitter selection (Readouts write path) — deferred.
- Any change to `runs.db` or the composite model itself. (Increment 2 *does* add
  intervention resolution via existing process-bigraph compose primitives — no
  new run-subsystem behavior beyond producing variant composites to run.)
- Restructuring the SPA investigation-detail view (`walkthrough.js`) — this
  redesign is the standalone `study-detail` page only.
- Renaming pillars. Pillar **count** drops 8 → 7 (Readouts merges into Model);
  no pillar is renamed or reordered.
- **Redefining the verdict computation rules** or coupling the combined verdict
  to the header gate — explicitly deferred (Increment 3 does transparency only).

## Success criteria

- Header shows each of {status, readiness, verdict} **exactly once**; the yellow
  readiness banner and "Spine at a glance" table are gone; the six-axis stepper
  is behind `status ▾`.
- The study's Question is the first content on the page, above the tabs.
- A `computational` (or `theoretical`) study shows **no** "Biology" headings and
  carries a visible `kind` tag.
- Overview has **no** "Biology / What this study is about" section; an authored
  `biological_summary` appears only as a matching "Summary" card inside
  "Question & Approach" (no auto-derived restatement of findings anywhere).
- "Question & Approach" is the enforced lead section of Overview; a study with
  no question surfaces a deterministic `missing_question` readiness gap.
- **Increment 1:** Simulations is a single read-only table of runs (time, seeds,
  status, location, retrieval, download) with **no** run/launch/remote controls;
  launching is header-only.
- **Increment 1:** Tests is one merged concept (Report Cards + Behavioral Tests),
  no sub-nav, led by the gate/audit summary.
- **Increment 1:** every tab's explanatory/tutorial paragraph is removed.
- **Increment 2:** the Model tab shows one Runs list of composite/config pairs,
  each with its emitter + ●saved/○excluded readouts; interventions (merge/override)
  author the extra runs and replace `variants`; the Readouts pillar is gone (7
  pillars total).
- **Increment 3:** each verdict track shows its actual computed inputs; the
  "Empirical validation" label replaces "Biological validation"; the Follow-ups
  section always shows ≥1 proposed study and fires `missing_followup` when empty.
- No fact rendered in the header is also rendered verbatim in a tab.
