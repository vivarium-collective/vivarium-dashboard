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
  - Decide's "biological_validation" verdict-track *label* becomes kind-aware
    (e.g. "biological validation" only for `biological`; otherwise a neutral
    "domain validation"). The underlying three-track structure
    (regression / domain / explanatory) is unchanged — only the label text.

### 3. Tabs — 8 pillars stay 8, each redesigned to one job

Narrative order preserved: *what we asked & found → what system → what runs →
what it saves → what the figures show → what the evidence says → the verdict →
the data.* Principle: **each tab owns its facts; nothing is restated across
tabs.**

| Pillar | One job | Cut | Enhance |
|---|---|---|---|
| **Overview** | The answer, one screen | The **entire** "Biology — what this study is about" block (both the auto-derived restatement *and* the standalone heading — redundant with Q&A above it and visually sloppy); the counts strip | Keep **"Question & Approach"** as the polished, enforced lead section (see §5) — three color-coded cards (Question / Hypothesis-Expected outcome / Mechanism-Model change). Fold an authored `biological_summary` in as a **matching fourth "Summary" card**, never its own section. Then Findings → Conclusion. |
| **Model** | What system was simulated | "Implementation requirements" moves into the collapsed "Plan & provenance"; "Model change" hidden when empty | Lead with the interactive composite card, then Conditions as a clean table |
| **Simulations** | What runs executed + how to run more | The in-tab Reproduce card (duplicate of the header button) | Runs table leads; fold the scattered run controls (Configure-&-Run widget, remote-run form, sweep summary) into **one** "Run" panel below the table |
| **Readouts** | What this study observes | The flat wall-of-paths list | See §4 — selected emitter + ●saved / ○excluded, browsable, **read-only** |
| **Visualizations** | What the figures show | Three separate mounts (native gallery / embedded HTML / latest-run charts) as distinct sections | Merge into **one** figure gallery |
| **Tests** | The study's audit — did it pass its own bar | — (keep both sub-tabs) | Lead with the **gate result**: which report cards / behavioral tests gate the verdict and which passed/failed, so the audit is legible at the top rather than reconstructed from a list. Report Cards + Behavioral Tests stay as sub-tabs. |
| **Decide** | The reasoned verdict + what's next | — | Kind-aware verdict-track label (§2); keep three-track reasoning + conclusion logic + follow-ups (this is the depth behind the header's one-word verdict) |
| **Exports** | Download artifacts | — | Unchanged. Readouts is **not** merged in — the observables surface is a first-class concern (§4). |

### 4. Readouts redesign (read-only) — detail

Job: *"what this study observes, and what it deliberately does not."* Today the
tab only shows what **is** saved, as a long flat list; the excluded set is
invisible, so a reader cannot tell whether an omission was deliberate.

New surface, top to bottom:

1. **Selected emitter** — the emitter name + type chosen for this study.
2. **● Saved** — the observables that will be written (store path + authored
   name + units); the current tab's content, but browsable rather than flat.
3. **○ Not saved** — the rest of the composite's observable surface that is
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

## Out of scope

- Editable/interactive emitter selection (Readouts write path) — deferred.
- Any change to the run subsystem, `runs.db`, or the composite model itself.
- Restructuring the SPA investigation-detail view (`walkthrough.js`) — this
  redesign is the standalone `study-detail` page only.
- Reordering or renaming pillars (8 stay 8, names unchanged).

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
- Readouts shows the selected emitter and both ●saved and ○excluded observables
  in a searchable, collapsible tree.
- Tests leads with the gate result.
- No fact rendered in the header is also rendered verbatim in a tab.
