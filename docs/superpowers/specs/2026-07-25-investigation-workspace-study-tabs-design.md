# Investigation workspace with study tabs — design

**Date:** 2026-07-25
**Repo:** vivarium-workbench (frontend SPA in `vivarium_workbench/static/walkthrough.js` + `vivarium_workbench/templates/index.html.j2`)
**Status:** approved design, ready for implementation plan

## Problem

How the SPA displays investigations and studies is inconsistent, because three
different entry points land a study under three different "above" contexts:

1. **Sidebar study click** → opens the study, but leaves whatever investigation
   graph was previously loaded connected above it (a *stale* investigation).
2. **Study card** (Studies browse) → can show an investigation stacked above the
   study.
3. **Studies tab** → the browse/studies UI itself ends up in the panel above the
   study.

There is also a v2/v3 fork: opening a v2-shape investigation (`spec.yaml` with
`variants`, e.g. `v2ecoli-vecoli-comparison`) renders a legacy "Study:
<investigation>" icon-tab view instead of the proper graph + objective detail.

The goal is one consistent, general model that cleanly separates **browsing/
searching** from **what is currently being viewed**, and shows a currently-open
investigation together with the studies opened inside it as embedded tabs.

## Goals / non-goals

**Goals**
- Separate the *browse/search/create* surface from the *viewing* surface.
- A viewing surface that shows one investigation (graph + objective) as
  persistent context, with opened studies as accumulating, closeable tabs
  beneath it.
- A single router so clicking a study *anywhere* behaves identically and always
  loads that study's *own* investigation (no stale context).
- Retire the legacy "Study: <investigation>" icon-tab render from the
  study/investigation viewing path.

**Non-goals**
- No backend/API changes. This is a client-side (SPA) restructure over existing
  endpoints (`/api/investigation-summaries`, `/api/investigations`,
  `/studies/<slug>` embedded page, `/api/investigation/<name>` detail).
- No change to the study-detail (pillar-tab) page itself — it is embedded as-is.
- The separate legacy `page-studies` section is not the target; the Studies
  browse lives as a tab on the Investigations page (already built).

## Design

### Two surfaces

**Explore surface** (the browse/search surface) — everything for
*finding/creating*, organized like the Registry page's clean tab layout
("Modules | Discovered registry" over "Processes | Steps | …"):

- a header/label **"Explore"**,
- a single **tab row: `Investigations N | Studies M`** (Registry-style tabs with
  live counts; `_setIsetBrowseTab`),
- the search input (`#investigations-filter`) + the **Sort** control,
- the card grid (`#investigations-list`),
- the context-aware **`+ New`** create button + prompt modal.

**Smart grouping within each tab** (this is the "intelligently organized for easy
exploring" part):

- **Investigations tab** → grouped **Active / Closed** (as today), each an
  uppercase group heading with a count, cards in a responsive grid.
- **Studies tab** → grouped **by their investigation**: one group heading per
  investigation (title + study count) followed by that investigation's study
  cards; studies with no investigation fall into an **"Ungrouped"** group. So the
  flat 42-study list reads in context (e.g. `COLONY COMPOSITE (3)` → its three
  study cards).
- The **Sort** control re-slices within groups (by name, status, recency, run
  count); it does not flatten the grouping.

This surface is what the **Investigations** left-nav item shows.

**Viewing surface (the "investigation workspace")** — a persistent surface for
*one* investigation plus the studies opened inside it. Opening an investigation
**hides Explore** and shows this surface. The user returns to Explore via the
**Investigations** nav item or a **"← All investigations"** control in the
workspace header. Search + create exist only on Explore.

### Viewing surface layout

```
┌ ← All investigations   Investigation: colonies      [status] [Report] [Notebook] ┐
│ ▾ graph + objective        (collapsible investigation context)                   │
├───────────────────────────────────────────────────────────────────────────────────┤
│ [ colonies-01 × ] [ colonies-03 × ]                 ← study tabs (opened only)     │
│                                                                                   │
│   active study's pillar page  (embedded /studies/<slug> in an iframe)              │
└───────────────────────────────────────────────────────────────────────────────────┘
```

Regions:
- **Workspace header**: the "← All investigations" control, the investigation
  title, its status pill, and its Report / Notebook download actions (moved from
  the card).
- **Investigation context**: the collapsible graph + objective (the existing
  investigation-detail render — graph nodes = studies, objective/biology prose).
- **Study-tabs bar**: one tab per *opened* study, each with a close (×). Empty
  until a study is opened.
- **Study porthole**: an iframe embedding the active study's pillar page
  (`/studies/<slug>`).

### Behaviors

- **Open an investigation** (from a Explore card or a sidebar investigation group
  header): Explore hides; workspace shows with the graph + objective **expanded**;
  study-tabs bar empty; no porthole.
- **Open a study** (graph node, study card on the Studies tab, or sidebar study
  leaf): its tab **pops in** (or focuses if already open); the investigation
  context **auto-collapses to a slim `▸ Investigation: <name>` bar**; the study's
  pillar page loads in the porthole.
- **Click the slim context bar**: the graph + objective **re-expands** (study
  tabs remain; the last-active study stays selected but the porthole may be
  scrolled below the expanded graph — expanding is an explicit "show me the
  graph" action).
- **Close a study tab (×)**: if it was active, focus the nearest remaining tab
  and keep the context collapsed; if it was the last tab, **return to graph-only**
  (context re-expands, porthole hidden). *(Decision: closing all tabs returns to
  graph-only, not to Explore.)*
- **Return to Explore**: the Investigations nav item or "← All investigations"
  shows Explore and hides the workspace. The workspace state (current
  investigation + open study tabs + active tab) is **retained** so re-opening the same investigation restores its tabs within the session.

### Consistency router

A single function is the only way a study is opened. Given a study slug:

1. Resolve the study's **own** investigation (`_investigationForStudy`, from the
   iset index).
2. If the workspace is **not already showing** that investigation, load it fresh
   (`_showInvestigationWorkspace(inv)` — renders graph + objective, **resets**
   the study-tabs bar).
3. **Add or focus** the study's tab; **collapse** the investigation context;
   embed `/studies/<slug>` in the porthole.
4. **Highlight** the study (and reveal its investigation group) in the sidebar
   rail.

This removes: stale-investigation-above-study, wrong-context study cards, and the
studies-tab-stuck-in-the-panel. An "ungrouped" study with no resolvable
investigation opens in a minimal workspace (header + a single study tab, no
graph).

### Component / code architecture

Client-side only, in `walkthrough.js` (+ markup in `index.html.j2`):

- **`_showInvestigationWorkspace(name)`** — replaces the old `_openInvestigation`
  focus-mode render. Renders the workspace header + collapsible investigation
  context (graph + objective) + an empty study-tabs bar + hidden porthole.
  **Always** renders the graph + objective detail; the legacy "Study:
  <investigation>" icon-tab render is not used on this path (v2-shape specs get
  the same graph + objective, since they have member studies → a graph).
- **Study-tabs manager** — session state `window._wsStudyTabs = { investigation,
  openTabs: [slug…], active: slug|null }` plus:
  - `_wsOpenStudyTab(slug)` — add or focus a tab, collapse context, embed.
  - `_wsCloseStudyTab(slug)` — close; refocus or return to graph-only.
  - `_wsRenderStudyTabs()` — render the tab bar into a mount.
- **`_setInvestigationContextCollapsed(bool)`** — toggle the graph/objective ↔
  slim-bar; wired to the slim bar click and to open/close-study transitions.
- **`_openStudyEmbeddedNewTab(slug)`** — rewritten to be the single router above
  (replaces the current pillar-in-porthole behavior).
- **Explore surface** — a header/label + Registry-style `Investigations N |
  Studies M` tab row (styling reused from the Registry page's tabs). The
  Investigations tab keeps the Active/Closed grouping; the Studies tab renderer
  (`_renderStudyBrowseCards`) is updated to **group study cards by their
  investigation** (heading + count per investigation, an "Ungrouped" bucket for
  the rest) instead of one flat "All studies" group. Sort applies within groups.
- **`_showExplore()` / `_showWorkspace()`** — toggle the two surfaces; wired to the
  Investigations nav (`data-page="investigations"` handler) and the "← All
  investigations" control. ("Explore" is the surface; "Explore ⇄ Viewing" is the
  toggle.)
- **Sidebar rail** — study leaves already carry `data-study-name` and call
  `_openStudyEmbeddedNewTab`; they now route through the workspace like every
  other entry point. `_selectStudyInRail` keeps the rail highlight in sync.

Existing markup reused where possible: the investigation detail render (graph +
objective), the study embed iframe pattern (`_fitEmbedToViewport`), and the
`investigation-detail-view` / embed-panel ids — reorganized into the workspace
regions.

## Edge cases

- **v2-shape investigation** (`spec.yaml` + `variants`): the workspace renders its
  graph + objective (member studies form the graph); it never renders the legacy
  study-as-investigation icon view.
- **Study opened while a *different* investigation is in the workspace**: load the
  new investigation fresh (reset tabs) before opening the study — never keep the
  old graph above the new study.
- **Deep link / bookmark** to `/studies/<slug>`: unchanged — the standalone
  server-rendered pillar page still resolves (external links keep working). The
  workspace is a live-SPA convenience layered on top.
- **Snapshot / read-only bundle**: the workspace uses the same base-path-aware
  `_studyHref`; no live-only assumptions beyond what the current embed already
  makes.
- **Reopening the same investigation** in a session restores its open study tabs
  + active tab (state retained across Explore ⇄ Viewing toggles).

## Testing

- **JS structure tests** (grep the served `walkthrough.js` / `index.html.j2`, the
  existing pattern in `tests/test_*structure*`/`test_pillar_unify`): the router
  `_openStudyEmbeddedNewTab` no longer full-window-navigates and no longer routes
  through the legacy `_openInvestigation` icon render; the workspace exposes the
  study-tabs manager + collapse toggle; Explore and Viewing are distinct
  toggled surfaces.
- **Render checks** against a live server on a workspace with both a v3
  investigation (colonies) and a v2-shape one (v2ecoli-vecoli-comparison):
  opening a study from each of the three entry points lands the study in the
  workspace under *its own* investigation, with the context collapsed, and the
  sidebar highlighting the study — asserted via DOM state, not the legacy
  "Baseline Composite" markers.
- Manual pass: open/close/focus study tabs; collapse/expand context; Explore ⇄
  Viewing round-trip retains tabs.

## Rollout

This lands on the existing `feat/investigations-browse` branch (PR #569), which
already carries the Investigations|Studies toggle, richer cards, sort, the
study-open pillar fix, and the prompt-first create — this redesign supersedes the
ad-hoc study-open behavior with the unified workspace router.
