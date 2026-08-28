# What the UI actually calls

**Snapshot taken 2026-08-28** against `main` at the merge of #962.
Companion to [`workbench-api-survey.md`](workbench-api-survey.md), which describes
the API from the server side; this one comes at it from the client.

**A description, not a standard.** It records which endpoints the shipped UI
invokes, how it builds those URLs, and which routes no live client touches — so
refactoring can start from measurement. Where something looks like drift it is
written down as drift. Expect it to age; *How to re-derive* at the end says how to
regenerate every number.

---

## 1. Method, and its blind spot

Endpoints were extracted by scanning the **shipped** UI surfaces —
`vivarium_workbench/static/*.js` (21 files), `templates/`, `loom/_dist`,
`loom/bigraph_loom`, and `lib/report.py` — for `/api/…` literals, then matched
against the 259 registered routes (path params matched on their prefix).

**The blind spot is real and worth stating first.** The UI builds some URLs by
concatenation:

```js
"/api/" + …        '/api/' + …        "/api/registry" + …        '/api/inputs' + …
```

Those cannot be resolved statically. Every "not referenced" claim below therefore
means *"no static reference found"*, not *"provably uncalled"* — 13 routes were
recovered only by widening the search, and a dynamically-built name could still
hide. Treat the orphan list as **candidates to verify**, never as a delete list.

`tests/_fixtures/*/reports/assets/*.js` are **generated copies of the UI** and are
excluded from "the UI". They matter anyway — see §5.

## 2. Who calls what

| UI file | endpoints | size |
|---|---:|---:|
| **`walkthrough.js`** | **118** | **819 KB** |
| `study-detail.js` | 37 | 175 KB |
| `data-source.js` | 22 | 13 KB |
| `branch-source.js` | 9 | 35 KB |
| `configure-run.js` | 7 | 16 KB |
| `workspace-switcher.js` | 7 | 9 KB |
| `github-login.js`, `sim-table.js` | 6 | 11 / 36 KB |
| `source-switch.js` | 5 | 10 KB |
| `client.js` | 4 | 1 KB |
| `session-status.js`, `workspace-picker.js` | 3 | 7 / 17 KB |
| `investigation-switcher.js`, `loom-embed.js`, `session.js` | 2 | 5–19 KB |
| `audit.js`, `composite-card.js`, `progress-track.js` | 1 | 8–42 KB |

Totals: **178** distinct endpoints across `static/`, **28** in `templates/`, **12**
in `loom/_dist`.

**`walkthrough.js` is the system's real client.** At 819 KB it touches 118
endpoints — roughly **62% of the used API surface from a single file**. Its header
is a one-line changelog running from v0.1.7 to v0.8.0 covering registry views,
composites, marketplace, investigations and study panels: it is the dashboard SPA,
accumulated rather than designed. Any API refactor is, in practice, a
`walkthrough.js` refactor.

The long tail is the opposite shape — `composite-card.js` is 42 KB for **one**
endpoint, so size and API-coupling are independent.

## 3. Three ways to build a URL

Not one convention, three:

1. **`report.py::_base_path_shim`** — injected into `<head>`, patches `fetch`,
   `EventSource`, `XMLHttpRequest` to prefix root-absolute URLs. Covers *requests*.
2. **`DataSource.apiUrl(p)`** — `walkthrough.js` wraps every call in a local
   `_api(p)` that delegates here, with a comment explaining it exists so
   composite-explore calls "reach the workbench under the co-tenant ALB instead of
   misrouting to sms-api → 404".
3. **`window.__BASE_PATH__` read directly** — required for *navigations*
   (`window.open`, `window.location`), which the shim cannot patch. Six sites got
   this wrong and were fixed in #960; `tests/js/test_base_path_navigation.js` now
   guards the class.

That three mechanisms coexist — and that the shim's coverage gap had to be
discovered by a user hitting PTools — is the clearest UI-side refactoring signal
in this document.

## 4. Endpoint usage

Of **259** routes (excluding the `/{rel:path}` static catch-all):

| classification | count |
|---|---:|
| called by the live UI | 191 |
| called by the live UI via a dynamically-built URL | 13 |
| **referenced only by tests** | **46** |
| referenced only by an *older* UI snapshot | 7 |
| referenced nowhere | 1 |
| CLI / publish only (`/health`) | 1 |

**204 of 259 routes (79%) have a live UI caller.**

The **46 tests-only** routes are the interesting bulk. Test coverage without a
caller means one of three things, and the survey cannot distinguish them
statically: an endpoint for external clients, an endpoint reached by a
dynamically-built URL, or a genuinely stranded feature. Each needs a caller-side
check before any conclusion.

## 5. Endpoints the UI dropped

Seven routes appear **only** in `tests/_fixtures/ws_increase_demo/reports/assets/`,
a generated snapshot of an older UI (2,622 lines vs the live `study-detail.js`'s
3,490). They were called once; the live UI no longer calls them:

```
/api/study-variant-add          /api/study-intervention-add
/api/study-variant-delete       /api/study-intervention-delete
/api/study-variant-set-params   /api/study-intervention-update
/api/remote-run-pinned-build
```

The `study-variant-*` family looks **superseded rather than abandoned**: the live
`study-detail.js` calls `study-baseline-add` and `study-baseline-remove`, which
have no fixture-era counterpart. So the UI moved from a *variant* vocabulary to a
*baseline* one and the older server routes stayed. `study-variant-rebuild` is
registered too and appears in neither.

Worth separating from those: **`/api/study-run-variant` has no live UI caller
either, but is load-bearing** — it is in the `READONLY` allowlist, and
`run_unblocked_views._worker` drives study runs through the *lib* function
`study_runs.run_study_variant`. That distinction generalizes:

> **The lib builders are the reuse surface; routes are only one entry point.**
> A route with no caller does not imply the capability is unused.

`/api/study-runs-clear` is the single route with no reference anywhere — no UI, no
test, no CLI, no fixture.

## 6. Load-bearing endpoints

By breadth of UI files referencing them (a proxy for how much breaks if the shape
changes):

| endpoint(s) | UI files |
|---|---:|
| `/api/composite-resolve` | 8 |
| `/api/workspaces` | 6 |
| `/api/composite-run/{run_id}` + `/status` `/state` `/download` `/artifact/{name}` `/stop` | 5 each |
| `/api/composite-state`, `/api/composite-state/{ref:path}` | 5 |
| `/api/composite-test-run` | 5 |
| `/api/source/switch` | 5 |
| `/api/simulations` | 4 |

The `composite-run/{run_id}/*` family is the **run-lifecycle spine** — submit,
poll, inspect, download, stop — and it is what makes dispatched runs observable in
the browser regardless of whether they executed locally or on Batch (`_execute_remote`
writes the same `composite-runs.db` rows). Changing that family's shape is the
most expensive API change available.

`/api/composite-resolve` at 8 files is the widest single dependency.

## 7. Seams for refactoring

Observed, not proposed.

1. **One file holds most of the client.** `walkthrough.js` — 819 KB, 118
   endpoints, a changelog for a header. Splitting it is a precondition for most
   UI-side work, and its `_api()` wrapper shows it already knows the base-path
   problem better than the shim does.
2. **Three URL-construction mechanisms** (§3), with the gap between them having
   produced a user-visible bug.
3. **A superseded endpoint family still registered** (§5): `study-variant-*` /
   `study-intervention-*` vs the live `study-baseline-*`.
4. **46 tests-only routes** — the largest pool of possibly-stranded surface, and
   the one place where tests give false confidence: they prove the endpoint
   *works*, not that anything *wants* it.
5. **Generated fixture copies of UI assets drift from the originals** and are old
   enough (868 lines behind on one file) to be mistaken for current. They were
   useful here as an accidental archaeological record, which is not a good reason
   to keep them diverging.

## How to re-derive

- **Routes:** parse `@app.<method>("<path>", … tags=[…])` out of `api/app.py`.
- **UI references:** scan `static/`, `templates/`, `loom/_dist`,
  `loom/bigraph_loom`, `lib/report.py` for `/api/[A-Za-z0-9_-]+(/…)*`. Do **not**
  anchor the regex to a preceding quote — that misses template literals and was
  the first version's error (13 false orphans).
- **Classification:** for each route with no static UI hit, grep the path stem
  across `vivarium_workbench/` and `tests/`, bucketing by live UI / `_fixtures` /
  tests / CLI.
- **Load-bearing:** rank used routes by the number of distinct UI files
  referencing them.
- **Dynamic-URL blind spot:** `grep -E "['\"\`]/api/[a-z-]*['\"\`]?\s*\+"` over
  `static/*.js` to see what cannot be resolved statically.
