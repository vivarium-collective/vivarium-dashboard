# Workspace Picker — pinned-commit mechanics

The "Workspace: `<name>` ▾" control in the rail header (`vivarium_workbench/static/workspace-picker.js`,
372 lines) is the one place in the UI where a user picks which workspace — local
or remote-pinned — a browser tab is going to look at. Its behavior around
*remote* rows is easy to misread: does the dropdown let you re-point what a tab
is looking at, or only let you open something new? Is the "pinned commit" a
remote dispatch resolves against (the `{repo_url, branch, commit, simulator_id}`
that e.g. `GET /api/remote-run-config` returns) the same thing as "whatever
workspace this tab currently shows"? This doc answers both, straight from the
source, with citations so you can verify directly rather than trust the prose.

**Short answer:** for a remote-pinned tab, the pinned commit *is* the tab's
active workspace — not two things that happen to agree, but one binding with
two names. Sections 5-6 spell out why; sections 1-4 walk the mechanics that
make it true.

## 1. What the dropdown actually lists

Opening the trigger fires two requests in parallel and merges the results
(`workspace-picker.js:331-347`):

- `GET /api/workspaces` — the dashboard's own local workspace catalog (name,
  label, status, path).
- `GET /api/source/builds` — viva-api's flat build history. (The UI's own code
  comments still call this backend "sms-api" — that's leftover naming from
  before the repo rename, cosmetic only; see `docs/remote-govcloud-onboarding.md`.)

`normalizeRemoteBuilds()` (`workspace-picker.js:47-72`) does not list every
build — it reduces the build history to **one row per distinct repo, that
repo's single most recent build**:

```js
// workspace-picker.js:54-72
function normalizeRemoteBuilds(builds) {
  var latest = {};
  (builds || []).forEach(function (b) {
    if (!b || !b.repo) return;
    var prev = latest[b.repo];
    if (!prev || String(b.created_at || "") > String(prev.created_at || "")) {
      latest[b.repo] = b;
    }
  });
  return Object.keys(latest).sort().map(function (repo) {
    var b = latest[repo];
    return {
      name: null, path: "remote:" + repo, kind: "remote",
      status: "remote", simulator_id: b.simulator_id,
      label: b.repo + " @ " + String(b.commit || "").slice(0, 7)
        + " (build #" + b.simulator_id + ") [" + (b.branch || "") + "]",
    };
  });
}
```

Label format: `"{repo} @ {commit:.7} (build #{simulator_id}) [{branch}]"` —
e.g. `sms-ecoli @ 8d50ff0 (build #62) [main]`.

## 2. Older builds are excluded on purpose, not by oversight

The function's own comment (`workspace-picker.js:47-53`) states the intent
directly: this list's job is "get me into a repo quickly," not replicate the
full build picker. The merge site's comment (`workspace-picker.js:331-334`)
makes the same point from the history side — before this dropdown existed,
remote builds "were reachable only through the separate Source panel, which a
user switching workspaces had no reason to know existed."

Earlier commits/builds of the *same* repo are real and still buildable/
runnable — they are just not rows in this dropdown. They stay reachable
through that row's **"Branch settings ↗"** link (`workspace-picker.js:311`),
which opens the full Source panel (`goSource()`, `workspace-picker.js:127-130`)
— a separate, fuller UI surface with the complete build history.

Practically: this dropdown answers "which repos have I got a build for, and
what's the latest," not "show me every commit I've ever built."

## 3. Clicking a row: `openWs()`

`openWs(ws, newTab)` (`workspace-picker.js:154-181`) is the single click
handler behind every row. It branches on `ws.kind`.

**Remote rows** (`kind: "remote"`) always spawn a new tab, unconditionally —
`newTab` is not even consulted:

```js
// workspace-picker.js:157-164
if (ws && ws.kind === "remote") {
  // Same URL shape branch-source.js's Open button already uses —
  // session.js's ?build= bootstrap materializes it and binds this new
  // tab's session, honoring the base path behind the shared ALB.
  var bp = window.__BASE_PATH__ || "";
  window.open(bp + "/?build=" + encodeURIComponent(ws.simulator_id), "_blank");
  return;
}
```

**Local rows** get two independent actions the render loop wires up
separately (`workspace-picker.js:235-250`), guarded by `if (!isRemote)` /
`if (ws.name || isRemote)`:

- **"Switch"** — `POST /api/source/switch` with the workspace's path, then
  `location.reload()` (`workspace-picker.js:173-177`). Re-points *this* tab
  in place.
- **"Open ↗"** — `window.open` to the workspace's own running-server URL, or a
  `/?workspace=<name>` bootstrap if none is running yet
  (`workspace-picker.js:165-172`).

Remote rows get **only** "Open ↗" — never "Switch." The code comment explains
why in plain terms (`workspace-picker.js:228-232`):

> Local workspaces get two actions (Switch this tab / Open in a new tab);
> remote sms-api builds are session-per-tab only (branch-source.js established
> this: `window.open('/?build=<id>')` spawns a fresh per-tab session — there
> is no in-place "switch this tab" for a remote build), so they get Open ↗
> only.

Row-clicks default accordingly — clicking anywhere on a remote row behaves as
"Open," a local row as "Switch" (`workspace-picker.js:253`:
`openWs(ws, isRemote)`).

## 4. The current tab's own row is inert

If a row's `status === "current"`, `render()` skips both action buttons
entirely and shows a plain `"current"` tail badge instead
(`workspace-picker.js:222-227`). There is no self-select — clicking a tab's
own row does nothing, by design.

## 5. Design intent: session-per-tab, pinned-for-life

The file's own top-of-file comment states the governing design directly
(`workspace-picker.js:3-8`):

> A always-visible "Workspace: `<name>` ▾" control in the rail header opens a
> searchable dropdown of workspaces. Picking one honors session-per-tab
> (pinned-for-life): it SPAWNS a new browser tab bound to that workspace via
> `window.open('/?workspace=<catalog-name>')` — session.js's `?workspace=`
> bootstrap force-mints a fresh per-tab session and binds it — rather than
> re-pointing this tab. The current tab's workspace shows a "current" badge
> and is inert.

The same bootstrap pattern applies to remote rows via `?build=<simulator_id>`
(section 3). `session.js` (`vivarium_workbench/static/session.js`) is the
consumer on the other end — per workspace-picker.js's own comments, it reads
the `?build=`/`?workspace=` query param on load, force-mints a fresh session
for that tab, and binds it for the tab's lifetime.

**Cross-reference note:** `docs/session-binding.md` and
`docs/session-registry.md` describe this per-tab session model as a design
proposal — each is headed "Status: proposed... Not implemented" as written.
`workspace-picker.js` is live, shipping code that already implements the
per-tab bootstrap those docs proposed. Read those two docs as design
*rationale* for why the model looks the way it does, not as a status tracker
for whether it's built — for this specific mechanic, it already is.

## 6. Direct answer: is "pinned commit" the same as "the tab's active workspace"?

**Yes, for a remote-pinned tab — they are the same binding, not two things
that happen to match.**

A tab's session is bound, for its entire lifetime, to whatever `simulator_id`
(and the `{repo_url, branch, commit}` that build resolves to) it was opened
against via the `?build=` bootstrap. There is no separate "pin" that could
drift independently of "what the tab is looking at": `GET
/api/remote-run-config`'s resolved `{commit, simulator_id}` for that tab is
reading back exactly the binding `session.js` set at tab-open time, not a
second, independently-mutable pointer.

The absence of a "Switch" action on remote rows (section 3) is the same fact
from the other direction: there is no code path anywhere in this file that
re-points a live tab's remote pin. The only in-place re-pointing mechanism
(`POST /api/source/switch`) is local-workspace-only by construction
(`if (!isRemote)` at `workspace-picker.js:235`).

## 7. Practical implication: working against a different commit

Because a remote pin can't be changed in place, reaching a *different* commit
than the one currently pinned in this tab always means opening a **new tab**:

- If the target is the single most recent build for that repo, its row is
  already in this dropdown — click "Open ↗" (or the row itself; both call
  `openWs(ws, true)` for a remote row).
- If the target is an older build of that repo, or a commit that hasn't been
  built yet, this dropdown will not show it (section 2) — use that repo's
  **"Branch settings ↗"** link into the full Source panel, which lists the
  complete build history and can register a new build.

Either path opens a new tab with its own independent per-tab session; neither
one touches the tab you started from.

## 8. Related docs

- [`session-binding.md`](session-binding.md),
  [`session-registry.md`](session-registry.md) — design background for the
  per-tab session model this file assumes as already real (see the
  cross-reference note in section 5 for their status-vs-shipped-code nuance).
- [`remote-govcloud-onboarding.md`](remote-govcloud-onboarding.md) — how to
  reach a remote viva-api backend at all (SSM tunnel setup) before the
  dropdown's remote rows have anything to show.
- [`dashboard-api-vs-sms-api.md`](dashboard-api-vs-sms-api.md) — the
  local-dashboard/remote-backend split this file straddles: `GET
  /api/workspaces` is dashboard-owned, `GET /api/source/builds` proxies
  viva-api's simulator-build history.
