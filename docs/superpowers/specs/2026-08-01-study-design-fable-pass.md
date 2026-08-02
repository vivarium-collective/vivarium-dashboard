# Study Detail — Whole-Page Design Pass (Fable)

**Date:** 2026-08-01
**Status:** Design proposal, ready to split into implementation increments.
**Revision:** **v2 — audit-grade** (§9–§14, appended). v2 supersedes §1 (conceptual model),
§3 (tab order/act labels), §4.6 (Tests), §4.7 (Decide), §4.8 (Exports) and §6 (increments);
those sections are kept intact below and carry a pointer to their v2 replacement. Sections
§2 (rendering rules), §4.1–§4.5 and §5 (Readouts) are unchanged and still hold.
**Builds on:** `2026-07-31-study-page-declutter-design.md` (shipped Increment 1). Nothing
here undoes that work; §6/§7 of that doc (deferred increments 2 and 3) are absorbed and
re-shaped by this one.
**Scope:** `templates/study-detail.html`, `static/study-detail.js`, `static/sim-table.js`,
`lib/readouts_views.py`, `lib/study_derivations.py`, `lib/composite_runs.py` (read-only
reuse), plus a new `static/study-detail.css`.

---

## 1. The conceptual model — what a study *is*

> **⚠ Superseded by §9 (v2).** The three-act spine below is correct but incomplete: it has
> no place for *assurance* (criteria, review, severity, waivers) and treats the verdict as
> an opinion rather than an authorized act. §9 revises the thesis and the act structure.
> §1.1 (the incoherence audit) is unchanged and still holds.

> **A study is one question, answered once, with a receipt.**

Everything on the page is one of four things: the **question**, the **apparatus** built to
answer it, the **evidence** the apparatus produced, or the **judgment** passed on that
evidence. The eight tabs are not eight topics — they are three acts plus a front page and
a receipt drawer:

```
                         ┌──────────── Act I ────────────┐ ┌─────── Act II ───────┐ ┌ III ┐
   Overview      │        Model      Readouts             │  Simulations  Figures  Tests  │  Decide  │  Exports
   ─────────     │        ─────      ────────             │  ───────────  ───────  ─────  │  ──────  │  ───────
   front page    │            THE APPARATUS               │       THE EVIDENCE            │ JUDGMENT │ RECEIPT
   (ask+answer)  │      what will run · what it records   │  what ran · what it looked    │ verdict  │ artifacts
                 │                                        │  like · whether it passed     │ + next   │
                 │        authored BEFORE the run         │      produced BY the run      │  after   │
```

Read the tab bar left to right and you get a sentence:

> *We asked X* (Overview) · *we built this model* (Model) · *wired to record these
> quantities* (Readouts) · *ran it these times* (Simulations) · *here is what came out*
> (Visualizations) · *judged against this bar* (Tests) · *so the verdict is Y and next we
> do Z* (Decide) · *and here are the files* (Exports).

Three properties make this a *spine* rather than a list:

1. **Act I is a plan; Act II is a record; Act III is an opinion.** Every panel belongs to
   exactly one of those epistemic modes. A panel that mixes them (today: Overview's "Plan
   & provenance," Decide's "Evidence") is the source of most of the page's confusion.
2. **Each act is caused by the one before it.** Readouts exist *because* tests and figures
   need them; runs exist *because* a model was declared; verdicts exist *because* tests
   graded runs. Every adjacency in the tab bar should carry a visible one-line bridge
   (§5), not just a boundary.
3. **Overview is not a tab — it is the abstract.** It restates the question and the answer
   and nothing else. Anything in Overview that is not *the question* or *the answer*
   belongs to the act that owns it.

### 1.1 Where the current page violates the spine

Found by reading the template + the rendered tabs:

| # | Incoherence | Where |
|---|---|---|
| A | **Overview is doing three jobs.** "Plan & provenance" (`study-detail.html:503–673`) holds pipeline gate, key assumptions, a behavioral-test *count* strip, a follow-ups *pointer*, literature anchors, pre-run expert questions, limitations, and a Status echo — five of which are owned by other tabs. Overview simultaneously carries Act I (plan), Act III (findings, conclusion, confidence) and governance. | Overview |
| B | **Readouts sits after Simulations**, implying readouts are a property of run *output*. They are a property of the *plan*: `study_runs.run_study_baseline` computes `emit_paths = collect_emit_paths_from_spec(spec)` *before* launching (`lib/study_runs.py:398`), and the emitter is injected into the composite state tree as a Step (`composite_runs.inject_emitter_for_declared_paths:976`). The instrument is part of the apparatus. | tab order |
| C | **The same composite is rendered twice on Model** — once as `#model-section` from `study.baseline` (`:693–735`) and again as `#conditions-section → Baseline` from `study.conditions.baseline` (`:748–760`), same ref, same params. | Model |
| D | **Tests states its gates twice, verbatim.** `_renderTestsGateSummary` (`study-detail.js:1413`) and the behavioral list (`study-detail.html:1078`) read the *same* `latest_outcomes` over the *same* test list. A third copy of per-test results is injected by `_renderComputedOutcomeRow` (`:1593`). | Tests |
| E | **Decide re-derives evidence that Tests owns** ("Latest run outcomes" → outcome_rollup → "canonical on the Tests tab →", `:1277–1298`). A block whose content is a pointer is noise. | Decide |
| F | **Three near-identical download surfaces** over one `/api/simulations` payload: `#readouts-download` (Readouts), `#raw-data-list` (Exports), and `_showRunDetail`'s action row (Simulations). | 3 tabs |
| G | **Follow-ups live in two families in two shapes** — authored `follow_up_studies` and discovered `discovery_implications.followup_study_proposals` — rendered as two separate sections with two different card styles and two different seed buttons. | Decide |
| H | **The second tab row is dead.** Every pillar has exactly one member, so `_showPillarSubnav` (`study-detail.js:22`) always hides `#study-subnav`. The whole two-level nav is vestigial. | nav |
| I | **~750 lines of dead JS** (baseline/variant/intervention CRUD, the entire remote-run subsystem, `_seedFromFinding`, `#status-select`) and a `<script src="/progress-track.js">` include that exists only for dead code. | JS |

---

## 2. Cross-cutting rendering rules (the aesthetic spine)

These are worth more than any single tab's restructure, because they fix the same class of
ugliness in eight places at once. Adopt them as page-wide invariants.

**R1 — Never render a raw Python dict or JSON blob in the default view.**
Current violations, all visible in the shipped UI:
- `study-detail.html:880–885` — `model_change.modified_processes` entries are dicts
  `{name, why, status, requirement_id}` rendered through `{{ m }}`, producing a literal
  Python repr with escaped `\n` inside the page. This is the single ugliest artifact on
  the page.
- `:411` — `f.evidence.observed` renders `{'n1': 73.6, 'n2': 73.2, …}` inline on every
  finding.
- `:427` — `pass_if | tojson` renders `{"op": "ratio_at_most", "ratio": 2.0}` inline.
- `:1125–1129`, `:1135` — assertion / calibration-anchor `<pre>` JSON (acceptable: these
  are already inside `<details>`).

Fix: two small formatters, used everywhere.
- Jinja filter `humanize_assertion` → `ratio_at_most/2.0` renders as **`ratio ≤ 2.0`**;
  unknown ops fall back to `op(args)`, never raw JSON.
- Jinja macro `kv(mapping)` → a two-column micro-table, used inside a `<details>`; the
  *outside* summary shows a scalar reduction (`n=4 · median 73.4 · spread 0.6`) computed
  in the template, not the mapping.
- A `|is mapping` guard on **every** `{{ item }}` inside a `for` over a spec list. Grep
  target: any loop body that prints the loop variable bare.

**R2 — Absent ≠ empty.** A computed set that could not be computed must not render as an
empty set. Every derived collection carries a three-state marker: `computed` / `empty` /
`unavailable(reason)`. Today `readouts_views` returns `excluded: []` for both "nothing is
excluded" and "we could not tell" (`lib/readouts_views.py:253`, `:268`) — those must be
distinguishable states in the payload and in the UI.

**R3 — No dead columns, no empty-state furniture.**
- A table column whose every cell is empty is *dropped*, not rendered as a column of "—".
  Implement once in `sim-table.js` as a generic pre-render pass; it immediately kills the
  empty **Location** and **Emitter** columns on Simulations and the empty **Indexed by /
  Units / Description** columns on Readouts.
- A section with no content renders **nothing** — not an empty-state card. The exception:
  content the study is *expected* to have. Those are readiness gaps, and gaps have exactly
  one home (the header's `⚠ N readiness gaps` link), not an inline box per tab. Today
  Tests renders an empty "Report cards" panel and Visualizations renders "No figures yet."
  above figures that do exist.

**R4 — One fact, one home.** Extends the declutter spec's header rule to the whole page:

| Fact | Home | Everywhere else |
|---|---|---|
| status / gate / readiness / phase | header | nowhere |
| the question | header headline + Overview lead | nowhere |
| composite + resolved config | Model | Readouts + Simulations show the *ref* as a link only |
| emitter + what is recorded | **Readouts** | Simulations shows emitter only as a *deviation* flag |
| per-run facts (time, seeds, status, location) | Simulations | Findings/Decide link by `run_id` |
| test results | Tests | Findings link by test name; Decide shows the rolled-up count *as a verdict input*, not as a section |
| follow-ups | Decide | nowhere |
| assumptions / limitations | Decide (scope of the claim) | nowhere |
| downloads | Exports | Simulations row detail may link to Exports |

**R5 — Style belongs in CSS.** The template carries **163 inline `style="…"` attributes**,
many hardcoding light-theme colors (`#fff`, `#f8fafc`, `#1e293b`). `style.css` has 327
`:root[data-theme="dark"]` rules that these inline styles override — so the study page is
materially broken in dark mode, and no per-tab redesign can fix that from inside the
template. Extract to `static/study-detail.css` with the existing token vocabulary
(`var(--surface)`, `var(--border)`, `var(--text-muted)`) as the enabling refactor for
everything below.

**R6 — Cross-act links must actually navigate.** Findings link to `#bt-<test>` and
`#run-<id>` (`:412`, `:413`, `:422`) which live in `hidden` panels — an anchor into a
hidden section does not scroll. Every cross-tab link goes through one helper
`_gotoStudyTab(kind, anchorId)` that switches the tab, then scrolls, then flashes the
target. (`_applyRunHash` at `study-detail.js:2401` already does this for `#run-…`; make it
the general mechanism.)

---

## 3. Tab order & navigation

> **⚠ Act labels superseded by §9.3.** The recommended tab *order* is unchanged; the act
> grouping gains a fourth act (Assurance) and a fifth (Decision).

**Recommended order:**

> **Overview · Model · Readouts · Simulations · Visualizations · Tests · Decide · Exports**

Readouts moves from position 4 → 3 (between Model and Simulations), per the user's
direction, and the reasoning is now first-class: **Readouts is the last thing you decide
before you press Run.** It closes Act I. Its inputs (`readouts[]`, `tests[].measure.path`,
`visualizations[].inputs_map`) are all authored, and its output (`emit_paths`) is consumed
by the launch. Placing it after Simulations mis-taught the causality.

**Navigation changes:**

1. **Delete the second tab row.** `#study-subnav` is always hidden (§1.1-H). Remove it,
   remove `_setStudyPillar` / `_showPillarSubnav` / `_pillarForKind`, and let
   `.study-pillar` buttons drive `_setStudyTab` directly. Saves a DOM row, ~45 lines of JS,
   and the entire pillar/member mental model.
2. **Use the freed row for act labels.** A hairline group label above the tabs — the single
   highest-leverage "conceptual aesthetic" change on the page, because it makes the
   narrative visible without adding a sentence:

```
   ┌ THE STUDY ┐ ┌──── THE APPARATUS ────┐ ┌───────── THE EVIDENCE ─────────┐ ┌ THE VERDICT ┐   │
     Overview      Model      Readouts       Simulations  Visualizations  Tests    Decide       │  Exports
```

   Act labels are `0.68em`, uppercase, `letter-spacing:.08em`, `var(--text-muted)`, with a
   1px rule spanning their group. Exports sits after a wider gap, right-aligned — it is
   outside the narrative (a drawer, not a chapter).
3. **Keep deep links.** `?tab=<kind>` (`study-detail.js:1969`) and `#run-<id>` keep working;
   add `?tab=readouts#path=<store.path>` for linking a finding or test to the exact readout
   it measures.

---

## 4. Per-tab redesign

### 4.1 Overview — *"What we asked, and what we found."*

**One job:** the abstract. A reader who reads only this tab should be able to state the
question, the answer, the confidence, and what is still open.

**Cut**
- The whole **"Plan & provenance"** wrapper (`:503–673`) — dissolve it, relocating each
  child to its owning act (table below). It is the single biggest Overview win.
- **Status** subsection (`:663–671`) — verbatim duplicate of the header pill.
- **Behavioral tests** count strip + "View on Tests tab →" (`:539–557`) — a count is not a
  finding; Tests owns it.
- **Follow-up studies** pointer block (`:619–629`) — a section whose entire content is
  "the canonical surface is the Decide tab."
- The `computed from findings` **conclusion-insight line** (`:480–485`) whenever it equals
  `findings[0].statement` verbatim, which is every time `report.main_insight` is unset.
  Render only when `main_insight` is authored *and* differs from the lead finding.

**Relocate**

| From Overview | To | Why |
|---|---|---|
| `pipeline_gate` (prereqs / enables / proceed-when) | **Decide**, as "What this gate unblocks" | it is a consequence of the verdict, not a plan |
| `key_assumptions`, `limitations` | **Decide**, as "Scope of the claim" | they bound the verdict |
| `literature_anchors` | **Tests**, as "Expectations" | they are the bar the tests encode |
| `expert_decisions_needed` | **merge into Open debts** (stay on Overview) | see below |

**Restructure**

1. **Findings become a compact ledger.** Today each finding is a stack of six boxes
   (`:395–447`) dumping raw dicts. New shape — one row, expandable:

```
   ✓  Daughter cells hydrate within one tick of division              ×1.02 vs expected   [test: daughters_hydrated ↗]  ▸
   ◐  Two-generation completion is media-dependent                    2 of 3 conditions   [test: two_generations ↗]     ▸
```

   Row = status glyph · claim (`f.statement`, one line, clamped to 2) · **one** evidence
   chip · the cited test as a real cross-tab link (R6) · a disclosure caret. Everything
   else — `observed` (as a `kv` table, R1), `pass_if` (as `ratio ≤ 2.0`, R1), `expected`,
   `Reference says`, `explanation`, expert quote, `next_action`, `provenance.run_ids` —
   lives inside the drawer. The evidence chip is chosen by precedence:
   `divergence_factor` → `observed` scalar+units → `observed` reduction (`n=4 · median X`)
   → the run count. Never a mapping.

2. **Open debts absorbs `expert_decisions_needed`.** Both answer "what does this study not
   yet know?" — the collector-derived debts (`epistemic_debts`) and the authored pre-run
   expert questions are the same concept at different severities. One list, severity-
   ordered, with a `source` chip (`derived` / `asked: <person>`). Removes a whole
   ~45-line section (`:559–604`) and its biology-flavored explainer paragraph.

3. **Final Overview order:** Question & approach (3 cards, unchanged — they work) →
   Findings ledger → Conclusion (full-width markdown, keep the recent win) → Open debts.
   Findings before Conclusion; debts last, because they are the hand-off to the next study.

**Links out:** every finding row → Tests (its gate) and Simulations (its runs).

---

### 4.2 Model — *"What runs."*

**One job:** describe the runnable system — one card per thing that will execute.

**Cut**
- The `MODEL COMPOSITION` h2 (`:685`) — the tab is named Model.
- The Conditions explainer (`:745`), the model-settings explainer (`:801`), and the
  implementation-requirements explainer (`:893`).
- **The duplicate baseline** (§1.1-C): `#conditions-section → Baseline` (`:748–760`) is the
  same composite the Model section already showed.
- `"No resolvable configuration for this composite."` as an error-shaped sentence for the
  normal unregistered-composite case (`study-detail.js:355`). Replace with a neutral
  state: *"Config resolves at run time — this composite isn't registered in this
  workspace."*

**Fix (raw-dict bug, R1)** — `modified_processes` (`:880–885`). Render each entry as a
card matching `new_processes`: `<code>{{ m.name }}</code>` · status chip · `req:`
link · `why` with newlines as paragraphs. Keep a string fallback for legacy prose entries.

**Restructure**

1. **One "Runnable models" list.** Each row is a `(composite, resolved config)` pair —
   baseline first, variants nested beneath the base they perturb (variants inherit the
   baseline row's config table and show only their delta). Per row:
   - composite ref + `🧬 explore & run ↗`
   - the resolved-config table (`_renderModelConfig`, which already marks overrides with a
     blue row + chip — keep, it's good), collapsed by default when ≥ 8 params
   - `⚠ needs a value` chips for `model_settings` with `gate: required-before-run` —
     inline on the row, replacing the standalone Model-settings table's "required" badge
   - **the bridge line to Readouts:** `Records 12 of 431 observables via parquet →`
2. **Model settings** stay as an editable table but move *below* the runnable models under
   the heading **"Settings awaiting a value"** — filtered to rows whose `current` is unset
   when any exist, full table behind "show all N". Their purpose is to be filled, not
   browsed.
3. **"What this study changes about the model"** — a clearly separated, collapsed section
   holding `model_change` + `implementation_requirements`. These describe work to be
   *built*, not a system that *runs*; they stay on Model (they gate Design→Build, which is
   Act I) but must not compete with the runnable model for the top of the tab.
   Implementation requirements render as a **checklist** (`id · title · effort · unblocks`)
   rather than N nested `<details>` blobs.

---

### 4.3 Readouts — *"What the run will record."* → see the deep dive in §5

Summary of its place in the spine: Readouts is the **instrument**. It closes Act I by
answering the only remaining pre-run question — *of everything this model contains, what
will survive the run?*

---

### 4.4 Simulations — *"What actually ran."*

**One job:** the ledger of executions. Already the cleanest tab post-declutter; the fixes
are about honesty, not volume.

**Cut**
- The dead **Location** and **Emitter** columns (R3). Note the precise cause before fixing:
  `sim-table.emitterPill` reads `row.emitter_type` (not `row.emitter`) and defaults to
  `"SQLite"` when falsy (`sim-table.js:27–34`), so a literal `—` means the resolved tag was
  `none` — `_EMITTER_LABEL` maps `"none" → "—"` (`lib/simulations_index.py:1247`). The rows
  are genuinely untagged, not mis-rendered. Two-step fix:
  1. *(cheap, generic)* drop any all-empty column in `sim-table.js` before render;
  2. *(the real fix)* populate them — the run **manifest already records both**
     (`composite_runs.build_run_manifest:250–252` stores `emitter` and `emit_paths`;
     `run_index._parse_manifest:78` already reads manifests). Add `manifest.emitter` to the
     `_emitter_for_row` resolution chain (`lib/simulations_index.py:890` →
     `emitters.label_for_run:230–269`) ahead of the disk probe, and source location from
     `.pbg/runs/<run_id>/` when `store_path`/`db_path` are absent.
- `#readouts-download` and the run-detail download row are two of three duplicate download
  surfaces (§1.1-F). Keep the download affordance here **only** as a per-row `⬇` in the
  detail panel; the *list* of downloads belongs to Exports alone.

**Restructure**
1. **A one-line ledger header** above the table, from data already loaded:
   `6 runs · 4 completed · 1 failed · latest 2026-07-27 14:02 · 2 on a stale spec`.
2. **Stale-run flag.** `run_index.replay_params(row)` + `row_seed(row)` already give a
   run's recorded params; diff against the current spec's resolved params and mark rows
   whose manifest no longer matches (`⟳ spec changed since this run`). This is the single
   most decision-relevant fact about an old run and it is currently invisible.
3. **Emitter column becomes a deviation flag** once Readouts owns emitter identity: show
   nothing when a run used the study's declared emitter; show an amber `emitter: ram
   (declared: parquet)` chip when it did not.

---

### 4.5 Visualizations — *"What it looked like."*

**One job:** figures, with nothing between the reader and them.

**Fix (bug)** — the empty state is decoupled from the content. `_loadNativeGallery`
(`study-detail.js:270–299`) writes *"No figures yet."* into `#native-gallery-panel`
regardless of the `embed_visualizations` iframes (`study-detail.html:991–1008`) and
`#viz-charts-panel` charts rendered below it, so the tab reads "no figures" directly above
a figure. Fix: compute the empty state **once, after all three sources resolve**, over
their union.

**Cut**
- The `Figures` h2 (tab title), the three source-specific mounts as *visible* groupings,
  and the per-source chrome (embed cards have a header bar + border; native figs have a
  bold label; charts have a `.chart-card`).

**Restructure**
- **One gallery, one card style.** A single `.figure-card` used by all three sources
  (native srcdoc iframes, embedded HTML iframes, inline SVG/PNG charts), flowing in one
  container. Source-of-figure becomes a muted caption chip, not a section heading.
- **Caption every figure with its run** and link it (R6): `from run cf3a12 ↗`. This is the
  Act-II integration link — a figure with no provenance is decoration.
- Empty state: one quiet line, no tutorial.

---

### 4.6 Tests — *"Did it clear its own bar."*

> **⚠ Superseded by §10.** Everything below still applies as the *mechanical* declutter of
> this tab; §10 expands its job from "graded checklist" to the study's assurance record.

**One job:** the graded checklist, stated once.

**Cut (the duplication, §1.1-D)** — the gate summary list and the behavioral list are the
same set from the same source. Merge into **one list led by one score**:

```
   0 / 4 gates passed        ▓▓▓▓░░░░░░░░░░░░  ·  3 pending · 1 failed
   ─────────────────────────────────────────────────────────────────────
   ✗ FAIL   primary      daughters_hydrated        ratio ≤ 2.0 · measured 3.4     ▸
   ⏳ pend   primary      two_generations_complete  requires: baseline_2gen        ▸
   ⏳ pend   supporting   reference_perf_recorded   —                              ▸
```

Also cut:
- The `auto_discover` / `data_source` badges (`:1066–1069`) — implementation trivia; move
  into a `⚙` popover on the Run-tests button or drop.
- The **empty "Report cards"** section box when there are no cards (R3).
- The placeholder tutorial `<li>` (`:1147–1150`).

**Restructure**
1. **Report cards are rows in the same list.** They already are, structurally (`kind:
   report_card`, `:1094–1102`); the separate `#report-cards-panel` heading recreates the
   sub-tab split the declutter removed. Make card-kind rows expand *in place* into the
   rich card (`_renderRichReportCard`, `study-detail.js:1333`) rather than linking "View
   report card ↑" to a section above.
2. **One assertion presentation.** Each row's collapsed line shows the human assertion
   (`ratio ≤ 2.0 · measured 3.4`, R1); the drawer holds the raw `measure`/`pass_if`/
   `given`/`cites` JSON, the calibration anchor, and the computed-outcome row
   (`_renderComputedOutcomeRow`) — which today injects a *third* copy of the result into
   the row body.
3. **`literature_anchors` land here as "Expectations"** — the published expectation, the
   model observable it maps to, and the test that checks it. This makes Tests the single
   home of *the bar* (both the number and where the number came from), and gives the
   `cites:` field on each test somewhere to point.

---

### 4.7 Decide — *"The verdict, and what's next."*

> **⚠ Superseded by §11.** The three-beat restructure below holds; §11 makes the verdict an
> *authorized* act (actor, basis, sign-off) rather than a free-form opinion.

**One job:** the judgment and its consequences. Currently the heaviest tab: three verdict
rows each with a 2-row textarea, two large if-pass/if-fail boxes, a conclusion blob, an
Evidence pass-through, discovery implications, and two separate follow-up families.

**Cut**
- **"Evidence → Latest run outcomes"** (`:1274–1299`) — its body is a rollup plus "canonical
  on the Tests tab →". The rollup survives as a *verdict input* (below); the section does not.
- The **non-v3 branches**: the `Claims + Evidence` synthesis (`:1300–1333`) and the
  `Limitations & provenance` collapsed shell (`:1499–1533`). Audit whether any v2 study
  remains; if not, delete both branches and the `_is_v3` conditional with them.
- The two explainer paragraphs the declutter already targeted, plus the
  "Click ➕ Add to investigation…" / "Click Seed new study →…" instructions (`:1418`,
  `:1454–1457`) — the buttons say what they do.

**Restructure — three beats**

1. **Verdict.** Three compact cards in a row. Each shows the track, the pill, and — the
   Increment-3 payload, now precisely specifiable because `lib/study_derivations.py:74–118`
   computes them deterministically — **its actual inputs**, replacing the vague
   "computed from run status" captions:

   | Track | Shown input (real values) |
   |---|---|
   | Regression compatibility | `4 of 4 runs completed · 0 errored` |
   | Empirical validation | `gate evaluator: needs_calibration · 0/4 gates passed` |
   | Explanatory gain | `3 findings · 1 interpretation-tier` |

   The `basis` textarea collapses to a one-line editable caption under the pill that
   expands on focus — three 2-row textareas stacked is what makes this tab read as a form.

2. **Conclusion.** The full-width markdown blob (recent win, keep) — and **fold
   `conclusion_logic` into it as a pre-registration line**, not two large colored boxes:

   > *Pre-registered: primary tests pass → unblocks `study-3`, `study-4`; fail → block
   > downstream, diagnose (3 checks) ▸*

   Rationale: an if-pass/if-fail rule is only *interesting* when it contradicts the actual
   verdict — so render it compactly, and highlight it (amber) only on contradiction.
   Directly beneath: **"Scope of the claim"** — `key_assumptions` + `limitations` relocated
   from Overview. They exist to bound the verdict, so they belong to it.

3. **Next.** **One** follow-up list (§1.1-G), merging authored `follow_up_studies` and
   discovered `followup_study_proposals` (already de-duplicated by id at `:1420`), one card
   style, one seed button, with an `authored`/`discovered` chip as the only distinction.
   Alongside it, `discovery_implications` compresses: `resolved_uncertainties` → a one-line
   `✓ 3 resolved ▸`; `remaining_uncertainties` **route to Overview's Open debts** (they are
   debts) with a link back; `alternate_hypotheses` and `mechanism_update_proposals` stay as
   compact rows.

Also: relocate `pipeline_gate` here as a one-line **"This gate unblocks: `x`, `y`"** under
the verdict — the gate's meaning is a consequence of the verdict, not a plan item.

---

### 4.8 Exports — *"Take the artifacts."*

> **⚠ Superseded by §12.** The consolidation below holds; §12 replaces the informal
> "receipt" with an ordered, attributed audit package.

**One job:** every file this study produced, in one place. The cleanest tab; keep it.

**Restructure (small)**
1. **Become the *only* download surface** (§1.1-F): `#readouts-download` moves out of
   Readouts; the run-detail panel keeps a single per-run `⬇`, and its "⬇ Analysis" button
   links here rather than duplicating the zip.
2. **Add a "receipt" row at the top:** one `⬇ Everything (.zip)` bundling analysis results
   + raw stores + **the run manifests**. The manifest is what makes the bundle a
   reproducible receipt (`build_run_manifest` already records env, seed, emit_paths,
   code_version) and it is currently not downloadable at all.
3. **Retitle the Analyses block** *"Analyses — what produces the files above"* so a config
   input inside a downloads tab reads as cause, not clutter.

---

## 5. Readouts — deep dive

### 5.1 The correction that unlocks this tab

The declutter spec's §4 recorded a Step-0 finding that in this codebase
`available == emitted` (one worker RPC feeds both sides), so the excluded set is
structurally empty and "not read out" needs new emitter machinery.

**That finding is true of `readouts_views.py`, but not of the codebase.** The subset
mechanism already exists and is already used on every study launch:

| Concern | Where | Evidence |
|---|---|---|
| Which paths a study saves | `composite_runs.collect_emit_paths_from_spec(spec)` | `lib/composite_runs.py:888` — unions `readouts[].store_path`, resolver-resolved canonical readouts, `tests[].measure.path`, `behavior_tests[].measure.path`, `visualizations[].inputs_map.*`, `comparative_visualizations[].observable_path`; normalises to slash form; expands each to its `agents/0/…` form |
| Which paths a **composite** declares | `composite_resolve.declared_emit_paths(decls)` ∪ `_actual_emit_paths(state)` | `lib/composite_resolve.py:40`, `:68` — the composite's own `emitters[].paths` plus the paths its actual `*Emitter` step nodes are wired to; embedded into the state doc as `_declared_emit_paths` (`:333`, `composite_state_views.py:296`) |
| Who calls it | `study_runs.run_study_baseline` | `lib/study_runs.py:398` → passed as `emit_paths=` into `launch_into_study` (`:412`); also `:599` for the variant path |
| How the subset is enforced | `composite_runs.inject_emitter_for_declared_paths(state, paths)` | `lib/composite_runs.py:976` — builds an emitter Step wired **only** to those paths (+`global_time`), injected into the composite state tree |
| Fallback when nothing is declared | `run_runner._emit_paths_for` | `lib/run_runner.py:210–217` — `req.emit_paths or cr.all_store_paths(state)`: **an empty declaration means "save everything."** |
| Per-run record | `build_run_manifest` | `lib/composite_runs.py:250–252` — `emitter` + `emit_paths` stored verbatim in `runs_meta.manifest_json` |

There is even a **working UI precedent for the subset picker**: the Composite Explorer's
Outputs panel renders a checkbox list from `state._declared_emit_paths`
(`static/walkthrough.js:2947–2978`) and posts `emit_paths` only when a strict subset is
checked (`:3222–3232`). The Readouts write path, when it ships, should copy that component
rather than invent one.

So `readouts_views.build_study_readouts` compares the structural surface against *itself*
(`lib/readouts_views.py:265`, `_split_saved_excluded(leaves, leaves)`) when the real saved
set is one function call away. **The "not read out" set is real today**, and for a study
that declares readouts it is *most of the surface*.

### 5.2 The backend prerequisite (small)

```python
# lib/readouts_views.py — build_study_readouts
from vivarium_workbench.lib import composite_runs as cr

# The saved set has two authors: the study spec, and the composite itself.
declared = cr.collect_emit_paths_from_spec(spec)          # slash form, agents/0-expanded
declared += composite_declared_emit_paths(ws_root, ref)   # composite_resolve.declared_emit_paths
                                                          #   ∪ _actual_emit_paths(state)
available = _available_observables_for_ref(ws_root, ref)  # dotted form (unchanged)

if declared:
    saved, excluded = _split_saved_excluded(_to_dotted(declared), available["leaves"])
    payload["emit_selection"] = "declared"                # a real subset
else:
    saved, excluded = available["leaves"], []
    payload["emit_selection"] = "total"                   # run_runner saves everything
```

(`StudyReadouts` / `ReadoutRow` in `lib/models.py:1010`, `:1032` gain the new fields;
`emit_is_total` is superseded by `emit_selection` and should be kept as a deprecated alias
for one release.)

Three notes that make this correct rather than merely plausible:
- **Normalisation.** `collect_emit_paths_from_spec` returns slash-form with `agents/0/`
  expansion; `available_observables` returns dotted paths, and `observables_views
  .augment_lineage_aliases` adds lineage-stripped aliases. Compare on
  `_strip_lineage(path.replace('/', '.'))` — the key `_split_saved_excluded` already uses.
- **Declared paths need not exist in the initial state.** `inject_emitter_for_declared_paths`
  deliberately skips validation because listener stores materialise at run time
  (`:976` docstring). So a declared path with no matching structural leaf is a **third**
  category — *declared but not in the structure* — which is exactly the existing
  `not_in_emit_plan` never-fabricate flag. Keep it; it is the honest label.
- **`emit_selection: "total"` is a finding, not a success.** A study that declares no
  readouts, no test measures and no figure inputs saves its entire state tree — including
  `…config.cache_dir`. That deserves a readiness gap (`undeclared_readouts`), sibling to
  the `missing_question` gap from the declutter spec §5.

**Three-state degradation (R2).** `payload.excluded_state`:

| State | When | UI |
|---|---|---|
| `computed` | composite built + `declared` non-empty | full Not-saved band |
| `total_emit` | composite built + nothing declared | band replaced by one callout: *"This study records the entire state tree (431 leaves) — no readout, test or figure declares a path."* + the gap |
| `unavailable` | composite could not build (remote build / no ParCa cache — `lib/readouts_views.py:246`) | Saved band still renders (it is spec-derived and always available); Not-saved band renders **`unknown — composite not built in this workspace`**, never an empty list |

### 5.3 Per-model vs per-run — the organizing principle

**Recommendation: per-model (per study-plan) is primary; runs are a reconciliation strip.**

Reasons, in order of weight:

1. **The emitter is part of the model, literally.** It is injected into the composite state
   tree as a Step node (`user_emitter`, `_type: step`, with `inputs` wiring —
   `composite_runs.py:750`, `:976`). A readout selection is not metadata *about* a run; it
   is a subgraph *of* the model. Rendering it anywhere but next to the model breaks the
   bigraph mental model the whole workbench is built on.
2. **The selection is a pure function of the spec.** `emit_paths` is derived at launch from
   `study.yaml` alone; the launch UI exposes no path picker (Configure&Run was removed in
   the declutter). Every run of a given spec revision therefore records the *same* set —
   a per-run view would be N identical copies. Per-run is a high-cardinality frame over a
   low-cardinality fact.
3. **There is no per-condition readout concept at all.** `readouts:` is a top-level study
   key only (`readouts_views.py:117`, `composite_runs.py:919`, `study_spec.py:92`); the v4
   `conditions:` block carries `baseline`, `variants[]`, `model_settings[]` and **no
   readouts key at any level** (`lib/scaffold_yaml.py:181–197`). Baseline and every variant
   therefore resolve *the same* `emit_paths` (`study_runs.py:398` and `:599` are the same
   call). A per-run or per-variant organizing principle would be inventing a distinction
   the data model does not have.
4. **Per-model is the actionable frame.** The reader's question is "will the run I am about
   to launch record what I need?" — asked *before* running. A per-run frame can only answer
   it retroactively.
5. **But runs are ground truth and can disagree** — a run predating a readout, or launched
   when the emitter resolution changed. Ignoring them would be dishonest.

**One honest caveat to surface in the UI:** the readouts worker resolves its composite from
`baseline[0].composite` only (`readouts_views.py:222–227`). A study whose baselines or
variants point at *different* composites silently shows the first one's surface. Until
per-model readouts exist, the tab must name the composite it is describing
(`Recording surface of <ref>`) and, when the study has >1 distinct composite ref, say so.

So: **plan is the page; runs are the reconciliation.** Three named levels of truth, which
is also the tab's conceptual gift to the reader:

| Level | Source | Meaning |
|---|---|---|
| **Declared** | `study.yaml` via `collect_emit_paths_from_spec` | what this study *asks* to record |
| **Planned** | `runs_meta.manifest_json → emit_paths` | what a given run was *launched* to record |
| **Recorded** | `pbg_emitters.RunReader(store).observables()` | what is *actually in the store* |

Declared is the page. Planned is the reconciliation strip. Recorded is a follow-up
increment (it needs polars in the env worker, so it belongs behind the same RPC seam as
`observables`).

### 5.4 The redesigned tab

```
 ┌─ RECORDER ─────────────────────────────────────────────────────────────────────┐
 │  parquet   ParquetEmitter                                    from study.runtime │
 │  writes → studies/dnaa-4/out/<run_id>/            subsample 1 · batch_size 100  │
 │  ⟳ last 3 runs used this emitter                                               │
 └────────────────────────────────────────────────────────────────────────────────┘

 ● SAVED  12 paths                                            [search…]  [group ▾]
   ▾ cells.*.ecoli.outputs                                                    (6)
       mass                       ← readout · figure:cell_mass
       listeners.mass.cell_mass   ← test:two_generations_complete
       …
   ▾ global                                                                   (1)
       global_time                ← always (tick clock)

 ○ NOT SAVED  419 paths                                                    [show ▸]
   ▸ cells.*.ecoli.config           (23)   parameters — rarely useful as time series
   ▸ cells.*.ecoli.inputs           (31)   wiring
   ▸ cells.*.ecoli.outputs         (188)
   ▸ cells.*.<geometry>             (177)

 ⟳ Reconciliation:  run cf3a12 recorded 12/12 planned · run 9be104 planned 8 (spec has
   changed since) → Simulations
```

**Band A — Recorder.** The tab's missing half. Shows:

- **Emitter name + class + output kind.** The accepted set is defined in one place —
  `lib/emitters.py:32–40`: `_ACCEPTED_EMITTERS = ("xarray", "sqlite", "parquet")`,
  `DEFAULT_EMITTER = "xarray"` (`ram` exists in the broker but cannot be declared).
  `emitters.resolve_contract(name)` (`:47`) yields `output_kind` +
  `output_uri_config_key` — exactly the two facts needed to say *what it writes and where*.
- **A provenance chip naming which level supplied the value.** This is the single most
  useful new fact on the page — "this value is not yours; it comes from the investigation."
  The real chain, with every level worth showing:

  | Level | Read at | Note |
  |---|---|---|
  | composite declares `emitters:` | `run_runner._select_emitter_name:164–183` | **forces `parquet`**, overriding everything below (explorer launch path) |
  | study `runtime.emitter` | `lib/study_runs.py:401` | |
  | investigation `runtime.default_emitter` | `lib/study_run_state.py:33–63` | |
  | workspace `runtime.default_emitter` | `lib/emitters.py:203–227` | |
  | `DEFAULT_EMITTER` | `lib/emitters.py:32` | `xarray` |

- **A trap this band will immediately expose (and should):** `study_runs.py:401` reads
  `runtime.**emitter**` from `study.yaml`, but the study scaffold documents
  `runtime.**default_emitter**` (`lib/scaffold_yaml.py:112–115`) and
  `emitters.default_emitter` reads `default_emitter` from the same block
  (`emitters.py:203–207`). A study authored from the scaffold sets a key the study-run path
  never reads. Fix the reader to accept both (Tier 1, #1b) — and until then the provenance
  chip will read `workspace` for a study that clearly declares its own emitter, which is
  precisely the kind of silent mis-resolution this band exists to make visible.
- **Its config.** Effective values from the emitter class's `config_schema` —
  sqlite `file_path, db_file, subsample, batch_size` (`pbg_emitters/sqlite_emitter.py:293`);
  parquet `out_dir, batch_size(400), flatten_separator, partitioning_keys`
  (`parquet_emitter.py:971`); xarray `out_uri, transducer, view, writer`
  (`xarray_emitter/emitter.py:31`) — defaults muted, overrides emphasised.
  **Honest caveat to render:** the workbench builds the xarray config itself
  (`emitters._xarray_emitter_config:449–492`, where the emit interval
  `transducer.predicate[…].subsample.interval`, `buffer.size` and `writer.buffers_per_chunk`
  live) and the caller-supplied `emitter_config` override is passed as `None` from *every*
  in-repo call site. So today this band shows **effective defaults with no authoring
  surface**. Mark them `default` rather than implying they are configurable, and file
  `runtime.emitter_config` as the follow-up that makes them editable.
- **The write location** — `run_store.zarr_store_path_for_db` (`lib/run_store.py:31`),
  `<out_dir>/parquet` (`emitters.py:707`), or the sqlite `file_path/db_file`. This is the
  same fact Simulations' dead Location column wants (§4.4).

**Band B — Saved**, with the feature that makes this tab *reasoning* rather than a listing:
**each saved path shows why it is saved.** `collect_emit_paths_from_spec` already knows the
source of every path (readout / test measure / figure input / comparative overlay); return
it (`{path, sources: ["readout", "test:two_generations"]}`) instead of discarding it. Then
every row answers "why is this here?" and links to the Test or Figure that demands it —
the Act-I↔Act-II integration the page currently lacks entirely.

**Band C — Not saved**, collapsed, grouped, with a per-group count. Read-only this
iteration; each row carries a disabled-for-now `+ add as readout` affordance so the future
write path has an obvious home.

**Browsing — the three moves that kill the "too long, hard to browse" problem.** (Rendered
today: ~30+ ungrouped rows mixing `cells.a_0.ecoli.config.cache_dir`,
`cells.a_0.ecoli.inputs.agent_id`, `cells.a_0.ecoli.outputs.mass`, `cells.a_0.angle`.)

1. **Collapse the lineage.** `cells.a_0.*`, `cells.a_1.*`, `agents.0.*` → one `cells.*`
   template row with a multiplicity badge. On a colony study this is 3000 rows → 30.
2. **Classify by role.** Derive `role ∈ {state, output, input, config}` from the path
   segments (`.config.` → config, `.inputs.` → input, `.outputs.` → output, else state).
   Default view shows `state | output`; `input | config` collapse behind
   *"show wiring & config leaves (54)"*. Emitting `cache_dir` as a time series is
   meaningless — the UI should say so by default rather than list it as an equal.
3. **Group by store subtree**, two levels deep, collapsible, with counts — plus a search
   box filtering on path and name, and a `group ▾` toggle for `by store` / `by role` /
   `by source` (the last being "show me everything the tests need").

**Columns.** Drop the four dead ones (R3): **Emitted?** (100% "✓ emitted" — the band
*is* the answer), **Indexed by**, **Units**, **Description** (all empty). Units and
description return as *inline muted suffixes on annotated rows only* — an annotated readout
reads `cell_mass · fg — total dry mass`, an unannotated one reads just its path. Annotation
becomes a visible reward instead of four empty columns.

**Also cut:** `#readouts-download` (moves to Exports, §4.8) and the *"How observables tie to
Expected Behavior"* `<details>` explainer (`study-detail.html:964–973`) — Band B's `← test:`
provenance chips now show that relationship as data.

---

## 6. Prioritized changes

> **⚠ Superseded by §14.** Increment A (#1–#8) is **unchanged** — it is purely mechanical.
> Increments B/C/D are re-scoped in §14 to fold in the audit-grade structure.

Ranked by (impact × visibility) ÷ effort. **T** = template/JS only · **B** = backend.

### Tier 1 — high impact, low effort (one small PR each)

| # | Change | Where | Kind |
|---|---|---|---|
| 1 | **Format `modified_processes` as fields, not a Python dict repr** (§2 R1) | `study-detail.html:880` | T |
| 1b | **Accept both `runtime.emitter` and `runtime.default_emitter`** in the study-run path — the scaffold documents one key, the reader reads the other (§5.4) | `lib/study_runs.py:401`, `:602` | **B** |
| 2 | **Drop all-empty table columns generically** — kills dead Location/Emitter on Simulations and Indexed-by/Units/Description on Readouts | `sim-table.js` + `_renderReadoutsTable` | T |
| 3 | **Fix the Visualizations empty-state bug** — compute over the union of all three figure sources | `study-detail.js:270` | T |
| 4 | **Merge the Tests gate summary into the gate list** (one score line + one list) | `study-detail.js:1413` + `study-detail.html:1045` | T |
| 5 | **Readouts: real saved/excluded via `collect_emit_paths_from_spec`** + `emit_selection` / `excluded_state` three-state (§5.2) | `lib/readouts_views.py` | **B** |
| 6 | **Delete `#study-subnav` + the pillar/member indirection** | `study-detail.html:146`, `study-detail.js:17–66` | T |
| 7 | **Delete the ~750 lines of dead JS** + the `progress-track.js` include | `study-detail.js` | T |
| 8 | **Delete Overview's Status subsection, tests-count strip, follow-ups pointer** | `study-detail.html:539–557, 619–629, 663–671` | T |

### Tier 2 — the structural wins

| # | Change | Where | Kind |
|---|---|---|---|
| 9 | **Readouts redesign**: Recorder band (emitter + config + precedence chip), grouped/roled/lineage-collapsed Saved and Not-saved bands, search (§5.4) | template + JS; needs #5 | T (+B: a `study_emitter_resolution(ws, slug)` helper returning `{name, level, contract, config, location}` over `emitters.resolve_contract` + the §5.4 chain) |
| 10 | **`sources` on each emit path** (why this is saved) → the readout↔test↔figure links | `composite_runs.collect_emit_paths_from_spec` returns `{path, sources}` | **B** |
| 11 | **Reposition Readouts to slot 3 + act labels in the tab bar** (§3) | `study-detail.html:135–159` + CSS | T |
| 12 | **Findings ledger** — compact row + evidence drawer; `humanize_assertion` + `kv` formatters (§4.1) | `study-detail.html:389–450` + a Jinja filter | T |
| 13 | **Extract inline styles to `study-detail.css`** (163 attrs; unblocks dark mode) | new file | T |
| 14 | **Merge the two Model baselines into one Runnable-models list** + `⚠ needs a value` inline | `study-detail.html:693–850` | T |
| 15 | **Cross-tab link helper `_gotoStudyTab(kind, anchor)`** — fixes findings→test/run anchors into hidden panels | `study-detail.js` | T |
| 16 | **Consolidate the three download surfaces into Exports** | 3 sites | T |

### Tier 3 — the deeper reshapes

| # | Change | Where | Kind |
|---|---|---|---|
| 17 | **Decide → three beats**: verdict cards with real inputs (from `study_derivations.py:74–118`), conclusion + pre-registration line + scope-of-claim, one merged follow-up list | template + `lib/study_derivations.py` (expose inputs) | T + **B** |
| 18 | **Dissolve "Plan & provenance"** — relocate gate/assumptions/limitations→Decide, anchors→Tests, expert questions→Open debts | template | T |
| 19 | **Stale-run flag + ledger header on Simulations** (via `run_index.replay_params`) | `lib/simulations_index.py` + JS | **B** |
| 20 | **Populate Simulations' emitter/location from the run manifest**; emitter shown only on deviation | `lib/simulations_index.py` | **B** |
| 21 | **`undeclared_readouts` readiness gap** when `emit_selection == "total"` | `lib/report_views.py` | **B** |
| 22 | **Per-run reconciliation strip on Readouts** (manifest `emit_paths` diff) | `lib/readouts_views.py` + JS | **B** |
| 23 | **Tests: report cards expand in place; `literature_anchors` as "Expectations"** | template + JS | T |
| 24 | **Exports "receipt" zip** including run manifests | `lib/` zip builder | **B** |
| 25 | **"Recorded" level** — `RunReader.observables()` behind the env-worker RPC, diffed against Planned | env worker + `lib/readouts_views.py` | **B** |
| 26 | **Retire the non-v3 Decide branches** after auditing for remaining v2 studies | template | T |

### Suggested increments

- **Increment A — "stop the noise"** (#1–#8): every high-visibility ugliness, one PR.
  No new concepts, no new data.
- **Increment B — "Readouts becomes the instrument"** (#5, #9, #10, #11, #21, #22).
  The tab the user cares most about, plus the tab-order change it justifies.
- **Increment C — "one narrative"** (#12–#16, #18, #23): the findings ledger, the CSS
  extraction, the Model merge, cross-tab links, and the Plan-&-provenance dissolution.
- **Increment D — "the verdict is legible"** (#17, #19, #20, #24–#26): supersedes the
  declutter spec's Increment 3.

---

## 7. Out of scope

- **The write path** — toggling an observable into/out of the emitter selection, which
  would rewrite `study.yaml` and commit. Band C's `+ add as readout` is designed as its
  future home but ships disabled. When it does ship, reuse the Composite Explorer's
  existing checkbox picker (`walkthrough.js:2947–2978`, `:3222–3232`) rather than building
  a second one.
- **`runtime.emitter_config`** — an authoring surface for emit interval / buffering /
  chunking. Today the workbench builds those values itself and no call site supplies an
  override (§5.4); making them editable is a separate, backend-led increment.
- **Per-condition / per-variant readouts.** The data model has no such concept (§5.3);
  introducing one is a schema change, not a page redesign.
- **Interventions replacing `variants`** (declutter spec §6). This pass keeps `variants` as
  the authoring shape and only changes how they *render* (nested under their base). The
  typed `merge`/`override` intervention model remains a separate, larger increment.
- **Renaming any tab.** The order changes; the words do not.
- **`walkthrough.js` / the SPA investigation view** — this is the standalone
  `study-detail` page only.
- **Changing verdict computation rules** (`lib/study_derivations.py`). #17 exposes the
  inputs; it does not redefine them.

## 8. Success criteria

- No raw Python dict or JSON object appears in any tab's default (undisclosed) view.
- No table column renders with every cell empty; no section renders as an empty-state box
  unless its absence is a declared readiness gap.
- Readouts opens with the emitter and its config; the Saved band is grouped, searchable and
  lineage-collapsed; the Not-saved band shows a real, non-empty set for any study that
  declares readouts, and says `unknown` (never `empty`) when the composite cannot build.
- Every saved path states why it is saved, and that reason links to the test or figure.
- The tab bar reads Overview · Model · Readouts · Simulations · Visualizations · Tests ·
  Decide · Exports, grouped into three visible acts, in one row.
- Each of {gate results, run facts, downloads, follow-ups} appears in exactly one tab.
- Every cross-tab link (finding→test, finding→run, figure→run, readout→test) navigates and
  scrolls rather than silently failing into a hidden panel.

---
---

# v2 — Audit-grade revision

*Supersedes §1, §3 (act labels), §4.6, §4.7, §4.8, §6. Everything else stands.*

## 9. Revised conceptual model

### 9.1 The thesis

> **A study is a question evaluated against declared criteria, answered with traceable
> evidence, and closed by an accountable decision.**

The v1 thesis ("one question, answered once, with a receipt") got the *narrative* right and
the *epistemics* wrong. It had no place for the three things that separate a defensible
study from a well-organised one:

- **criteria declared in advance** — otherwise the bar moves to meet the result;
- **evidence bound to each claim** — otherwise a conclusion is an assertion;
- **a decision someone is accountable for** — otherwise nothing is actually closed.

The correction is not to add process furniture. It is to notice that the page already
*computes* most of this (§9.4) and simply never shows it. The redesign's job is to make an
existing rigor apparatus visible, not to invent a compliance regime.

### 9.2 Five acts, eight tabs, no new tab

v1 had three acts. The missing one sits between Evidence and Verdict: **Assurance** — the
act of holding evidence up against the criteria and recording what it did and did not meet.
Without it, Tests is "a checklist" and Decide is "an opinion," and there is nowhere for
severity, deviations, waivers, or review to live.

```
  ┌ THE STUDY ┐ ┌──── DESIGN ────┐ ┌──── EVIDENCE ────┐ ┌ ASSURANCE ┐ ┌ DECISION ┐   ┌ RECORD ┐
    Overview      Model  Readouts    Simulations  Viz       Tests         Decide        Exports
    ─────────     ─────  ────────    ───────────  ───       ─────         ──────        ───────
    the abstract  what runs · what   what ran ·   what   did it meet   authorized    the ordered,
    (ask+answer)  it will record     it produced         the declared  conclusion:   attributed
                                                         criteria, and who signed  audit package
                                                         with what      it, on what
                  BEFORE execution     DURING/AFTER      severity        basis
```

**Act → tab mapping, and the judgment behind it:**

| Act | Tab(s) | Epistemic mode | What it answers |
|---|---|---|---|
| *(abstract)* | **Overview** | summary | What did we ask, and what is the answer? |
| **I · Design** | **Model**, **Readouts** | a plan | What will run, and what will it record? |
| **II · Evidence** | **Simulations**, **Visualizations** | a record | What ran, with what provenance, producing what? |
| **III · Assurance** | **Tests** | an evaluation | Did the evidence meet the criteria declared in advance — and where it did not, how badly, and was that waived? |
| **IV · Decision** | **Decide** | an authorized act | Given the assurance record, what is the conclusion, who authorized it, and on what basis? |
| *(record)* | **Exports** | an artifact | The immutable, ordered, attributed package. |

**On naming.** The user's constraint stands: *order changes, words don't; no ninth tab.*
So **Tests keeps its label** and grows its job. This is defensible — "Tests" is where the
criteria and the checks already live (`behavior_tests`, `pass_if`, report cards, the gate
evaluator), so Assurance is an expansion, not a relabel. That said: if exactly one rename is
ever authorised, **Tests → Assurance** is the one worth spending, because "Tests" invites
readers to think *unit tests* (did the code run?) when the tab's real question is *did the
evidence meet the bar?*. Recommend deferring the rename and letting the **act label** above
the tab carry the word — which is precisely what act labels are for.

**Visualizations moves cleanly into Evidence.** In v1 it sat ambiguously beside Tests; a
figure is a *product of a run*, not a judgment of one. This tightens Act II and leaves Tests
alone as the assurance surface.

### 9.3 Revised tab bar (supersedes §3's act labels)

Order is **unchanged** from v1 — Readouts still moves to slot 3:

> **Overview · Model · Readouts · Simulations · Visualizations · Tests · Decide · Exports**

The act rail above it gains two labels:

```
 ┌ THE STUDY ┐ ┌───── DESIGN ─────┐ ┌────── EVIDENCE ──────┐ ┌ ASSURANCE ┐ ┌ DECISION ┐    ┌ RECORD ┐
   Overview      Model    Readouts    Simulations   Visualizations   Tests        Decide      Exports
```

Add a **gate dot** to each act label — a 6px dot coloured by that act's gate state (§13):
grey = not assessed, amber = open findings, green = passed, red = blocked, violet = waived.
The rail then reads as a *lifecycle progress bar* and a *navigation* at once, and it is the
cheapest possible surfacing of the gating spine: six gates, five dots, zero new tabs.

### 9.4 What already exists (the crucial finding)

Most of the assurance apparatus is **already implemented and already computed** — it is
simply never rendered on the study page. Before treating any of this as new work:

| Audit-grade concept | Already exists as | Status on the page |
|---|---|---|
| Acceptance criteria | investigation `acceptance_criteria[]` → `executive.computed_acceptance`, filtered per-study by `study_enrichment.study_acceptance_criterion:259` and attached to the spec as **`spine_acceptance`** (`study_spec.py:804–812`) | **computed, attached, never rendered** |
| Predefined pass thresholds | `behavior_tests[].pass_if` / `expect`, `calibration_anchor` | rendered (as raw JSON) |
| Threshold provenance ("is the bar sourced or invented?") | `rigor._test_threshold_sourced:343`, `threshold_sensitivity:362` | not rendered |
| Quality checks (V&V, sensitivity, controls, replication, falsifiability, pre-registration, claim discipline) | **`viva_superpowers/rigor.py`** — a full deterministic scorecard with per-dimension severities `GAP / WARN / OK / N-A` | not rendered |
| Reproducibility audit | **`viva_superpowers/study_audit.py`** — L0–L5 checks, `tier=hard\|soft`, `--gate` CLI already used in CI | not rendered |
| Plan-gate validation | **`viva_superpowers/study_verify.py`** — design→build cross-reference checks | not rendered |
| Evidence gaps | `needs_attention.open_epistemic_debts` (has `severity`) | rendered (Overview) |
| Lint findings with severity | report linter → `{study, check, severity, message, field_path}` (`models.py:896`) | rendered as a *count* only |
| Claim ↔ evidence links | `findings[].evidence.{from_test, from_run}`, `provenance.run_ids`, `expected.cites`, `expert_reference` | rendered (as broken anchors — §2 R6) |
| Execution provenance | run manifest: `env`, `env_id`, `seed`, `code_version.git_sha`, `emit_paths`, `result_fingerprint` (`composite_runs.py:245–275`) | not rendered |
| A *locked* verdict record | `conclusion_card` (schema `conclusion_card/v1`) — persisted to `viz/report_card/conclusion.verdict.json` and **preferred over live recompute** (`study_spec.py:906–915`); same precedent as `study_verdict.write_gate_evaluator` | rendered as a pill; its frozen-ness invisible |
| Actor identity (partial) | `feedback_tracked[].author` / `.responded_by` (`feedback_tracking.py:71,77,144`); `expert_decisions_needed[].asked_to` / `.status` | not rendered |
| A six-stage lifecycle | `design/implementation/simulation/evaluation/gate/expert_review_status` (`investigations.py:1417–1424`) | rendered as six authored strings behind `status ▾` |

**Genuinely new (schema additions to `study.yaml`)** — these do not exist in any form:
study-level `acceptance_criteria[]` with `required_evidence[]`; per-criterion outcome
vocabulary including **conditional-pass** and **not-assessable**; `severity` + `risk` on
findings; `deviations[]`; `waivers[]`; `attributions[]` / `sign_off{}` with actor identity
and decision basis; explicit `gates{}` objects carrying both a computed and an approved
state; reviewer independence.

---

## 10. Tests → the Assurance record *(supersedes §4.6)*

**One job:** *did the evidence meet the criteria declared in advance — and where it did not,
how badly, and was that accepted?*

Everything in §4.6 still applies as the mechanical declutter (one score line, one list,
report cards expanding in place, `literature_anchors` as Expectations, human assertions
instead of JSON). §10 adds the assurance structure *around* that list.

### 10.1 Four bands

```
 ACCEPTANCE CRITERIA                                            2 of 5 met · 1 conditional
 ─────────────────────────────────────────────────────────────────────────────────────────
 ✓  met          Doubling time within 10% of Boesen 2024        ← test:doubling_time · run cf3a12
 ◐  conditional  Two generations complete in all media          ← test:two_generations (2 of 3 media)
                 ⚑ waived by E. Agmon · 2026-07-24 · "minimal media out of scope" · expires 2026-09
 ✗  not met      ATP fraction inside the published band         ← test:atp_fraction   HIGH severity
 ○  not          Interface stability vs vEcoli                  — no evidence: comparison run never
    assessable                                                    executed  (evidence gap)
 ─────────────────────────────────────────────────────────────────────────────────────────

 CHECKS                                                          automated 12 · human 1
   ▸ Gates (behavioral + report cards)         0 / 4 passed        ← the §4.6 list, verbatim
   ▸ Quality  (rigor scorecard)                3 gaps · 2 warn     ← viva_superpowers/rigor.py
   ▸ Reproducibility (L0–L5 audit)             L0–L3 pass · L4 warn ← viva_superpowers/study_audit.py
   ▸ Spec verification (plan gate)             2 unresolved refs   ← viva_superpowers/study_verify.py
   ▸ Human review                              1 open question     ← expert_decisions_needed

 EXCEPTIONS                                                       1 waiver · 0 deviations
 EVIDENCE GAPS                                                    2  → Overview · Open debts
```

**Band 1 — Acceptance criteria.** The predefined bar, stated *before* the outcome, with a
four-value outcome vocabulary. Map the existing test vocabulary onto it with **no schema
change** (adopt-now):

| Existing | Audit outcome |
|---|---|
| `PASS` | **met** |
| `FAIL` | **not met** |
| `PARTIAL` | **conditional-pass** |
| `SKIP` / no result | **not assessable** |

The criteria themselves come from `spine_acceptance` (already on the spec, §9.4) until
study-level `acceptance_criteria[]` exists. Each criterion shows **its required evidence as
links** — this is the "each claim ↔ its evidence" requirement, and `findings[].evidence`
already carries exactly those references; they just need to render as working cross-tab
links (§2 R6).

**Band 2 — Checks**, grouped by *who ran them*: automated (gates, rigor, audit, verify) and
human (expert questions, reviewer annotations). Each group is one collapsed row with a
result summary; expanding shows the existing per-item detail. The point of the grouping is
the **independence** signal: a study whose entire assurance is self-authored automated
checks is a different epistemic object from one with an independent human review, and the
band header should say which it is.

**Band 3 — Exceptions.** Deviations (what departed from the plan) and waivers (what failed
but was accepted anyway, by whom, why, until when). **New schema.** Until it exists, this
band renders the honest stand-in: *"No deviations or waivers recorded — this study has no
mechanism to record them yet."* An empty exceptions band is not the same as a clean one, and
saying so is the whole point (§2 R2).

**Band 4 — Evidence gaps.** Criteria that are *not assessable* — the most under-served state
on the page today, because a missing result currently renders identically to a pending one.
Links to Overview's Open debts, which already collects them.

### 10.2 Severity and risk

Every unmet criterion and every finding carries **severity** (how wrong) and **risk** (what
it endangers). Neither exists on `findings` today (`status`, `kind`, `tier` are close but
orthogonal). **New schema** — but two-thirds of it is derivable now:

- `rigor.py` already emits `GAP / WARN / OK / N-A` per dimension → seed severity from it.
- The report linter already emits `severity` per finding (`models.py:896`).
- `study_audit` already emits `tier: hard|soft` → a hard-tier failure *is* high severity.

Recommendation: **compute a provisional severity from those three sources now**, label it
`computed`, and let an author override it once the field exists. That is the pattern the
codebase already uses everywhere (`computed_gate_verdict`, `spine_acceptance`) and it avoids
a schema change blocking a visible improvement.

---

## 11. Decide → the authorized verdict *(supersedes §4.7)*

**One job:** *given the assurance record, what is the conclusion, who authorized it, and on
what basis?*

The three-beat restructure of §4.7 stands (verdict cards with real inputs · conclusion +
pre-registration + scope of claim · one merged follow-up list). §11 adds accountability.

### 11.1 The verdict is an act, not a text field

Today the verdict is three computed pills plus three free-text `basis` boxes and a markdown
blob. Nothing records **who** decided, **when**, or **on what**. Add an authorization
block directly beneath the conclusion:

```
 ┌ AUTHORIZATION ────────────────────────────────────────────────────────────────────────┐
 │  Decision      accept with conditions                                                  │
 │  Decided by    ◆ Claude Opus 4.8  (agent)                          2026-07-27 14:02    │
 │  Reviewed by   ● E. Agmon  (human)                                 2026-07-28 09:15    │
 │  Independence  reviewer ≠ author  ✓                                                    │
 │  Basis         opinion ○──────────●── evidence      4 of 5 claims evidence-linked       │
 │                rests on: test:doubling_time · test:atp_fraction · finding F2 · run cf3a12│
 │  Record        locked · sha256:9f2c…  (conclusion_card/v1)          [⬇ audit package]   │
 └────────────────────────────────────────────────────────────────────────────────────────┘
```

### 11.2 The actor model — humans *and* agents

An approver is an **actor**, not a person. In this workspace most decisions are in fact
made by agents, and pretending otherwise would make the audit record a fiction.

```yaml
actor:
  name:  "Claude Opus 4.8"        # or "E. Agmon"
  kind:  agent                    # human | agent
  model: "claude-opus-4-8"        # agents only: model + version, for reproducibility
  # optional: session/run reference so the decision traces to its transcript
```

Every sign-off, review check and gate approval carries one. Rendering convention: a glyph
distinguishing the kinds (`●` human, `◆` agent) plus the model string for agents — an agent
decision must never be able to *pass as* a human one, and vice-versa. This is a genuine
integrity property, not decoration.

Note the codebase is already half-way: `feedback_tracked[].author` / `.responded_by` and
`expert_decisions_needed[].asked_to` are actor strings today. They are untyped (no
human/agent distinction) — typing them is the schema step; *showing* them is free.

### 11.3 The basis spectrum — make traceability a measured quantity

A decision spans a spectrum from **matter of opinion** (a judgment call) to
**evidence-grounded** (rests on specific tests/findings/runs). Record it:

```yaml
basis:
  kind: evidence            # opinion | evidence | mixed
  evidence_refs:            # what it rests on — resolvable references
    - test:doubling_time
    - finding:F2
    - run:cf3a12
  rationale: "…"            # required when kind == opinion
```

Render it as a **basis meter** whose position is *computed*, not asserted:

> `position = (# claims in the conclusion with ≥1 resolvable evidence_ref) / (# claims)`

This turns "traceability" from a checkbox into a visible measurement, and it is computable
against today's data: each verdict track already has computed inputs
(`study_derivations.py:74–118`), and a `basis` textarea with zero references measurably
reads as **opinion**. A study whose meter sits at the opinion end is not *wrong* — but the
page should say so plainly rather than dressing a judgment call as a derivation.

**Independence, computed rather than claimed:** an approver is *dependent* when the same
actor authored the artifact being approved. Once attributions exist this is a set
comparison, rendered as `self` / `independent` / `unknown`. Default to `unknown` and never
to `independent` — an unproven independence claim is worse than none.

### 11.4 Locking

`conclusion_card` **already freezes the verdict** to disk and the render already prefers the
frozen copy over a live recompute (`study_spec.py:906–915`). Two cheap additions make it an
audit record: (1) show that it *is* frozen, with its write timestamp — invisible today; and
(2) hash its content and show the digest. Full immutability (append-only, hash-chained
revisions with supersession rather than overwrite) is a real feature and is **aspirational**;
the digest + timestamp is a one-afternoon change that delivers most of the trust.

---

## 12. Exports → the audit package *(supersedes §4.8)*

**One job:** *one ordered, attributed, verifiable package that reconstructs the whole study.*

The §4.8 consolidation stands (Exports is the only download surface; Analyses retitled).
What changes is the *ordering principle*: Exports stops being a file browser grouped by
directory and becomes the audit package, **in narrative order**, each section attributed:

| # | Section | Contents | Source (existing unless noted) |
|---|---|---|---|
| 1 | **Question** | question, intended use, kind | `purpose.*`, `kind` |
| 2 | **Criteria** | acceptance criteria + thresholds + their provenance | `spine_acceptance`, `pass_if`, `calibration_anchor` |
| 3 | **Plan** | model version, config, assumptions, declared readouts | composite ref + resolved config, `key_assumptions`, `emit_paths` |
| 4 | **Execution** | runs, env, seeds, code version, logs | run manifests (`env`, `env_id`, `seed`, `code_version`) |
| 5 | **Evidence** | raw stores, analysis outputs, figures | existing download lists |
| 6 | **Findings** | claims + their evidence links + severity | `findings[]` (+ severity, **new**) |
| 7 | **Exceptions** | deviations, waivers, evidence gaps | **new** (+ `open_epistemic_debts`) |
| 8 | **Decision** | verdict, basis, conclusion | `conclusion_card` |
| 9 | **Sign-off** | actors, timestamps, independence, digest | **new** |

Rendered as a numbered checklist with a completeness state per section (`✓ complete` /
`⚠ partial` / `○ absent`) and one `⬇ Audit package (.zip)` producing exactly that structure
with a `manifest.json` and a content digest. Sections 1–5 and 8 are buildable **today** from
existing data; 6, 7 and 9 degrade honestly to `absent` until the schema lands, which makes
the package itself the strongest possible argument for adding those fields.

Note this replaces v1's "receipt" zip idea (§4.8 #2) with a stronger version: the ordering
*is* the audit trail, and it is the same order as the acts in §9.2 — the package is the page,
serialized.

---

## 13. The gating model

Six gates, in lifecycle order. The key finding: **the six gates are already present as the
six status axes** (`investigations.py:1417–1424`) — but the axes are authored free-text
strings with generic names, and each one already has a *machine evaluator* sitting unused
next to it. The reconciliation is a relabel plus a wiring, not a new subsystem.

| Gate | Passes when | Existing evaluator (unused on this page) | Existing axis | Act / tab |
|---|---|---|---|---|
| **1 · Plan** | question, intended use, model version, assumptions, readouts and success criteria are complete **before** execution | `study_verify` (design→build cross-refs) + report-linter `missing_question` + proposed `undeclared_readouts` (§5.2) | `design_status` | I — Model, Readouts |
| **2 · Execution** | required runs completed with valid provenance, environment, logs; no disqualifying deviations | run manifest (`env`, `env_id`, `seed`, `code_version`, `result_fingerprint`) + `study_audit` L2 | `simulation_status` | II — Simulations |
| **3 · Evidence** | outputs complete, reproducible, interpretable, and linked to each claim | `study_audit` L3/L4 + `result_fingerprint` + `findings[].evidence` resolution | `evaluation_status` | II — Simulations, Visualizations |
| **4 · Quality** | verification, validation, sensitivity, uncertainty and interface tests meet **predefined** thresholds | `rigor.py` dimensions + `threshold_sensitivity` + the gate evaluator | `evaluation_status` | III — Tests |
| **5 · Decision** | every major finding is resolved, accepted as residual risk, or explicitly blocks approval | `study_derivations.conclusion_verdicts` + open debts + (new) waivers | `gate_status` | IV — Decide |
| **6 · Release** | a named actor signs the conclusion and locks the record | `conclusion_card` persist (**lock exists; attribution missing**) | `expert_review_status` | IV — Decide, Exports |

### 13.1 Where gates live in the UI

- **The header keeps ONE pill.** The declutter's rule holds: one status, one readiness link.
  The pill now reads the **furthest gate passed** (`Gate 4 · Quality`) rather than an
  ambiguous axis value — a strictly more informative string of the same length.
- **`status ▾` becomes the gate ladder.** The six-axis stepper already lives there; relabel
  the axes to the gate names and give each a **computed** state alongside the authored one,
  plus a link to the evidence that produced it. When computed and authored disagree, show
  the divergence chip that already exists (`computed_gate_verdict.diverges_from_authored`,
  `study-detail.html:72–74`) — that mechanism is built and correct; it just needs to apply
  per gate rather than only to the overall verdict.
- **Act rail dots** (§9.3) show each act's gate state at a glance.
- **Each gate is attributed** (§11.2): a gate whose state is computed shows `◆ computed`;
  one an actor approved shows that actor. A gate approved by an actor *against* its computed
  state is the single most audit-relevant event on the page and should be visually loud.

### 13.2 Gate states

`not-assessed` · `passed` · `passed-with-conditions` · `blocked` · `waived`. This mirrors the
criterion vocabulary of §10.1 deliberately — one outcome vocabulary across criteria, gates
and verdicts is worth more than three precise ones.

---

## 14. Reconciled increments *(supersedes §6)*

**Increment A — "stop the noise" (#1–#8) is UNCHANGED.** It is purely mechanical: dict
rendering, dead columns, the empty-state bug, the duplicated gate summary, dead JS, the
vestigial subnav, the real saved/excluded set. Ship it exactly as specified in §6. Nothing
in v2 touches it.

**Increment B — "Readouts becomes the instrument"** (§6 #5, #9, #10, #11, #21, #22) is
unchanged in content; its tab-order change now also carries the **act rail with gate dots**
(§9.3), since both edit the same nav markup. Add: `undeclared_readouts` is now explicitly
**Gate 1 (Plan)** evidence, not a standalone lint.

**Increment C — "one narrative"** (§6 #12–#16, #18, #23) is unchanged, plus one addition:
**surface what already exists** — the cheapest audit-grade work in the whole plan, all
template/JS:

| C+ | Change | Kind |
|---|---|---|
| C1 | Render `spine_acceptance` as Tests' **Acceptance criteria** band — the data is already on the spec and never displayed | **T** |
| C2 | Render the `rigor.py` scorecard as Tests' **Quality** check group (severities included) | T (thin backend route) |
| C3 | Render `study_audit` L0–L5 as the **Reproducibility** check group | T (thin backend route) |
| C4 | Relabel the six status axes to the six gates; show computed-vs-authored per gate | **T** |
| C5 | Map `PASS/FAIL/PARTIAL/SKIP` → `met / not met / conditional-pass / not assessable` | **T** |
| C6 | Show attribution wherever an actor is *already* recorded (`feedback_tracked.author`, `.responded_by`, `expert_decisions_needed.asked_to`, conclusion-card write time) — and render `unattributed` explicitly where none is | **T** |
| C7 | Show that the verdict record is **frozen**, with its timestamp + content digest | T + tiny B |

**Increment D — was "the verdict is legible," now "audit-grade assurance + authorized
verdict + audit package."** This is where the **schema work** concentrates and it is
**backend-led**. Split it in two, because the halves have very different costs:

**D1 — structure without accountability** *(schema additions, moderate)*
| # | Change | Kind |
|---|---|---|
| D1.1 | Study-level `acceptance_criteria[]` with `required_evidence[]` refs | **B — schema** |
| D1.2 | `severity` + `risk` on findings (seeded from rigor / linter / audit tier, author-overridable) | **B — schema** |
| D1.3 | `deviations[]` + `waivers[]` (waiver: actor, reason, expiry, criterion) | **B — schema** |
| D1.4 | Explicit `gates{}` objects: computed state + approved state + evidence refs | **B — schema** |
| D1.5 | Exports → the ordered 9-section audit package with per-section completeness | B |
| D1.6 | §6 #17, #19, #20, #24–#26 (verdict inputs, stale-run flag, manifest-sourced emitter, Recorded-level readouts) — carried forward unchanged | B |

**D2 — accountability** *(schema + policy, the real feature)*
| # | Change | Kind |
|---|---|---|
| D2.1 | `attributions[]` / `sign_off{}`: `actor{name, kind: human\|agent, model?}`, timestamp, `basis{kind, evidence_refs[], rationale}`, target gate/decision id | **B — schema** |
| D2.2 | The basis meter (computed opinion↔evidence position) | B + T |
| D2.3 | Computed independence (`self` / `independent` / `unknown`) | B |
| D2.4 | Immutable record: append-only, hash-chained, supersede-never-overwrite | **B — hard** |
| D2.5 | Who-signs-what policy (which gates require a human; whether an agent may sign alone) | **policy, not code** |

### 14.1 Recommended adoption path — what to take now, what is aspirational

The audit-grade frame is worth adopting; the *compliance apparatus* is not, yet. Split:

**Adopt now** — high value, no schema, no policy:
1. **The reframing itself** — five acts, the Assurance act, the act rail with gate dots. Pure
   information architecture; it changes how every later increment is judged.
2. **Surface what is already computed** (C1–C3): `spine_acceptance`, the rigor scorecard, the
   L0–L5 audit. Three deterministic evaluators, already shipped, already used by CI, invisible
   on the page. This alone moves the page most of the way to audit-grade.
3. **Relabel the six axes to the six gates** (C4) and show computed-vs-authored per gate. The
   ladder exists; it is mis-named and unwired.
4. **One outcome vocabulary** (C5) — `met / conditional-pass / not met / not assessable` —
   applied to criteria, gates and verdicts alike.
5. **Advertise attribution from what exists** (C6), including an explicit `unattributed`.
   Rendering "decided by: unattributed" on every verdict is the cheapest possible forcing
   function for D2, and it is honest today.
6. **Show that the verdict is frozen** (C7).

**Adopt next** (D1): acceptance criteria, severity/risk, deviations/waivers, gate objects,
the ordered audit package. Real schema work, but each field has an existing computed seed,
so none of it starts from zero.

**Aspirational** (D2.4, D2.5): a true immutable, hash-chained, signed record and a
who-signs-what policy. These are a *product*, not a page redesign — and their value depends
entirely on someone actually being accountable for the result. Build them when a real
reviewer (human or agent) is on the hook for a real decision; until then they are ceremony,
and ceremony is exactly what this redesign is trying to remove.

**The honest framing for the whole v2:** this page's problem was never a missing compliance
layer. It was that a workspace with a genuinely rigorous apparatus — pre-registered
thresholds, deterministic rigor scoring, an L0–L5 reproducibility audit, frozen verdict
cards — renders none of it, and renders a free-text opinion box instead. Audit-grade here
means *showing the rigor that already exists*, and adding accountability (who, when, on what
basis) as the one genuinely missing dimension.

### 14.2 Revised success criteria (additive to §8)

- The tab rail shows five acts with per-act gate dots; Assurance is a visible act.
- Tests opens with acceptance criteria and their outcomes in the four-value vocabulary,
  each linked to the evidence it rests on.
- The rigor scorecard and the L0–L5 audit are visible on the page, not just in CI.
- `status ▾` reads as six named gates, each with a computed state and an evidence link;
  computed-vs-authored divergence is visible per gate.
- Every verdict, approval and gate displays its actor (human or agent, with model for
  agents) and its basis — or says `unattributed` rather than leaving it blank.
- A decision's position on the opinion↔evidence spectrum is *computed and shown*, not claimed.
- Exports produces one ordered, attributed audit package whose sections state their own
  completeness.
