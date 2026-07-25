# Investigation Workspace with Study Tabs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the SPA's investigations/studies UI into a clean **Explore** browse surface + a persistent **investigation workspace** (collapsible graph + objective, opened-only study tabs, active study porthole), with a single router so every study-open path loads that study's own investigation — no stale context, no legacy v2 "Study:" icon view.

**Architecture:** Client-side only, in `vivarium_workbench/static/walkthrough.js` (SPA driver) + `vivarium_workbench/templates/index.html.j2` (markup). No backend/API changes — reuses `/api/investigation-summaries`, `/api/investigations`, and the embedded `/studies/<slug>` pillar page. Two toggled surfaces (Explore ⇄ Viewing) live inside the existing `#page-investigations` section.

**Tech Stack:** Vanilla ES2020 JS (no bundler), Jinja2 template, Python 3.12 + pytest for structure tests, `node --check` for JS parse, a locally-served workbench for live-render checks.

## Global Constraints

- Language: browser JS must stay ES2020-compatible (the codebase already uses `??`/`?.`); no new build step, no new dependencies.
- All new SPA functions are attached to `window.` (the pattern every existing handler follows) so inline `onclick=` can reach them.
- Escape all interpolated user/data strings with the existing `_esc(...)` helper.
- Study pillar pages are embedded via `_studyHref(slug)` (base-path aware) — never a raw `/studies/<slug>`.
- Tests read the **source** files (`vivarium_workbench/static/walkthrough.js`, `vivarium_workbench/templates/index.html.j2`); run pytest with `PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard` from the repo root.
- Work on branch `feat/investigations-browse`. Commit after every task.
- After each JS edit, `node --check vivarium_workbench/static/walkthrough.js` must pass; after each template edit, the Jinja loader must parse `index.html.j2`.

---

## File Structure

- **Modify** `vivarium_workbench/static/walkthrough.js` — the study-open router, the workspace renderer + study-tabs manager + context-collapse, the Explore⇄Viewing toggle, and the studies-by-investigation grouping in `_renderStudyBrowseCards`.
- **Modify** `vivarium_workbench/templates/index.html.j2` — the `#page-investigations` section: the Explore label + counts on the tab row, and the workspace regions (header, collapsible context mount, study-tabs mount, study porthole).
- **Create** `tests/test_investigation_workspace.py` — structure tests (read the two files, assert markers), following the `tests/test_pillar_unify.py` pattern.

---

## Task 1: Studies grouped by investigation in the Explore surface

**Files:**
- Modify: `vivarium_workbench/static/walkthrough.js` (`_renderStudyBrowseCards`)
- Modify: `vivarium_workbench/templates/index.html.j2` (tab-row labels → counts)
- Test: `tests/test_investigation_workspace.py`

**Interfaces:**
- Consumes: `window._investigations` (study objects: `{name, status, effective_status, question, objective, n_runs}`), `window._isetIndex` (investigations: `{name, title, studies:[slug]}`), `_investigationForStudy(slug)`, `_studyBrowseCardHtml(study)`, `_esc(s)`.
- Produces: `_renderStudyBrowseCards(list)` renders `<div class="iset-group" data-study-group="<invName|__ungrouped__>">` groups; `_setIsetBrowseTab(tab)` updates `#iset-tab-inv-count` / `#iset-tab-study-count`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_investigation_workspace.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "vivarium_workbench/static/walkthrough.js").read_text(encoding="utf-8")
TPL = (ROOT / "vivarium_workbench/templates/index.html.j2").read_text(encoding="utf-8")


def test_studies_grouped_by_investigation():
    # _renderStudyBrowseCards groups by investigation (not one flat "All studies").
    i = JS.index("function _renderStudyBrowseCards")
    block = JS[i:i + 2500]
    assert "data-study-group" in block          # one group per investigation
    assert "__ungrouped__" in block             # bucket for studies with no iset
    assert "All studies" not in block           # the old single flat group is gone


def test_explore_tab_row_has_counts():
    assert 'id="iset-tab-inv-count"' in TPL
    assert 'id="iset-tab-study-count"' in TPL
    assert "Explore" in TPL                      # the surface label
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard python -m pytest tests/test_investigation_workspace.py -q`
Expected: FAIL (`data-study-group` / `iset-tab-inv-count` / `Explore` not found).

- [ ] **Step 3: Update the tab row markup**

In `index.html.j2`, replace the `.iset-browse-tabs` block (the `Investigations`/`Studies` buttons) so it carries the Explore label + count spans:

```html
  <div class="iset-browse-header" style="display:flex;align-items:center;gap:14px;margin:0 0 4px">
    <strong style="font-size:1.05em;color:#0f172a">Explore</strong>
  </div>
  <div class="iset-browse-tabs" role="tablist"
       style="display:flex;gap:2px;margin:0 0 12px;border-bottom:1px solid #e5e7eb">
    <button class="iset-browse-tab active" data-browse="investigations" role="tab"
            onclick="_setIsetBrowseTab('investigations')"
            style="background:none;border:0;border-bottom:2px solid transparent;padding:8px 14px;font-size:1em;cursor:pointer;color:#64748b;margin-bottom:-1px">Investigations <span id="iset-tab-inv-count" style="color:#94a3b8;font-weight:600"></span></button>
    <button class="iset-browse-tab" data-browse="studies" role="tab"
            onclick="_setIsetBrowseTab('studies')"
            style="background:none;border:0;border-bottom:2px solid transparent;padding:8px 14px;font-size:1em;cursor:pointer;color:#64748b;margin-bottom:-1px">Studies <span id="iset-tab-study-count" style="color:#94a3b8;font-weight:600"></span></button>
    <button id="iset-browse-create" class="action-btn" onclick="_openBrowseCreate()"
            style="margin-left:auto;align-self:center;margin-bottom:6px">+ Investigation</button>
  </div>
```

- [ ] **Step 4: Group studies by investigation in `_renderStudyBrowseCards`**

Replace the body of `_renderStudyBrowseCards(list)` in `walkthrough.js` with:

```javascript
  function _renderStudyBrowseCards(list) {
    var studies = (window._investigations || []).slice();
    if (!studies.length) {
      list.innerHTML = '<p class="empty-state">No studies in this workspace yet.</p>';
      return;
    }
    var sort = window._isetSort || 'default';
    var rank = { running: 0, in_progress: 1, planning: 2, planned: 2, failed: 3, complete: 4, ran: 4 };
    var byStatus = function (s) { return rank[s.effective_status || s.status] ?? 9; };
    var cmp = function (a, b) {
      var an = String(a.title || a.name), bn = String(b.title || b.name);
      if (sort === 'status') return byStatus(a) - byStatus(b) || an.localeCompare(bn);
      if (sort === 'studies_desc' || sort === 'recent') return (b.n_runs || 0) - (a.n_runs || 0) || an.localeCompare(bn);
      if (sort === 'studies_asc') return (a.n_runs || 0) - (b.n_runs || 0) || an.localeCompare(bn);
      return an.localeCompare(bn);
    };
    // Bucket studies by their investigation (ordered by _isetIndex; leftovers last).
    var groups = {};
    studies.forEach(function (s) {
      var inv = _investigationForStudy(s.name) || '__ungrouped__';
      (groups[inv] = groups[inv] || []).push(s);
    });
    var order = (window._isetIndex || []).map(function (i) { return i.name; })
      .filter(function (n) { return groups[n]; });
    if (groups.__ungrouped__) order.push('__ungrouped__');
    var GRID = 'display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin:6px 0 14px';
    var titleFor = function (inv) {
      if (inv === '__ungrouped__') return 'Ungrouped';
      var it = (window._isetIndex || []).find(function (i) { return i.name === inv; });
      return (it && (it.title || it.name)) || inv;
    };
    list.innerHTML = order.map(function (inv) {
      var items = groups[inv].slice().sort(cmp);
      return '<div class="iset-group" data-study-group="' + _esc(inv) + '">' +
        '<h3 class="iset-group-head" style="font-size:0.9em;color:#475569;font-weight:700;margin:10px 0 2px;text-transform:uppercase;letter-spacing:0.04em">' +
        _esc(titleFor(inv)) + ' <span style="color:#94a3b8;font-weight:600">(' + items.length + ')</span></h3>' +
        '<div class="investigations-grid" style="' + GRID + '">' +
        items.map(_studyBrowseCardHtml).join('') + '</div></div>';
    }).join('') +
      '<p id="investigations-empty" class="empty-state" style="display:none">No studies match the filter.</p>';
    _filterInvestigations();
  }
```

- [ ] **Step 5: Populate the tab counts in `_setIsetBrowseTab`**

In `_setIsetBrowseTab(tab)`, after the button-styling loop and before `_renderInvestigationSets()`, add:

```javascript
    var invCount = document.getElementById('iset-tab-inv-count');
    var studyCount = document.getElementById('iset-tab-study-count');
    if (invCount) invCount.textContent = (window._isetIndex || []).length || '';
    if (studyCount) studyCount.textContent = (window._investigations || []).length || '';
```

Also call this count-update once on initial render — at the end of `_renderInvestigationSets`, add (guarded so it is cheap):

```javascript
    var _ic = document.getElementById('iset-tab-inv-count');
    if (_ic) _ic.textContent = (window._isetIndex || []).length || '';
    var _sc = document.getElementById('iset-tab-study-count');
    if (_sc) _sc.textContent = (window._investigations || []).length || '';
```

- [ ] **Step 6: Parse + test**

Run:
```
node --check vivarium_workbench/static/walkthrough.js
python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('vivarium_workbench/templates')).get_template('index.html.j2')"
PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard python -m pytest tests/test_investigation_workspace.py -q
```
Expected: JS OK, template parses, 2 passed.

- [ ] **Step 7: Commit**

```bash
git add vivarium_workbench/static/walkthrough.js vivarium_workbench/templates/index.html.j2 tests/test_investigation_workspace.py
git commit -m "feat(explore): name the surface Explore; group Studies by investigation + tab counts"
```

---

## Task 2: Workspace regions markup + Explore ⇄ Viewing toggle

**Files:**
- Modify: `vivarium_workbench/templates/index.html.j2` (inside `#page-investigations`, after `#investigations-list`)
- Modify: `vivarium_workbench/static/walkthrough.js` (`_showExplore`, `_showWorkspace`)
- Test: `tests/test_investigation_workspace.py`

**Interfaces:**
- Produces: DOM ids `#iset-explore` (wraps the Explore surface), `#iset-workspace` (the viewing surface), `#ws-back` (← All investigations), `#ws-title`, `#ws-context` (collapsible graph+objective mount), `#ws-context-bar` (slim collapsed bar), `#ws-study-tabs` (tab bar mount), `#ws-study-frame` (study iframe). JS: `window._showExplore()`, `window._showWorkspace()`.
- Consumes (later tasks): these ids.

- [ ] **Step 1: Write the failing test**

```python
def test_workspace_regions_exist():
    for _id in ['iset-explore', 'iset-workspace', 'ws-back', 'ws-title',
                'ws-context', 'ws-context-bar', 'ws-study-tabs', 'ws-study-frame']:
        assert 'id="%s"' % _id in TPL, _id


def test_explore_workspace_toggle_functions():
    assert "function _showExplore" in JS
    assert "function _showWorkspace" in JS
    assert "window._showExplore" in JS
    assert "window._showWorkspace" in JS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard python -m pytest tests/test_investigation_workspace.py -k "workspace_regions or toggle_functions" -q`
Expected: FAIL (ids/functions absent).

- [ ] **Step 3: Wrap the Explore surface + add the workspace markup**

In `index.html.j2`, wrap the existing Explore controls (the `.iset-browse-header`, `.iset-browse-tabs`, search div, sort div, and `#investigations-list`) in a container, and add the workspace container after it. The `#page-investigations` body becomes:

```html
  <div id="iset-explore">
    <!-- (existing: .iset-browse-header, .iset-browse-tabs, search, sort, #investigations-list) -->
  </div>

  <div id="iset-workspace" style="display:none">
    <div style="display:flex;align-items:center;gap:12px;margin:0 0 10px">
      <button id="ws-back" class="btn-mini" onclick="_showExplore()" style="cursor:pointer">← All investigations</button>
      <strong id="ws-title" style="font-size:1.1em;color:#0f172a"></strong>
      <span id="ws-status" style="margin-left:6px"></span>
      <span id="ws-actions" style="margin-left:auto"></span>
    </div>
    <!-- slim collapsed bar (hidden until a study is open) -->
    <button id="ws-context-bar" onclick="_setInvestigationContextCollapsed(false)"
            style="display:none;width:100%;text-align:left;background:#f8fafc;border:1px solid #e5e7eb;border-radius:6px;padding:6px 12px;cursor:pointer;color:#475569;font-weight:600">▸ Investigation: <span id="ws-context-bar-name"></span></button>
    <!-- full investigation context (graph + objective) -->
    <div id="ws-context"></div>
    <!-- study tabs + porthole -->
    <div id="ws-study-tabs" style="display:none;border-bottom:1px solid #e5e7eb;margin:12px 0 0"></div>
    <div id="ws-study-panel" class="panel" style="display:none;margin-top:0;padding:0;overflow:hidden">
      <iframe id="ws-study-frame" src="" title="Study detail"
              style="width:100%;border:0;display:block"></iframe>
    </div>
  </div>
```

- [ ] **Step 4: Add the toggle functions in `walkthrough.js`**

Add near the other `_iset*` helpers (after `_setIsetBrowseTab`):

```javascript
  function _showExplore() {
    var ex = document.getElementById('iset-explore');
    var ws = document.getElementById('iset-workspace');
    if (ex) ex.style.display = '';
    if (ws) ws.style.display = 'none';
  }
  window._showExplore = _showExplore;

  function _showWorkspace() {
    var ex = document.getElementById('iset-explore');
    var ws = document.getElementById('iset-workspace');
    if (ex) ex.style.display = 'none';
    if (ws) ws.style.display = '';
  }
  window._showWorkspace = _showWorkspace;
```

- [ ] **Step 5: Route the Investigations nav item back to Explore**

Find the Investigations menu-link handler (search `data-page="investigations"` in `walkthrough.js`; there is an existing block that returns to the top-level list). At the end of that handler add a call so pressing the nav shows Explore, not a stale workspace:

```javascript
    if (typeof _showExplore === 'function') _showExplore();
```

- [ ] **Step 6: Parse + test**

Run:
```
node --check vivarium_workbench/static/walkthrough.js
python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('vivarium_workbench/templates')).get_template('index.html.j2')"
PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard python -m pytest tests/test_investigation_workspace.py -q
```
Expected: all passed.

- [ ] **Step 7: Commit**

```bash
git add vivarium_workbench/static/walkthrough.js vivarium_workbench/templates/index.html.j2 tests/test_investigation_workspace.py
git commit -m "feat(workspace): Explore/Viewing surfaces + toggle; workspace region markup"
```

---

## Task 3: Investigation-context collapse

**Files:**
- Modify: `vivarium_workbench/static/walkthrough.js` (`_setInvestigationContextCollapsed`)
- Test: `tests/test_investigation_workspace.py`

**Interfaces:**
- Consumes: `#ws-context`, `#ws-context-bar`, `#ws-context-bar-name`, `window._wsInvestigation` (set in Task 4/5).
- Produces: `window._setInvestigationContextCollapsed(collapsed)`; `window._wsContextCollapsed` (bool).

- [ ] **Step 1: Write the failing test**

```python
def test_context_collapse_function():
    assert "function _setInvestigationContextCollapsed" in JS
    assert "ws-context-bar" in JS
    # the slim bar's onclick re-expands
    assert "_setInvestigationContextCollapsed(false)" in TPL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard python -m pytest tests/test_investigation_workspace.py -k context_collapse -q`
Expected: FAIL.

- [ ] **Step 3: Implement the collapse toggle**

Add to `walkthrough.js`:

```javascript
  function _setInvestigationContextCollapsed(collapsed) {
    window._wsContextCollapsed = !!collapsed;
    var ctx = document.getElementById('ws-context');
    var bar = document.getElementById('ws-context-bar');
    var name = document.getElementById('ws-context-bar-name');
    if (ctx) ctx.style.display = collapsed ? 'none' : '';
    if (bar) bar.style.display = collapsed ? '' : 'none';
    if (name) name.textContent = window._wsInvestigation || '';
  }
  window._setInvestigationContextCollapsed = _setInvestigationContextCollapsed;
```

- [ ] **Step 4: Parse + test**

Run:
```
node --check vivarium_workbench/static/walkthrough.js
PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard python -m pytest tests/test_investigation_workspace.py -k context_collapse -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/static/walkthrough.js tests/test_investigation_workspace.py
git commit -m "feat(workspace): collapsible investigation context (graph <-> slim bar)"
```

---

## Task 4: Study-tabs manager

**Files:**
- Modify: `vivarium_workbench/static/walkthrough.js` (`_wsStudyTabs` state + `_wsOpenStudyTab` / `_wsCloseStudyTab` / `_wsRenderStudyTabs`)
- Test: `tests/test_investigation_workspace.py`

**Interfaces:**
- Consumes: `#ws-study-tabs`, `#ws-study-panel`, `#ws-study-frame`, `_studyHref(slug)`, `_esc(s)`, `_fitEmbedToViewport(frame, panel, minH)`, `_setInvestigationContextCollapsed(bool)`.
- Produces: `window._wsStudyTabs = {investigation, openTabs:[slug], active:slug|null}`; `window._wsOpenStudyTab(slug)`, `window._wsCloseStudyTab(slug)`, `window._wsRenderStudyTabs()`, `window._wsResetStudyTabs(investigation)`.

- [ ] **Step 1: Write the failing test**

```python
def test_study_tabs_manager():
    for fn in ["_wsOpenStudyTab", "_wsCloseStudyTab", "_wsRenderStudyTabs", "_wsResetStudyTabs"]:
        assert "function %s" % fn in JS, fn
        assert "window.%s" % fn in JS, fn
    # opening a tab collapses the context; closing the last returns to graph-only
    o = JS[JS.index("function _wsOpenStudyTab"): JS.index("function _wsOpenStudyTab") + 900]
    assert "_setInvestigationContextCollapsed(true)" in o
    c = JS[JS.index("function _wsCloseStudyTab"): JS.index("function _wsCloseStudyTab") + 900]
    assert "_setInvestigationContextCollapsed(false)" in c
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard python -m pytest tests/test_investigation_workspace.py -k study_tabs_manager -q`
Expected: FAIL.

- [ ] **Step 3: Implement the manager**

Add to `walkthrough.js`:

```javascript
  window._wsStudyTabs = { investigation: null, openTabs: [], active: null };

  function _wsResetStudyTabs(investigation) {
    window._wsStudyTabs = { investigation: investigation, openTabs: [], active: null };
    _wsRenderStudyTabs();
    var panel = document.getElementById('ws-study-panel');
    if (panel) panel.style.display = 'none';
    _setInvestigationContextCollapsed(false);   // fresh investigation -> graph expanded
  }
  window._wsResetStudyTabs = _wsResetStudyTabs;

  function _wsRenderStudyTabs() {
    var bar = document.getElementById('ws-study-tabs');
    if (!bar) return;
    var st = window._wsStudyTabs;
    if (!st.openTabs.length) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
    bar.style.display = '';
    bar.innerHTML = st.openTabs.map(function (slug) {
      var on = slug === st.active;
      return '<span class="ws-study-tab" data-ws-tab="' + _esc(slug) + '" ' +
        'style="display:inline-flex;align-items:center;gap:6px;padding:6px 10px;cursor:pointer;' +
        'border-bottom:2px solid ' + (on ? '#3b82f6' : 'transparent') + ';' +
        'color:' + (on ? '#0f172a' : '#64748b') + ';font-weight:' + (on ? '600' : '400') + ';margin-bottom:-1px">' +
        '<span onclick="_wsOpenStudyTab(\'' + _esc(slug) + '\')">' + _esc(slug) + '</span>' +
        '<span onclick="event.stopPropagation();_wsCloseStudyTab(\'' + _esc(slug) + '\')" ' +
        'title="close" style="color:#94a3b8;font-weight:700">×</span></span>';
    }).join('');
  }
  window._wsRenderStudyTabs = _wsRenderStudyTabs;

  function _wsOpenStudyTab(slug) {
    var st = window._wsStudyTabs;
    if (st.openTabs.indexOf(slug) === -1) st.openTabs.push(slug);
    st.active = slug;
    _wsRenderStudyTabs();
    var panel = document.getElementById('ws-study-panel');
    var frame = document.getElementById('ws-study-frame');
    if (panel) panel.style.display = '';
    if (frame) { frame.src = _studyHref(slug); }
    _setInvestigationContextCollapsed(true);    // study active -> context collapses
    if (typeof _fitEmbedToViewport === 'function') _fitEmbedToViewport(frame, panel, 560);
  }
  window._wsOpenStudyTab = _wsOpenStudyTab;

  function _wsCloseStudyTab(slug) {
    var st = window._wsStudyTabs;
    var i = st.openTabs.indexOf(slug);
    if (i !== -1) st.openTabs.splice(i, 1);
    if (st.active === slug) st.active = st.openTabs[Math.max(0, i - 1)] || st.openTabs[0] || null;
    _wsRenderStudyTabs();
    if (st.active) {
      _wsOpenStudyTab(st.active);                // re-focus nearest remaining tab
    } else {
      var panel = document.getElementById('ws-study-panel');
      if (panel) panel.style.display = 'none';
      _setInvestigationContextCollapsed(false);  // last tab closed -> graph-only
    }
  }
  window._wsCloseStudyTab = _wsCloseStudyTab;
```

- [ ] **Step 4: Parse + test**

Run:
```
node --check vivarium_workbench/static/walkthrough.js
PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard python -m pytest tests/test_investigation_workspace.py -k study_tabs_manager -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/static/walkthrough.js tests/test_investigation_workspace.py
git commit -m "feat(workspace): opened-only study-tabs manager (open/focus/close)"
```

---

## Task 5: `_showInvestigationWorkspace` + the single study-open router

**Files:**
- Modify: `vivarium_workbench/static/walkthrough.js` (`_showInvestigationWorkspace`, rewrite `_openStudyEmbeddedNewTab`, repoint `_openInvestigation` callers)
- Test: `tests/test_investigation_workspace.py`

**Interfaces:**
- Consumes: `_renderInvestigationDetailInto(name, mountEl)` (see Step 3 note), `_investigationForStudy(slug)`, `_wsResetStudyTabs`, `_wsOpenStudyTab`, `_selectStudyInRail`, `_showWorkspace`, `#ws-context`, `#ws-title`, `window._wsInvestigation`.
- Produces: `window._showInvestigationWorkspace(name)`; `_openStudyEmbeddedNewTab(slug)` now routes through the workspace.

- [ ] **Step 1: Write the failing test**

```python
def test_router_uses_workspace_not_legacy():
    assert "function _showInvestigationWorkspace" in JS
    r = JS[JS.index("function _openStudyEmbeddedNewTab"): JS.index("function _openStudyEmbeddedNewTab") + 1200]
    assert "_showInvestigationWorkspace" in r        # loads the study's own investigation
    assert "_wsOpenStudyTab" in r                    # opens/focuses the tab
    assert "window.location = _studyHref" not in r   # no dead-end full-window nav
    assert "_openInvestigation(" not in r            # never the legacy icon-view path


def test_showworkspace_renders_graph_not_legacy_icon_view():
    w = JS[JS.index("function _showInvestigationWorkspace"): JS.index("function _showInvestigationWorkspace") + 1200]
    assert "ws-context" in w
    assert "_showWorkspace" in w
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard python -m pytest tests/test_investigation_workspace.py -k "router_uses or showworkspace_renders" -q`
Expected: FAIL.

- [ ] **Step 3: Add `_showInvestigationWorkspace(name)`**

This renders the investigation's graph + objective into `#ws-context`. The existing `_openInvestigation`/detail render targets `#investigation-detail`; extract its graph+objective rendering into a reusable `_renderInvestigationDetailInto(name, mountEl)` if not already callable, then:

```javascript
  function _showInvestigationWorkspace(name) {
    if (!name) return;
    window._wsInvestigation = name;
    _showWorkspace();
    var title = document.getElementById('ws-title');
    if (title) title.textContent = 'Investigation: ' + name;
    var ctx = document.getElementById('ws-context');
    if (ctx) {
      // Always the graph + objective detail — NOT the legacy "Study:<inv>" icon view.
      if (typeof _renderInvestigationDetailInto === 'function') {
        _renderInvestigationDetailInto(name, ctx);
      } else if (typeof _openInvestigation === 'function') {
        // fallback: reuse the detail loader, then relocate its output into #ws-context
        _openInvestigation(name);
        var src = document.getElementById('investigation-detail');
        if (src && src !== ctx) ctx.innerHTML = src.innerHTML;
      }
    }
    _wsResetStudyTabs(name);   // graph expanded, no study open
  }
  window._showInvestigationWorkspace = _showInvestigationWorkspace;
```

> Implementation note for the fallback branch: verify against the running server that `#investigation-detail` holds the graph + objective (it does for v3; for a v2-shape spec confirm it is NOT the legacy `Study: <name>` icon markup — if it is, render the graph+objective directly from `/api/investigation/<name>` instead). Prefer extracting `_renderInvestigationDetailInto` so the workspace never touches the legacy path.

- [ ] **Step 4: Rewrite `_openStudyEmbeddedNewTab(slug)` as the single router**

Replace the whole function body with:

```javascript
  function _openStudyEmbeddedNewTab(name) {
    // Single router: always show the study's OWN investigation workspace, then
    // open/focus its study tab. Never the legacy investigation-as-study icon view,
    // never a dead-end full-window navigation, never a stale investigation above.
    var inv = _investigationForStudy(name);
    if (inv) {
      if (window._wsInvestigation !== inv) _showInvestigationWorkspace(inv);
      else _showWorkspace();
      _wsOpenStudyTab(name);
    } else {
      // Ungrouped study: minimal workspace (no graph), just the study tab.
      window._wsInvestigation = null;
      _showWorkspace();
      var ctx = document.getElementById('ws-context'); if (ctx) ctx.innerHTML = '';
      var title = document.getElementById('ws-title'); if (title) title.textContent = 'Study: ' + name;
      _wsResetStudyTabs(null);
      _wsOpenStudyTab(name);
    }
    _selectStudyInRail(name);
  }
  window._openStudyEmbeddedNewTab = _openStudyEmbeddedNewTab;
```

- [ ] **Step 5: Route investigation-open (cards + rail) through the workspace**

Repoint the investigation-open entry points to the workspace:
- `_vivOpenInvestigationFromRail(name)` and the investigation-card `onclick` handler (`_openInvestigationDetail`) should call `_showInvestigationWorkspace(name)` instead of `_openInvestigation(name)`. Update those call sites (search `_openInvestigationDetail` and `_vivOpenInvestigationFromRail` in `walkthrough.js`) to:

```javascript
    if (typeof _showInvestigationWorkspace === 'function') _showInvestigationWorkspace(name);
    else _openInvestigation(name);
```

- [ ] **Step 6: Parse + test**

Run:
```
node --check vivarium_workbench/static/walkthrough.js
PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard python -m pytest tests/test_investigation_workspace.py -q
```
Expected: all passed.

- [ ] **Step 7: Live smoke check**

```bash
cd /Users/eranagmon/code/v2e-goldstd
PID=$(lsof -ti tcp:8796); [ -n "$PID" ] && kill "$PID"; sleep 2
PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard nohup vivarium-workbench serve --workspace /Users/eranagmon/code/v2e-goldstd --port 8796 >/tmp/wb.log 2>&1 &
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8796/
curl -s http://127.0.0.1:8796/assets/walkthrough.js | grep -c "_showInvestigationWorkspace"
```
Expected: `200`, and `>0`. Then manually in the browser (⌘⇧R): open a v3 investigation (colonies) and a v2 one (v2ecoli-vecoli-comparison) from a card, the rail, and a study — confirm each lands the study in the workspace under its own investigation with the context collapsed, and NO "Baseline Composite" legacy tabs appear.

- [ ] **Step 8: Commit**

```bash
git add vivarium_workbench/static/walkthrough.js tests/test_investigation_workspace.py
git commit -m "feat(workspace): single study-open router via _showInvestigationWorkspace; retire legacy v2 study-as-investigation view"
```

---

## Task 6: Regression sweep + cleanup

**Files:**
- Modify (only if a regression surfaces): `vivarium_workbench/static/walkthrough.js`
- Test: existing suites

**Interfaces:** none new.

- [ ] **Step 1: Run the SPA structure suites that touch these files**

Run:
```
PYTHONPATH=/Users/eranagmon/code/vivarium-dashboard python -m pytest \
  tests/test_investigation_workspace.py tests/test_pillar_unify.py \
  tests/test_study_detail_page.py tests/test_report_card_promotion.py -q
```
Expected: all passed. If `test_pillar_unify` (or another) asserts a now-removed behavior (e.g. an old `_openStudyEmbeddedNewTab` full-window fallback), update that test to the new contract in the same commit — do not weaken coverage, re-point it.

- [ ] **Step 2: Confirm the old flat-catalog studies path is not double-serving**

The Studies browse now lives only as the Explore tab; the legacy `#page-studies` porthole path is superseded by the workspace. Verify no entry point still calls `_openStudyEmbedded` (the old page-studies porthole) — search `walkthrough.js`; if a stray caller remains, repoint it to `_openStudyEmbeddedNewTab`.

Run: `grep -n "_openStudyEmbedded\b" vivarium_workbench/static/walkthrough.js`
Expected: only the definition + `window._openStudyEmbedded` export remain (no live callers), or callers are repointed.

- [ ] **Step 3: Commit any regression fixes**

```bash
git add -A
git commit -m "test(workspace): reconcile SPA structure suites with the workspace router"
```

- [ ] **Step 4: Push**

```bash
git push
```

---

## Self-Review

**Spec coverage:**
- Explore surface (name, Registry-style tab row + counts, Investigations Active/Closed, **Studies grouped by investigation**, Sort within groups) → Task 1. ✓
- Two surfaces + Explore⇄Viewing toggle, return via nav + "← All investigations" → Task 2. ✓
- Workspace layout (header w/ status+Report/Notebook, collapsible context, study-tabs bar, porthole) → Tasks 2 (markup) + 3 (collapse) + 4 (tabs). ✓ *(Report/Notebook + status wiring into `#ws-actions`/`#ws-status` is part of Task 5's `_showInvestigationWorkspace` — it populates the header from the iset summary; if omitted there, add a step to copy the card's report/notebook actions into `#ws-actions`.)*
- Behaviors: open investigation (expanded, empty tabs), open study (pops in + collapses), slim-bar re-expand, close-last→graph-only, retain tabs across toggle → Tasks 3–5. ✓ (retain-tabs: `_wsStudyTabs` persists across `_showExplore`/`_showWorkspace` since it is module state; only `_wsResetStudyTabs` clears it, called only on a *new* investigation.)
- Single router + no stale context + v2/v3 legacy retirement → Task 5. ✓
- Sidebar rail consistency + `_selectStudyInRail` → Task 5 (router) reuses the existing rail highlight. ✓
- Edge cases (v2 shape, cross-investigation study, deep link, snapshot, reopen restores tabs) → covered in Task 5 + retained state. ✓

**Placeholder scan:** no "TBD"/"add error handling"/"similar to Task N" — each code step shows the code. One explicit verify-against-server note in Task 5 Step 3 (the v2 detail-markup check) is a real verification action, not a placeholder.

**Type consistency:** `_wsStudyTabs`/`_wsOpenStudyTab`/`_wsCloseStudyTab`/`_wsRenderStudyTabs`/`_wsResetStudyTabs`, `_showInvestigationWorkspace`, `_showExplore`/`_showWorkspace`, `_setInvestigationContextCollapsed`, `window._wsInvestigation` — used consistently across Tasks 2–5. DOM ids (`ws-context`, `ws-context-bar`, `ws-study-tabs`, `ws-study-panel`, `ws-study-frame`, `iset-explore`, `iset-workspace`) match between the Task 2 markup and their consumers.
