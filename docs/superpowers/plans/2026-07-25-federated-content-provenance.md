# Federated Ecosystem Content + Provenance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an installed ecosystem module's composites, studies, and investigation-sets appear read-only in the current workspace — each tagged with its origin repo — and finish the Marketplace tab so installs land the full repo on disk.

**Architecture:** A new `lib/federation.py` discovers "linked workspaces" (installed modules that ship a `workspace.yaml`), landed at `<ws>/external/<name>/` by the full-repo install path. Its enumerators return that content tagged with `origin_repo` + `read_only`, using namespaced ids so foreign items never collide with local ones. The existing study / investigation-set / composite list builders merge in the federated items; the frontend renders an origin-repo badge and a read-only treatment on each card. All federation helpers are best-effort (a broken linked workspace is skipped, never raising).

**Tech Stack:** Python 3.12, FastAPI, pydantic (`extra="allow"` passthrough models), pytest with the `dashboard_client` subprocess fixture, vanilla JS (`walkthrough.js`).

## Global Constraints

- **Read-only federation:** foreign content is never copied or mutated; foreign items carry `read_only: true` and hide mutate/run/delete affordances regardless of authoring mode.
- **Namespaced ids:** federated studies/investigation-sets use `"<repo>::<local_id>"`; composites keep their inherently-namespaced `"<pkg>.composites.<stem>"` id.
- **Best-effort, never 500:** every federation helper swallows per-workspace errors and returns partial results; a malformed linked workspace is skipped.
- **Additive fields only:** `origin_repo` (str|null), `read_only` (bool, default false), `investigations` (str[], studies only) default to null/false/[] so existing consumers and the published static bundle render unchanged.
- **Federation source of truth:** linked workspaces live at `<ws_root>/external/<name>/` (git full-repo install path) plus any editable-installed module whose package resolves to a repo root containing `workspace.yaml`. The current workspace is always excluded (dedupe by resolved root).
- **`origin_repo` display name:** the linked workspace's `workspace.yaml` `name`, else its directory name.

---

### Task 1: `lib/federation.py` — linked-workspace discovery

**Files:**
- Create: `vivarium_workbench/lib/federation.py`
- Create: `tests/_fixtures/ws_federation_demo/` (fixture workspace, see Step 1)
- Test: `tests/test_federation.py`

**Interfaces:**
- Produces:
  - `class LinkedWorkspace` — dataclass `{repo: str, root: Path, layout: WorkspacePaths}`.
  - `linked_workspaces(ws_root: Path) -> list[LinkedWorkspace]` — every linked workspace for `ws_root`, deduped by resolved root, excluding `ws_root` itself.

- [ ] **Step 1: Build the fixture workspace**

Create a fixture with one linked workspace under `external/`:

```
tests/_fixtures/ws_federation_demo/
  workspace.yaml                      # name: host_ws
  external/
    donor/
      workspace.yaml                  # name: donor-repo
      studies/
        donor_study/study.yaml        # name: donor_study  (minimal v3: name, description, baseline: [])
      investigations/
        donor_inv/investigation.yaml  # name: donor_inv, studies: [donor_study]
      donor/composites/
        donor.composite.yaml          # name: donor_comp, state: {}, description: "d"
  external/
    broken/                           # malformed: workspace.yaml is not valid yaml
      workspace.yaml                  # content: ":\n  - ["
```

`host_ws/workspace.yaml`:
```yaml
name: host_ws
```
`external/donor/workspace.yaml`:
```yaml
name: donor-repo
package_path: donor
```
`external/donor/studies/donor_study/study.yaml`:
```yaml
name: donor_study
description: A donor study.
baseline:
  - {name: base, composite: donor.composites.donor}
```
`external/donor/investigations/donor_inv/investigation.yaml`:
```yaml
name: donor_inv
description: Donor investigation.
studies: [donor_study]
```
`external/donor/donor/composites/donor.composite.yaml`:
```yaml
name: donor_comp
description: d
state: {}
```
`external/broken/workspace.yaml`:
```yaml
":
  - ["
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_federation.py
from pathlib import Path
from vivarium_workbench.lib.federation import linked_workspaces

FIX = Path(__file__).parent / "_fixtures" / "ws_federation_demo"

def test_linked_workspaces_finds_donor_and_skips_broken():
    links = linked_workspaces(FIX)
    repos = {lw.repo for lw in links}
    assert "donor-repo" in repos          # name from workspace.yaml
    assert all(lw.root.name != "host_ws" for lw in links)  # excludes self
    # broken external dir must not raise and must not appear
    assert "broken" not in {lw.root.name for lw in links}

def test_linked_workspaces_empty_when_no_external(tmp_path):
    (tmp_path / "workspace.yaml").write_text("name: solo\n")
    assert linked_workspaces(tmp_path) == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_federation.py -v`
Expected: FAIL — `ModuleNotFoundError: vivarium_workbench.lib.federation`

- [ ] **Step 4: Implement `linked_workspaces`**

```python
# vivarium_workbench/lib/federation.py
"""Read-only federation of installed ecosystem modules' content.

A "linked workspace" is an installed module that ships a workspace.yaml — landed
on disk at <ws_root>/external/<name>/ by the marketplace's full-repo install
path (or editable-installed to a repo root). Its studies, investigation-sets,
and composites are surfaced read-only in the host workspace, each tagged with
its origin repo. All helpers are best-effort: a malformed linked workspace is
skipped, never raising, so the host workspace's own listings always render.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from vivarium_workbench.lib.workspace_paths import WorkspacePaths


@dataclass
class LinkedWorkspace:
    repo: str          # display name (workspace.yaml `name`, else dir name)
    root: Path         # repo root on disk
    layout: WorkspacePaths


def _repo_name(root: Path) -> str:
    try:
        data = yaml.safe_load((root / "workspace.yaml").read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("name"):
            return str(data["name"])
    except Exception:
        pass
    return root.name


def linked_workspaces(ws_root: Path) -> list[LinkedWorkspace]:
    ws_root = Path(ws_root).resolve()
    seen: set[Path] = {ws_root}
    out: list[LinkedWorkspace] = []
    ext = ws_root / "external"
    if ext.is_dir():
        for child in sorted(ext.iterdir()):
            if not child.is_dir() or not (child / "workspace.yaml").is_file():
                continue
            root = child.resolve()
            if root in seen:
                continue
            try:
                layout = WorkspacePaths.load(root)
            except Exception:
                continue
            seen.add(root)
            out.append(LinkedWorkspace(repo=_repo_name(root), root=root, layout=layout))
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_federation.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add vivarium_workbench/lib/federation.py tests/test_federation.py tests/_fixtures/ws_federation_demo
git commit -m "feat(federation): discover linked workspaces under external/"
```

---

### Task 2: `federation.py` — study / investigation-set / composite enumerators

**Files:**
- Modify: `vivarium_workbench/lib/federation.py`
- Test: `tests/test_federation.py`

**Interfaces:**
- Consumes: `linked_workspaces`, `LinkedWorkspace` (Task 1).
- Produces:
  - `federated_studies(ws_root: Path) -> list[dict]` — each `{name, id, origin_repo, read_only, spec}` where `id = "<repo>::<study_name>"` and `spec` is the raw study.yaml dict.
  - `federated_investigation_sets(ws_root: Path) -> list[dict]` — each `{name, id, origin_repo, read_only, spec, member_studies}` where `id = "<repo>::<inv_name>"` and `member_studies` is the namespaced ids of its studies (`"<repo>::<study>"`).
  - `federated_composites(ws_root: Path) -> dict[str, dict]` — `{spec_id: record}` for composites under each linked workspace's `<package_path>/composites/`, each record tagged `origin_repo` + `read_only`, keyed by the same `"<pkg>.composites.<stem>"` id `composite_lookup` uses.

- [ ] **Step 1: Write the failing test**

```python
from vivarium_workbench.lib.federation import (
    federated_studies, federated_investigation_sets, federated_composites,
)

def test_federated_studies_tagged_and_namespaced():
    studies = federated_studies(FIX)
    ds = next(s for s in studies if s["name"] == "donor_study")
    assert ds["origin_repo"] == "donor-repo"
    assert ds["read_only"] is True
    assert ds["id"] == "donor-repo::donor_study"

def test_federated_investigation_sets_member_studies_namespaced():
    isets = federated_investigation_sets(FIX)
    di = next(i for i in isets if i["name"] == "donor_inv")
    assert di["origin_repo"] == "donor-repo"
    assert di["id"] == "donor-repo::donor_inv"
    assert di["member_studies"] == ["donor-repo::donor_study"]

def test_federated_composites_tagged():
    comps = federated_composites(FIX)
    rec = next(r for r in comps.values() if r.get("name") == "donor_comp")
    assert rec["origin_repo"] == "donor-repo"
    assert rec["read_only"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_federation.py -k federated -v`
Expected: FAIL — `ImportError: cannot import name 'federated_studies'`

- [ ] **Step 3: Implement the enumerators**

```python
# append to vivarium_workbench/lib/federation.py
from vivarium_workbench.lib.composite_lookup import (
    discover_workspace_composites, load_spec,  # existing helpers
)


def _iter_study_specs(lw: LinkedWorkspace):
    """Yield (study_name, spec_dict) for a linked workspace's studies."""
    sdir = lw.layout.studies
    if not sdir.is_dir():
        return
    for d in sorted(p for p in sdir.iterdir() if p.is_dir()):
        f = d / "study.yaml" if (d / "study.yaml").is_file() else d / "spec.yaml"
        if not f.is_file():
            continue
        try:
            spec = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        name = spec.get("name") or d.name
        yield name, spec


def federated_studies(ws_root: Path) -> list[dict]:
    out: list[dict] = []
    for lw in linked_workspaces(ws_root):
        try:
            for name, spec in _iter_study_specs(lw):
                out.append({
                    "name": name,
                    "id": f"{lw.repo}::{name}",
                    "origin_repo": lw.repo,
                    "read_only": True,
                    "spec": spec,
                })
        except Exception:
            continue
    return out


def federated_investigation_sets(ws_root: Path) -> list[dict]:
    out: list[dict] = []
    for lw in linked_workspaces(ws_root):
        idir = lw.layout.investigations
        if not idir.is_dir():
            continue
        for d in sorted(p for p in idir.iterdir() if p.is_dir()):
            f = d / "investigation.yaml"
            if not f.is_file():
                continue
            try:
                spec = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            name = spec.get("name") or d.name
            members = [f"{lw.repo}::{s}" for s in (spec.get("studies") or [])]
            out.append({
                "name": name,
                "id": f"{lw.repo}::{name}",
                "origin_repo": lw.repo,
                "read_only": True,
                "spec": spec,
                "member_studies": members,
            })
    return out


def federated_composites(ws_root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for lw in linked_workspaces(ws_root):
        pkg = None
        try:
            data = yaml.safe_load((lw.root / "workspace.yaml").read_text(encoding="utf-8"))
            pkg = (data or {}).get("package_path")
        except Exception:
            pkg = None
        if not pkg:
            continue
        try:
            recs = discover_workspace_composites(lw.root, pkg)
        except Exception:
            continue
        for spec_id, rec in recs.items():
            rec = dict(rec)
            rec["origin_repo"] = lw.repo
            rec["read_only"] = True
            out.setdefault(spec_id, rec)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_federation.py -k federated -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/federation.py tests/test_federation.py
git commit -m "feat(federation): enumerate linked studies, investigation-sets, composites"
```

---

### Task 3: Merge federated studies into `build_investigations` + provenance + membership

**Files:**
- Modify: `vivarium_workbench/lib/investigations_index.py:259-387` (`build_investigations` — append federated rows + membership)
- Modify: `vivarium_workbench/lib/models.py` (`InvestigationRow` — add typed optional fields)
- Test: `tests/test_federation_endpoints.py`

**Interfaces:**
- Consumes: `federation.federated_studies`, `federation.federated_investigation_sets` (Task 2).
- Produces: `build_investigations(ws_root)` rows gain `origin_repo` (str|null), `read_only` (bool), `investigations` (str[] — investigation-set names this study belongs to, local + federated).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_federation_endpoints.py
from pathlib import Path
from vivarium_workbench.lib.investigations_index import build_investigations

FIX = Path(__file__).parent / "_fixtures" / "ws_federation_demo"

def test_build_investigations_includes_federated_study_with_provenance():
    rows = build_investigations(FIX)["investigations"]
    donor = next(r for r in rows if r["name"] == "donor_study")
    assert donor["origin_repo"] == "donor-repo"
    assert donor["read_only"] is True
    # membership: donor_inv lists donor_study
    assert "donor_inv" in donor["investigations"]

def test_build_investigations_own_rows_have_null_origin():
    rows = build_investigations(FIX)["investigations"]
    # host_ws has no own studies; assert federated rows are the only ones and
    # any own row (if present) carries origin_repo None.
    for r in rows:
        assert "origin_repo" in r
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_federation_endpoints.py -v`
Expected: FAIL — `KeyError: 'origin_repo'`

- [ ] **Step 3: Implement the merge**

In `build_investigations`, before `return {"investigations": out}`:
1. Set `row["origin_repo"] = None` and `row["read_only"] = False` on every own row built in the loop.
2. Build a membership map over **local + federated** investigation-sets:

```python
from vivarium_workbench.lib import federation as _fed

# --- membership: study name -> set of investigation-set names that list it ---
membership: dict[str, set[str]] = {}
# local isets
from vivarium_workbench.lib.investigation_status import build_iset_summary
try:
    for iset in build_iset_summary(ws_root) or []:
        for sname in (iset.get("studies") or []):
            membership.setdefault(str(sname), set()).add(iset.get("name") or "")
except Exception:
    pass
# federated isets (member ids are "<repo>::<study>"; strip for display membership)
for iset in _fed.federated_investigation_sets(ws_root):
    for mid in iset.get("member_studies", []):
        sname = mid.split("::", 1)[-1]
        membership.setdefault(sname, set()).add(iset["name"])

for row in out:
    row["investigations"] = sorted(x for x in membership.get(row["name"], ()) if x)

# --- append federated study rows ---
for fs in _fed.federated_studies(ws_root):
    spec = fs["spec"]
    frow = {
        "name": fs["name"],
        "composite": "",
        "composites": [],
        "description": spec.get("description", ""),
        "topic": spec.get("topic", ""),
        "tags": spec.get("tags") or [],
        "status": spec.get("status", "planned"),
        "phase": spec.get("phase"),
        "n_simulations": 0,
        "n_runs": 0,
        "n_baseline": len(spec.get("baseline") or []),
        "origin_repo": fs["origin_repo"],
        "read_only": True,
        "investigations": sorted(x for x in membership.get(fs["name"], ()) if x),
    }
    out.append(frow)
```

> Note: `build_iset_summary`'s exact per-iset study-list key is `studies`; if a future refactor renames it, update the membership loop. Keep the `try/except` so a builder error never breaks the studies list.

3. In `lib/models.py`, add to `InvestigationRow` (keeps `extra="allow"`, these just make the fields typed):

```python
    origin_repo: Optional[str] = None
    read_only: bool = False
    investigations: list[str] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_federation_endpoints.py -v`
Expected: PASS

- [ ] **Step 5: Regression — existing investigations tests still pass**

Run: `pytest tests/ -k "investigation and not federation" -q`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add vivarium_workbench/lib/investigations_index.py vivarium_workbench/lib/models.py tests/test_federation_endpoints.py
git commit -m "feat(federation): federated studies + provenance + membership in build_investigations"
```

---

### Task 4: Merge federated investigation-sets into `build_iset_summary`

**Files:**
- Modify: `vivarium_workbench/lib/investigation_status.py:222+` (`build_iset_summary` — append federated isets)
- Test: `tests/test_federation_endpoints.py`

**Interfaces:**
- Consumes: `federation.federated_investigation_sets` (Task 2).
- Produces: `build_iset_summary(...)` returns federated iset summaries tagged `origin_repo` + `read_only`, with `studies` = display names of member studies.

- [ ] **Step 1: Write the failing test**

```python
from vivarium_workbench.lib.investigation_status import build_iset_summary

def test_iset_summary_includes_federated_investigation():
    isets = build_iset_summary(FIX)
    di = next(i for i in isets if i["name"] == "donor_inv")
    assert di["origin_repo"] == "donor-repo"
    assert di["read_only"] is True
    assert "donor_study" in di["studies"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_federation_endpoints.py::test_iset_summary_includes_federated_investigation -v`
Expected: FAIL — no federated iset / `KeyError: 'origin_repo'`

- [ ] **Step 3: Implement**

At the end of `build_iset_summary`, before returning `summaries`:
1. Set `origin_repo=None`, `read_only=False` on every own summary.
2. Append federated summaries:

```python
from vivarium_workbench.lib import federation as _fed
for fi in _fed.federated_investigation_sets(ws_root):
    summaries.append({
        "name": fi["name"],
        "description": (fi["spec"].get("description") or ""),
        "studies": [m.split("::", 1)[-1] for m in fi.get("member_studies", [])],
        "n_studies": len(fi.get("member_studies", [])),
        "origin_repo": fi["origin_repo"],
        "read_only": True,
    })
```

> Match the surrounding summary dict's existing key names (inspect one own summary first; add any required keys such as `status`/`phase` with safe defaults so the frontend renderer doesn't choke).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_federation_endpoints.py -k iset -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vivarium_workbench/lib/investigation_status.py tests/test_federation_endpoints.py
git commit -m "feat(federation): federated investigation-sets in build_iset_summary"
```

---

### Task 5: Composites — tag `origin_repo` + federate external composites

**Files:**
- Modify: `vivarium_workbench/lib/composite_lookup.py:148-` (`discover_all_composites` — merge federated composites + tag origin_repo)
- Test: `tests/test_federation_endpoints.py`

**Interfaces:**
- Consumes: `federation.federated_composites` (Task 2).
- Produces: every composite record gains `origin_repo` (str|null; null for the host workspace's own composites).

- [ ] **Step 1: Write the failing test**

```python
from vivarium_workbench.lib.composite_lookup import discover_all_composites

def test_discover_all_composites_tags_federated_origin():
    comps = discover_all_composites(FIX, "host")  # host_ws has no own package
    rec = next(r for r in comps.values() if r.get("name") == "donor_comp")
    assert rec["origin_repo"] == "donor-repo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_federation_endpoints.py::test_discover_all_composites_tags_federated_origin -v`
Expected: FAIL — donor_comp not found / no `origin_repo`

- [ ] **Step 3: Implement**

In `discover_all_composites`, after the workspace + installed-package scans and before the generator merge:
```python
from vivarium_workbench.lib import federation as _fed
# Federated composites from linked workspaces under external/ (read-only).
for spec_id, rec in _fed.federated_composites(ws_root).items():
    out.setdefault(spec_id, rec)
# Tag origin: own/installed composites get origin_repo None unless already set.
for rec in out.values():
    rec.setdefault("origin_repo", None)
    rec.setdefault("read_only", False)
```
Place the `setdefault("origin_repo", None)` loop so it runs for ALL records (own + installed + federated); federated recs already carry a truthy `origin_repo`, so `setdefault` leaves them untouched.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_federation_endpoints.py -k composites -v`
Expected: PASS

- [ ] **Step 5: Regression — composite tests still pass**

Run: `pytest tests/ -k composite -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add vivarium_workbench/lib/composite_lookup.py tests/test_federation_endpoints.py
git commit -m "feat(federation): tag composites with origin_repo + federate external composites"
```

---

### Task 6: Frontend — origin-repo badges + read-only treatment

**Files:**
- Modify: `vivarium_workbench/static/walkthrough.js` (`_renderComposites` ~2225, `_renderInvestigationSets` ~5191, study-card rendering within the browse/iset renderers)
- Modify: `vivarium_workbench/static/style.css` (badge + `.federated-readonly` styles)
- Test: manual (frontend has no unit harness) — verification steps below

**Interfaces:**
- Consumes: `origin_repo`, `read_only`, `investigations[]` fields on composites / studies / investigation-sets from Tasks 3-5.
- Produces: shared `window._originBadge(repo)` helper.

- [ ] **Step 1: Add the shared badge helper**

Near the other small render helpers in `walkthrough.js`:
```js
// Origin-repo provenance badge. Empty string for own (null) content.
function _originBadge(repo) {
  if (!repo) return '';
  return '<span class="origin-badge" title="From installed module ' +
    _esc(repo) + '">📦 ' + _esc(repo) + '</span>';
}
window._originBadge = _originBadge;
```

- [ ] **Step 2: Composite cards — badge + read-only**

In `_renderComposites`, in the per-composite card HTML, add `_originBadge(c.origin_repo)` into the card header, and when `c.read_only` add a `federated-readonly` class to the card + skip any promote/run/edit button.

- [ ] **Step 3: Study + investigation-set cards — badge + membership + read-only**

In `_renderInvestigationSets` (and the study-card sub-render it calls):
- Investigation-set card header: append `_originBadge(iset.origin_repo)`.
- Study card header: append `_originBadge(study.origin_repo)`.
- Study card body: when `study.investigations?.length`, add a line: `part of: <names joined by ", ">`.
- When `origin_repo` / `read_only`, add class `federated-readonly` and omit Run/Delete/Edit affordances.

- [ ] **Step 4: CSS**

Append to `style.css`:
```css
.origin-badge{display:inline-block;font-size:0.72em;font-weight:600;color:#5b21b6;
  background:#ede9fe;border:1px solid #ddd6fe;border-radius:10px;padding:1px 7px;
  margin-left:6px;vertical-align:middle;white-space:nowrap}
.federated-readonly{opacity:0.92}
.federated-readonly .action-btn,.federated-readonly .btn-mini{display:none}
```

- [ ] **Step 5: Verify in a live workspace**

Run (in a workspace that has a linked module under `external/`):
```bash
.venv/bin/vivarium-workbench serve --workspace <ws-with-external> --port 8123
```
Confirm in the browser:
- Composites tab: a federated composite shows `📦 <repo>` and no promote/run button.
- Investigations browse: a federated investigation-set shows `📦 <repo>`; its studies show the badge + `part of:` line and no Run/Delete.

- [ ] **Step 6: Commit**

```bash
git add vivarium_workbench/static/walkthrough.js vivarium_workbench/static/style.css
git commit -m "feat(federation): origin-repo badges + read-only treatment on cards"
```

---

### Task 7: SP-A finalize — marketplace installs force full-repo checkout

**Files:**
- Modify: `vivarium_workbench/lib/catalog_install_views.py:62-` (`catalog_install` — honor `full_repo`)
- Modify: `vivarium_workbench/static/walkthrough.js` (`_installFromCatalog` / `_proceedWithCatalogInstall` — pass `full_repo:true` when the install originates from the Marketplace tab)
- Test: `tests/test_catalog_install_views_lib.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `catalog_install(ws_root, body)` honors `body["full_repo"] is True` by taking the git-submodule/full-repo path even when the catalog entry has a `pypi_name` (so `studies/`+`investigations/` land at `external/<name>/`). Modules with no git `source` fall back to the PyPI path (composites-only federation).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog_install_views_lib.py  (add a test)
def test_full_repo_forces_git_path_over_pypi(monkeypatch, tmp_path):
    # A catalog entry WITH pypi_name but full_repo=True must choose install_mode "git".
    # Arrange a fake catalog entry + monkeypatch subprocess.run to record argv,
    # assert the git submodule path (not `uv pip install <pypi_name>`) was taken.
    ...
```
(Mirror the existing monkeypatch style in this test file — fake `subprocess.run` returning `CompletedProcess`, assert on recorded commands. Reuse the file's existing catalog-entry fixture/helper.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_catalog_install_views_lib.py -k full_repo -v`
Expected: FAIL — PyPI path taken

- [ ] **Step 3: Implement**

In `catalog_install`, where install mode is chosen (`pypi_name = catalog_entry.get("pypi_name")` → `if pypi_name:` PyPI branch), gate it:
```python
full_repo = bool(body.get("full_repo"))
use_pypi = bool(pypi_name) and not (full_repo and catalog_entry.get("source"))
if use_pypi:
    ...  # existing PyPI branch
else:
    ...  # existing git-submodule full-repo branch
```
Keep `install_mode = "pypi" if use_pypi else "git"`.

- [ ] **Step 4: Frontend — mark marketplace-originated installs**

In `walkthrough.js`, have the Marketplace Install button call a marketplace-specific installer that sets a flag, OR pass `full_repo` through `_proceedWithCatalogInstall`. Minimal approach: `_moduleActionFor` renders the marketplace Install button as `_installFromCatalog('<name>', {full_repo:true})`; thread the opts to the POST body in `_proceedWithCatalogInstall` (`if (opts && opts.full_repo) body.full_repo = true;`). The Modules-tab install button keeps its current no-flag behavior.

> `_moduleActionFor` is shared between the Modules and Marketplace grids. Distinguish by a second arg to `_renderModuleGrid` (e.g. `opts.marketplace`) so only the Marketplace grid emits the `full_repo:true` button.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_catalog_install_views_lib.py -k full_repo -v`
Expected: PASS

- [ ] **Step 6: Regression — install tests still pass**

Run: `pytest tests/ -k "catalog_install" -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add vivarium_workbench/lib/catalog_install_views.py vivarium_workbench/static/walkthrough.js tests/test_catalog_install_views_lib.py
git commit -m "feat(marketplace): force full-repo checkout for marketplace installs"
```

---

### Task 8: End-to-end federation test through the live server

**Files:**
- Test: `tests/test_federation_endpoints.py` (add a `dashboard_client`-based test)

**Interfaces:**
- Consumes: `dashboard_client` fixture (`tests/conftest.py`) pointed at `ws_federation_demo`.

- [ ] **Step 1: Write the test**

```python
def test_endpoints_expose_federated_content(dashboard_client_factory):
    # Use whatever fixture spins the live app against a chosen workspace.
    client = dashboard_client_factory(FIX)   # adapt to conftest's actual API
    inv = client.get("/api/investigations").json()["investigations"]
    assert any(r.get("origin_repo") == "donor-repo" for r in inv)
    comps = client.get("/api/composites").json()["composites"]
    assert any(c.get("origin_repo") == "donor-repo" for c in comps)
```
> Inspect `tests/conftest.py` for the exact fixture name/signature (`dashboard_client` may be pre-bound to a fixture workspace; if so, add a parametrized/factory variant or a dedicated fixture for `ws_federation_demo`).

- [ ] **Step 2: Run**

Run: `pytest tests/test_federation_endpoints.py -k endpoints_expose -v`
Expected: PASS

- [ ] **Step 3: Full suite**

Run: `pytest -q`
Expected: PASS (no regressions)

- [ ] **Step 4: Commit**

```bash
git add tests/test_federation_endpoints.py
git commit -m "test(federation): end-to-end federated content through the live server"
```

---

## Self-Review

**Spec coverage:**
- Marketplace tab (SP-A) — done pre-plan; full-repo install finalize = Task 7. ✓
- Read-only federation of composites/studies/investigations — Tasks 2, 3, 4, 5. ✓
- Automatic on install — federation keys off `external/`, no opt-in step. ✓
- Provenance badges on study/investigation/composite cards — Task 6. ✓
- Study cards show investigation membership — Task 3 (`investigations[]`) + Task 6 render. ✓
- Namespaced ids / best-effort / additive fields (global constraints) — Tasks 1-5. ✓
- SP-C (referencing) — explicitly out of scope for this plan (future spec). ✓

**Placeholder scan:** Task 7 Step 1 and Task 8 Step 1 leave test bodies partially sketched (`...`) because they must mirror existing monkeypatch/fixture conventions in files not fully quoted here; each carries an explicit instruction to match the existing file's pattern. All implementation steps contain concrete code.

**Type consistency:** `origin_repo` (str|None), `read_only` (bool), `investigations` (list[str]), `member_studies` (list[str], namespaced), `id` (`"<repo>::<name>"`) are used consistently across Tasks 1-6. `federated_composites` returns `dict[str, dict]`; `federated_studies`/`federated_investigation_sets` return `list[dict]` — matched at every call site.

**Open item for the implementer:** Tasks 3 & 4 assume `build_iset_summary`'s member-study list key is `studies`; verify against the real function and adjust the membership loop if it differs.
