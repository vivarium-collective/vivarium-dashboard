# Increment C — "one narrative" (template/JS reshapes)

> **For agentic workers:** implement subagent-driven with per-task review. One editing subagent at a time in the shared worktree.
> **Depends on:** Increment A + Increment G (both landed on `feat/study-design-fable-a`, tip `2e4b68a`). Build C off G's tip.

**Goal:** Collapse the study page into one reading narrative — a real **findings ledger**, one **Runnable-models** list, report cards that **expand in place**, downloads consolidated into **Exports**, the **Plan & provenance** grab-bag dissolved into the acts its pieces belong to, and finally all inline styles **extracted to a stylesheet** (unblocks dark mode). All template/JS; **no schema changes, no backend logic changes** (a couple of pure Jinja formatting filters are fine).

**Design source of truth:** `docs/superpowers/specs/2026-08-01-study-design-fable-pass.md` — §6 #12–#16/#18/#23 (the item list), §4.1 (findings ledger), §2 (R1–R6 rendering rules; R5 = CSS extraction), §4.2 (Model merge), §4.6/§10 (Tests), §4.8/§12 (Exports). Each task cites its section.

**Tech stack:** Jinja template `vivarium_workbench/templates/study-detail.html` (1829 lines), vanilla JS `vivarium_workbench/static/study-detail.js` (2175 lines), served CSS under `vivarium_workbench/static/`. No bundler.

## Global constraints
- **No schema changes, no backend logic changes.** New pure-formatting Jinja filters (registered in `lib/study_page.py` beside `outcome_label`) are allowed; nothing may read a field that isn't already on the study spec.
- **Absent ≠ empty** (spec §2 R2): a section with no data renders nothing, never an empty box.
- **No visual regression** except the intended reshape: the page must render the same content; only its structure/placement/styling changes as each task specifies.
- **Reuse, don't fork:** route all outcome/status display through the existing G3 `outcome_label` filter + JS helpers and existing CSS classes; do not invent parallel vocabularies or color systems.
- **Line numbers in this plan are approximate** (the template shifted across A/G) — implementers **grep by content/anchor**, never trust a bare line number.
- Test env (ONLY this venv): `/Users/eranagmon/code/vivarium-workbench--study-declutter/.venv/bin/python -m pytest <file> -v`; `dashboard_client` is a FACTORY `dashboard_client(ws)->client`; run focused files, foreground. `node --check vivarium_workbench/static/study-detail.js` after every JS edit. Grep `tests/` for fallout on any deletion/relabel.
- **Concurrency:** ONE editing subagent at a time. Reviewers are read-only. NEVER run `git stash`/`reset`/`checkout`/`clean`/`restore`; a FOREIGN `stash@{0}` must never be touched — read other revisions with `git show <rev>:<path>`. Stage only specific paths (`git add <path>`), NEVER `git add -A` (unrelated modified fixtures live in the tree). Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Task C1 (do first): Cross-tab link helper `_gotoStudyTab(kind, anchor)`
**Kind:** T (JS) · **Fable §:** §6 #15. **Foundational — C2 uses it.**
Add a JS helper `_gotoStudyTab(kind, anchor)` in `static/study-detail.js` that (a) activates the tab whose `data-kind` == `kind` (same mechanism `_setStudyTab` already uses — reuse it, don't duplicate the tab-switch logic), then (b) scrolls to / highlights `#<anchor>` inside that now-visible panel. Today an anchor link into a hidden panel silently fails because the target is `display:none`. Expose it so inline `onclick="_gotoStudyTab('assurance','bt-<id>')"` works from any tab. If `anchor` is falsy, just switch tabs. If the anchor element is missing after the switch, switch the tab and no-op the scroll (don't throw).
- Test: a render/DOM assertion (or a focused JS unit test if the harness supports it) that the helper is defined and that a findings→test evidence link uses it. At minimum, a `node --check` clean + a render assertion that the emitted evidence links call `_gotoStudyTab(`. Wire at least one real caller in C2.

## Task C2: Findings ledger + assertion formatters
**Kind:** T (template + 2 Jinja filters) · **Fable §:** §4.1, §6 #12. **Uses C1.**
Replace the current Findings render (Overview "🔬 Findings" section, `{% for f in study.findings %}`) with a **compact ledger**: one row per finding — outcome glyph (via `outcome_label`) · short claim · a disclosure that opens an **evidence drawer** linking to the test/run/figure it rests on (evidence links call `_gotoStudyTab` from C1). Add two **pure-formatting** Jinja filters in `lib/study_page.py` (beside `outcome_label`):
- `humanize_assertion(a)` — turn a finding's raw assertion/`observed`/`pass_if` **dict** into a readable phrase (e.g. `observed 0.42 vs pass_if ≤ 0.5`) instead of dumping a Python dict repr. Handle the shapes actually present in `study.findings[*]` (grep fixtures + `lib/` for the finding shape first).
- `kv(d)` — render a small dict as `k: v · k: v` inline text (used inside the drawer), escaping values.
**Also fix the latent `measure|tojson` 500** in this region if present (a finding with a non-JSON-serializable `measure` currently risks a 500 — verify by rendering a fixture finding through the page; if `tojson` is the culprit, route it through the new formatter / a safe serialization).
- Test: a fixture study with findings renders the ledger rows (glyph + claim + a drawer with evidence links that call `_gotoStudyTab`); `humanize_assertion` unit-tested on the real dict shape (dict in → readable phrase, not `{'...'}`); a finding with a dict `observed`/`pass_if` does **not** 500 the page. Absent findings → no ledger, no empty box.

## Task C3: Merge the two Model baselines into one Runnable-models list
**Kind:** T (template) · **Fable §:** §4.2, §6 #14.
The Compose/Model tab currently shows baseline info in two places (the Build-block `{% for b in study.baseline %}` list and the Conditions `_cond.baseline` block). Merge them into **one "Runnable models" list**: each model = name + composite ref + params, with `⚠ needs a value` rendered **inline** next to any param/model-setting that still has no human-set value (the Conditions block already computes "still need a human-set value" — reuse that signal, don't recompute). Do not lose the "Set composite" affordance for an unresolved composite ref (keep the existing `baseline-composite-input`/`baseline-composite-set` control). Non-v3 studies (that only have `study.baseline`, no `conditions`) must still render their models.
- Test: a v4 fixture (baseline + conditions + a value-needing setting) renders ONE models list with the `⚠ needs a value` marker inline; a non-v3 fixture (baseline only) still renders its model. No duplicate baseline block remains (assert the old second render is gone).

## Task C4: Consolidate the three download surfaces into Exports
**Kind:** T (template + JS) · **Fable §:** §4.8, §6 #16.
Three download surfaces exist today — `#readouts-download` (Readouts tab), `#data-download-all` / the Exports `<a>`s (Exports tab), and any per-run/store download rendered elsewhere. Consolidate the **download actions** into the **Exports** tab as one group, leaving at most a single pointer link (not a duplicate download UI) where a download used to sit inline. Keep the existing endpoints/JS loaders (`_loadReadoutsDownload` etc.) — just move where their output mounts so Exports is the single "take the artifacts" surface. Do not break the Readouts tab (a small "Download this run's data → Exports" pointer is fine; a second full download widget is not).
- Test: render assertion that the download actions render under Exports; the Readouts tab no longer renders a full duplicate download widget (a pointer link is allowed); the Exports download `<a>`/loaders still resolve.

## Task C5: Dissolve "Plan & provenance" into the acts *(HOLD — confirm with user before dispatching)*
**Kind:** T (template) · **Fable §:** §4.7/§4.6, §6 #18.
> **⚠ This task reverses an explicit earlier user tweak** (Plan & provenance was made *always shown* on Overview, commit `bf6ea5c`). Do NOT dispatch this task until the controller has the user's confirmation. If the user prefers to keep a consolidated section, this task is dropped or reduced to a relabel.
Dissolve the Overview "Plan & provenance" group (`{# ─── Group 4: Plan & provenance (always shown) ─── #}`), relocating each piece to the act it belongs to: **gate / assumptions / limitations → Decide**; **anchors (`literature_anchors`) → Tests** (raw move here; C6 formats them as "Expectations"); **expert questions / open debts → Decide's "Open debts"**. No content is deleted — only moved. After the move, the Overview tab ends at Findings/insight; Plan & provenance no longer exists as a section.
- Test: render assertions that gate/assumptions/limitations now render in Decide, `literature_anchors` render in Tests, expert questions render in Decide's open-debts area, and the Overview "Plan & provenance" heading is gone. Nothing rendered twice.

## Task C6: Tests — report cards expand in place + `literature_anchors` as "Expectations"
**Kind:** T (template + JS) · **Fable §:** §4.6/§10, §6 #23. **After C5 (anchors already in Tests).**
In Tests: make report cards **expand in place** (inline disclosure) rather than linking away / replacing the view. Render the `literature_anchors` (moved to Tests by C5) as an **"Expectations"** band — each anchor as a stated expectation the study is measured against, using the existing outcome vocabulary where an anchor carries an outcome. Keep it read-only (editing anchors is out of scope, §7).
- Test: render assertion that report cards have an in-place expand control (not a navigation link) and that `literature_anchors` render under an "Expectations" heading in Tests. If C5 is on hold, this task reads anchors from their current Overview location instead — note that fallback in the implementer brief at dispatch time.

## Task C7 (do LAST): Extract inline styles to `study-detail.css`
**Kind:** T (template + new CSS file) · **Fable §:** §2 R5, §6 #13.
Create `vivarium_workbench/static/study-detail.css`, link it from the template head (beside `/style.css`, `/progress-track.css` — confirm how those are served and mirror it; likely a `@app.get`/static mount in `api/app.py`). Move the **two inline `<style>` blocks** (currently ~line 198 and ~355) and **all `style="…"` inline attrs** (~178) into classes in the new file, replacing each inline attr with a semantic class. **Zero visual change** is the bar — this is a pure mechanical extraction over the *settled* post-C markup. Run last so it captures markup added/moved by C2–C6.
- Test: the CSS file is served (200) and linked in the rendered page; the page still renders all key sections (act rail, findings ledger, models list, Tests bands, Exports); a guard that the count of `style="` inline attrs in the template dropped to ~0 (or a documented small residual for truly dynamic inline styles like server-computed widths, which stay). Grep `tests/` for any assertion keyed on an inline style string and update it.

---

## Out of scope (later increments / §7)
- The readout **write path** (`+ add as readout`), `runtime.emitter_config` authoring, per-condition/per-variant readouts, `variants`→interventions, tab renames — all §7.
- Backend-led items #17/#19/#20/#21/#22/#24–#26 — **Increment B / D**.
- Schema additions (acceptance_criteria[]/severity/waivers/gates{}/audit-package) — **Increment D1**.

## Success criteria
- Findings render as a compact ledger with working cross-tab evidence links; no dict-repr, no 500.
- One "Runnable models" list with inline `⚠ needs a value`; no duplicate baseline block.
- Downloads live under Exports only; report cards expand in place; `literature_anchors` read as "Expectations" in Tests.
- (If confirmed) Plan & provenance is dissolved into the acts, nothing duplicated.
- Inline styles extracted to `study-detail.css`; page renders identically; dark mode is now reachable.
