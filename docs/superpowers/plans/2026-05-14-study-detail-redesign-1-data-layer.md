# Study Detail Redesign — Plan 1: Data Layer & Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the study spec so a study's **Baseline** is a *list* of composites and each **Variant** references one of them via `base_composite` + carries flat `parameter_overrides`, and add an additive `interventions[]` field — including migrating the real v2-shaped specs in existing workspaces.

**Architecture:** All changes are in the spec-loading/validation layer — `vivarium_dashboard/lib/spec_migration.py` (the `migrate_v2_to_v3` in-memory migration) and `vivarium_dashboard/lib/investigations.py` (`_validate_study_v3`). No endpoint, template, or JS changes — those are Plans 2 and 3. After this plan, `load_spec` returns the new v3 shape for every study (legacy single-composite, legacy `composites:` list, and the real `variants:`+`baseline:<string>` shape), and `_validate_study_v3` accepts it.

**Tech Stack:** Python 3.12, pytest, PyYAML.

**Plan sequence:** This is **Plan 1 of 3** for the spec `docs/superpowers/specs/2026-05-14-study-detail-redesign-design.md`. Plan 2 = the server endpoints (baseline add/remove, variant set-params, intervention CRUD, `study-variant-add`/`study-run-baseline` extensions). Plan 3 = the UI (`study-detail.html` 5-tab restructure, `study-detail.js`, CSS).

---

## Target spec shape (the v3 shape this plan produces)

```yaml
schema_version: 3
name: t1
baseline:                       # LIST of composites (was a single {composite,params} dict)
  - name: chromosome-partition  # stable key — variants reference this
    composite: pbg_chromosome_rep1.composites.chromosome-partition
    params: {}
variants:                       # param-overlays on a baseline composite
  - name: high-count
    base_composite: chromosome-partition   # references baseline[].name
    parameter_overrides:
      parameters.initial_chromosome_count.default: 2.0
interventions: []               # NEW additive field — [{name, description}]
objective: ""
runs: []
visualizations: []
# ...other existing fields (status, conclusion, parent_studies, ...) untouched
```

**Refinement over the spec:** the spec wrote baseline entries as `{composite, params}`. This plan adds a `name` to each baseline entry, because variants must reference a specific baseline composite by a stable key (`base_composite`) — exactly how today's `extends:`/`baseline:` reference variants by name. If you'd rather variants reference by `composite` id instead of `name`, flag it before execution.

---

## File Structure

- `vivarium_dashboard/lib/spec_migration.py` — MODIFY. `migrate_v2_to_v3` learns: (a) emit `baseline` as a list, (b) recognize and reshape the `variants:`+`baseline:<string>` shape, (c) flatten variant `intervention.parameter_overrides` → `parameter_overrides` and `extends` → `base_composite`, (d) pass `interventions` through.
- `vivarium_dashboard/lib/investigations.py` — MODIFY. `_validate_study_v3` accepts list-shaped `baseline`, validates variant `base_composite`/`parameter_overrides`, and validates the optional `interventions[]`.
- `tests/test_spec_migration.py` — MODIFY (existing file). Add migration tests.
- `tests/test_v3_study_validation.py` — MODIFY (existing file). Add validation tests.

---

## Task 1: `migrate_v2_to_v3` emits `baseline` as a list

The `composites:`-list and lone-`composite:` paths in `migrate_v2_to_v3` currently produce `baseline` as a single `{composite, params}` dict (first composite only, `UserWarning` on extras). Change them to emit a **list** with one entry per composite, each entry `{name, composite, params}`.

**Files:**
- Modify: `vivarium_dashboard/lib/spec_migration.py` (the `migrate_v2_to_v3` `composites`/`composite` branches, ~lines 130–153)
- Test: `tests/test_spec_migration.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spec_migration.py`:

```python
def test_migrate_v2_to_v3_baseline_is_a_list_of_all_composites():
    """v2→v3: a multi-entry composites: list becomes a baseline LIST with one
    {name, composite, params} entry each — no composites are dropped."""
    spec = {
        "schema_version": 2,
        "name": "s",
        "composites": [
            {"name": "a", "source": "pkg.a", "parameters": {"rate": 1.0}},
            {"name": "b", "source": "pkg.b"},
        ],
    }
    out = migrate_v2_to_v3(spec)
    assert out["schema_version"] == 3
    assert out["baseline"] == [
        {"name": "a", "composite": "pkg.a", "params": {"rate": 1.0}},
        {"name": "b", "composite": "pkg.b", "params": {}},
    ]
    assert "composites" not in out


def test_migrate_v2_to_v3_lone_composite_key_becomes_one_element_list():
    """A bare top-level composite: string becomes a one-element baseline list."""
    spec = {
        "schema_version": 2,
        "name": "s",
        "composite": "pkg.chemotaxis",
        "parameters": {"k": 0.5},
    }
    out = migrate_v2_to_v3(spec)
    assert out["baseline"] == [
        {"name": "pkg.chemotaxis", "composite": "pkg.chemotaxis", "params": {"k": 0.5}}
    ]
    assert "composite" not in out and "parameters" not in out
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `cd ~/code/vivarium-dashboard && source .venv/bin/activate && python -m pytest tests/test_spec_migration.py::test_migrate_v2_to_v3_baseline_is_a_list_of_all_composites tests/test_spec_migration.py::test_migrate_v2_to_v3_lone_composite_key_becomes_one_element_list -v`
Expected: FAIL — `out["baseline"]` is a dict, not a list.

- [ ] **Step 3: Implement — make `baseline` a list**

In `vivarium_dashboard/lib/spec_migration.py`, replace the `composites`/`composite` branches of `migrate_v2_to_v3` (the block from `composites = spec.get("composites") or []` through `out.pop("parameters", None)`) with:

```python
    composites = spec.get("composites") or []
    if composites:
        out["baseline"] = [
            {
                "name": c.get("name") or c.get("source", ""),
                "composite": c.get("source") or c.get("name", ""),
                "params": c.get("parameters", {}) or {},
            }
            for c in composites
        ]
        out.pop("composites", None)
    elif "composite" in spec:
        # Lone top-level `composite:` key (explicit v2 with composite key).
        out["baseline"] = [{
            "name": spec["composite"],
            "composite": spec["composite"],
            "params": spec.get("parameters", {}) or {},
        }]
        out.pop("composite", None)
        out.pop("parameters", None)
```

Also delete the now-obsolete `import warnings` line and the `if len(composites) > 1: warnings.warn(...)` block — multi-composite is no longer a lossy case.

- [ ] **Step 4: Run the tests, verify they pass**

Run: `python -m pytest tests/test_spec_migration.py -v`
Expected: PASS — including the pre-existing `test_spec_migration.py` tests (some assert the old dict shape — see Step 5).

- [ ] **Step 5: Fix any pre-existing tests that asserted the old dict-shaped baseline**

Run the full file in Step 4. For each pre-existing test that fails because it expected `baseline` to be a `{composite, params}` dict, update its assertion to the list shape `[{name, composite, params}]`. Do **not** change migration behavior to satisfy them — the list shape is the new contract.

- [ ] **Step 6: Commit**

```bash
git add vivarium_dashboard/lib/spec_migration.py tests/test_spec_migration.py
git commit -m "feat(migration): v2→v3 emits baseline as a list of composites"
```

---

## Task 2: `migrate_v2_to_v3` recognizes and reshapes the `variants:`+`baseline:<string>` shape

The real specs in existing workspaces look like the v2ecoli `t1/spec.yaml`: a top-level `variants:` list where each entry is a *composite* (has `source`/`document`), a `baseline:` *string* naming one of them, and **no** `schema_version` and **no** `composites:` key. `migrate_v2_to_v3` currently passes these through unchanged (the `version != 2 and not has_composites_key` early-return). Teach it to recognize and reshape them: composite-entries (have `source`, no `extends`) → `baseline[]`; overlay-entries (have `extends` or `intervention`) → `variants[]`.

**Files:**
- Modify: `vivarium_dashboard/lib/spec_migration.py` (`migrate_v2_to_v3` — the early-return guard + a new reshape branch)
- Test: `tests/test_spec_migration.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spec_migration.py`:

```python
def test_migrate_v2_to_v3_reshapes_variants_as_composites_shape():
    """The real workspace shape — `variants:` list (entries ARE composites) +
    `baseline:` string, no schema_version — is reshaped: composite-entries go
    to baseline[], extends/intervention entries become real variants."""
    spec = {
        "name": "t1",
        "baseline": "chromosome-partition",
        "variants": [
            {"name": "chromosome-partition",
             "source": "pkg.chromosome-partition",
             "document": "./composites/chromosome-partition.yaml"},
            {"name": "high-count",
             "extends": "chromosome-partition",
             "document": "./composites/high-count.yaml",
             "intervention": {"description": "",
                              "parameter_overrides": {"p.count": 2.0}}},
        ],
    }
    out = migrate_v2_to_v3(spec)
    assert out["schema_version"] == 3
    assert out["baseline"] == [
        {"name": "chromosome-partition",
         "composite": "pkg.chromosome-partition", "params": {}},
    ]
    assert out["variants"] == [
        {"name": "high-count",
         "base_composite": "chromosome-partition",
         "parameter_overrides": {"p.count": 2.0}},
    ]
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `python -m pytest tests/test_spec_migration.py::test_migrate_v2_to_v3_reshapes_variants_as_composites_shape -v`
Expected: FAIL — `out` is returned unchanged (no `schema_version`, `baseline` still a string).

- [ ] **Step 3: Implement — recognize + reshape the shape**

In `migrate_v2_to_v3`, the early-return guard currently is:

```python
    version = spec.get("schema_version")
    has_composites_key = "composites" in spec
    if version != 2 and not has_composites_key:
        return spec
```

Replace it with logic that also recognizes the `variants:`-as-composites shape (a `variants:` list whose entries carry `source`, plus a string `baseline:`), and add a reshape branch. Insert this *before* the existing `composites = spec.get("composites") or []` block, and adjust the guard:

```python
    version = spec.get("schema_version")
    has_composites_key = "composites" in spec
    # The "variants-as-composites" v2 shape: a `variants:` list whose entries
    # are composites (carry `source`), with a string `baseline:` naming one.
    variants_in = spec.get("variants")
    is_variants_as_composites = (
        isinstance(variants_in, list)
        and isinstance(spec.get("baseline"), str)
        and any(isinstance(v, dict) and v.get("source") for v in variants_in)
    )
    if version != 2 and not has_composites_key and not is_variants_as_composites:
        return spec

    out = dict(spec)
    out["schema_version"] = 3
    out.setdefault("objective", "")
    out.setdefault("parent_studies", [])

    if is_variants_as_composites:
        baseline_list = []
        new_variants = []
        for v in variants_in:
            if not isinstance(v, dict):
                continue
            if v.get("source") and not v.get("extends"):
                baseline_list.append({
                    "name": v.get("name", ""),
                    "composite": v.get("source", ""),
                    "params": v.get("parameter_overrides", {}) or {},
                })
            else:
                iv = v.get("intervention") or {}
                new_variants.append({
                    "name": v.get("name", ""),
                    "base_composite": v.get("extends", ""),
                    "parameter_overrides": (
                        v.get("parameter_overrides")
                        or iv.get("parameter_overrides")
                        or {}
                    ),
                })
        out["baseline"] = baseline_list
        out["variants"] = new_variants
        return out
```

Then **delete the now-redundant second `out = dict(spec)` / `out["schema_version"] = 3` / `out.setdefault("objective", "")` / `out.setdefault("parent_studies", [])` block** that sits just above `composites = spec.get("composites") or []`. There must be **exactly one** `out` setup block, before all three branches — the `composites:`/`composite:` code below it keeps using that same `out`.

- [ ] **Step 4: Run the test, verify it passes**

Run: `python -m pytest tests/test_spec_migration.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add vivarium_dashboard/lib/spec_migration.py tests/test_spec_migration.py
git commit -m "feat(migration): reshape the variants-as-composites v2 shape to v3"
```

---

## Task 3: `migrate_v2_to_v3` carries `interventions` through unchanged

A v2 spec will not have `interventions`; a partially-migrated or hand-authored one might. The migration must (a) default `interventions` to `[]` when absent (done in Task 2's shared block for the variants-as-composites path; ensure it also happens for the `composites:`/`composite:` paths) and (b) preserve a present `interventions` list verbatim.

**Files:**
- Modify: `vivarium_dashboard/lib/spec_migration.py` (`migrate_v2_to_v3`)
- Test: `tests/test_spec_migration.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spec_migration.py`:

```python
def test_migrate_v2_to_v3_defaults_interventions_to_empty_list():
    out = migrate_v2_to_v3({"schema_version": 2, "name": "s",
                            "composites": [{"name": "a", "source": "pkg.a"}]})
    assert out["interventions"] == []


def test_migrate_v2_to_v3_preserves_existing_interventions():
    out = migrate_v2_to_v3({
        "schema_version": 2, "name": "s",
        "composites": [{"name": "a", "source": "pkg.a"}],
        "interventions": [{"name": "hi-glu", "description": "glucose 25mM"}],
    })
    assert out["interventions"] == [{"name": "hi-glu", "description": "glucose 25mM"}]
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `python -m pytest tests/test_spec_migration.py::test_migrate_v2_to_v3_defaults_interventions_to_empty_list tests/test_spec_migration.py::test_migrate_v2_to_v3_preserves_existing_interventions -v`
Expected: FAIL — `out` has no `interventions` key on the `composites:` path.

- [ ] **Step 3: Implement**

Add `out.setdefault("interventions", [])` to the **single** `out` setup block (Task 2 hoisted it to one place before all three branches):

```python
    out = dict(spec)
    out["schema_version"] = 3
    out.setdefault("objective", "")
    out.setdefault("parent_studies", [])
    out.setdefault("interventions", [])
```

This one block now serves all three migration paths (variants-as-composites, `composites:`, lone `composite:`). `dict(spec)` already copies a present `interventions` list verbatim, so `setdefault` is a no-op when it exists — preservation is automatic.

- [ ] **Step 4: Run the tests, verify they pass**

Run: `python -m pytest tests/test_spec_migration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_dashboard/lib/spec_migration.py tests/test_spec_migration.py
git commit -m "feat(migration): default + preserve interventions[] through v2→v3"
```

---

## Task 4: `_validate_study_v3` accepts list-shaped `baseline`

`_validate_study_v3` currently requires `baseline` to be a *mapping* with a `composite` key. It must now require `baseline` to be a non-empty **list** of mappings, each with `name` + `composite` strings (`params` optional mapping).

**Files:**
- Modify: `vivarium_dashboard/lib/investigations.py` (`_validate_study_v3`, the `baseline` block ~lines 115–119)
- Test: `tests/test_v3_study_validation.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_v3_study_validation.py` (import `_validate_study_v3` and `InvestigationSpecError` from `vivarium_dashboard.lib.investigations` the same way the existing tests in the file do):

```python
def test_v3_validation_accepts_list_baseline():
    """A v3 study with baseline as a list of {name, composite, params} validates."""
    _validate_study_v3({
        "schema_version": 3, "name": "s",
        "baseline": [{"name": "a", "composite": "pkg.a", "params": {}}],
        "variants": [], "runs": [], "visualizations": [],
    })  # must not raise


def test_v3_validation_rejects_empty_baseline_list():
    with pytest.raises(InvestigationSpecError):
        _validate_study_v3({
            "schema_version": 3, "name": "s",
            "baseline": [], "variants": [], "runs": [], "visualizations": [],
        })


def test_v3_validation_rejects_baseline_entry_missing_composite():
    with pytest.raises(InvestigationSpecError):
        _validate_study_v3({
            "schema_version": 3, "name": "s",
            "baseline": [{"name": "a", "params": {}}],
            "variants": [], "runs": [], "visualizations": [],
        })
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `python -m pytest tests/test_v3_study_validation.py::test_v3_validation_accepts_list_baseline tests/test_v3_study_validation.py::test_v3_validation_rejects_empty_baseline_list tests/test_v3_study_validation.py::test_v3_validation_rejects_baseline_entry_missing_composite -v`
Expected: FAIL — `test_v3_validation_accepts_list_baseline` raises ("'baseline' must be a mapping").

- [ ] **Step 3: Implement**

In `vivarium_dashboard/lib/investigations.py`, replace the `baseline` block of `_validate_study_v3`:

```python
    baseline = spec.get("baseline")
    if not isinstance(baseline, dict):
        raise InvestigationSpecError("v3 study: 'baseline' must be a mapping")
    if not baseline.get("composite"):
        raise InvestigationSpecError("v3 study: 'baseline.composite' is required")
```

with:

```python
    baseline = spec.get("baseline")
    if not isinstance(baseline, list) or not baseline:
        raise InvestigationSpecError(
            "v3 study: 'baseline' must be a non-empty list of composites"
        )
    for i, c in enumerate(baseline):
        if not isinstance(c, dict):
            raise InvestigationSpecError(f"v3 study: baseline[{i}] must be a mapping")
        if not c.get("name"):
            raise InvestigationSpecError(f"v3 study: baseline[{i}].name is required")
        if not c.get("composite"):
            raise InvestigationSpecError(f"v3 study: baseline[{i}].composite is required")
```

Also update the docstring's `v3 shape` line for `baseline` to read: "``baseline``: a non-empty list of ``{name, composite, params}`` mappings."

- [ ] **Step 4: Run the tests, verify they pass**

Run: `python -m pytest tests/test_v3_study_validation.py -v`
Expected: PASS. Fix any pre-existing test in the file that constructed `baseline` as a dict — update it to the list shape (the list shape is the new contract).

- [ ] **Step 5: Commit**

```bash
git add vivarium_dashboard/lib/investigations.py tests/test_v3_study_validation.py
git commit -m "feat(validation): v3 study baseline is a non-empty list of composites"
```

---

## Task 5: `_validate_study_v3` validates variant `base_composite` + `parameter_overrides` and the `interventions[]` field

Variants in the new shape carry `base_composite` (must reference a declared `baseline[].name`) and an optional `parameter_overrides` mapping. The optional top-level `interventions` must be a list of `{name, description}` mappings.

**Files:**
- Modify: `vivarium_dashboard/lib/investigations.py` (`_validate_study_v3`, the `variants` block + a new `interventions` block)
- Test: `tests/test_v3_study_validation.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_v3_study_validation.py`:

```python
def test_v3_validation_accepts_variant_with_base_composite():
    _validate_study_v3({
        "schema_version": 3, "name": "s",
        "baseline": [{"name": "a", "composite": "pkg.a", "params": {}}],
        "variants": [{"name": "v1", "base_composite": "a",
                      "parameter_overrides": {"rate": 2.0}}],
        "runs": [], "visualizations": [],
    })  # must not raise


def test_v3_validation_rejects_variant_base_composite_not_in_baseline():
    with pytest.raises(InvestigationSpecError):
        _validate_study_v3({
            "schema_version": 3, "name": "s",
            "baseline": [{"name": "a", "composite": "pkg.a", "params": {}}],
            "variants": [{"name": "v1", "base_composite": "nope"}],
            "runs": [], "visualizations": [],
        })


def test_v3_validation_accepts_interventions_list():
    _validate_study_v3({
        "schema_version": 3, "name": "s",
        "baseline": [{"name": "a", "composite": "pkg.a", "params": {}}],
        "variants": [], "runs": [], "visualizations": [],
        "interventions": [{"name": "hi-glu", "description": "glucose 25mM"}],
    })  # must not raise


def test_v3_validation_rejects_intervention_missing_name():
    with pytest.raises(InvestigationSpecError):
        _validate_study_v3({
            "schema_version": 3, "name": "s",
            "baseline": [{"name": "a", "composite": "pkg.a", "params": {}}],
            "variants": [], "runs": [], "visualizations": [],
            "interventions": [{"description": "no name"}],
        })
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `python -m pytest tests/test_v3_study_validation.py -k "base_composite or interventions or intervention_missing" -v`
Expected: FAIL — `test_v3_validation_rejects_variant_base_composite_not_in_baseline` and `test_v3_validation_rejects_intervention_missing_name` do not raise (no such checks exist yet).

- [ ] **Step 3: Implement**

In `_validate_study_v3`, replace the `variants` block:

```python
    variants = spec.get("variants", [])
    if not isinstance(variants, list):
        raise InvestigationSpecError("v3 study: 'variants' must be a list")
    for i, v in enumerate(variants):
        if not isinstance(v, dict) or not v.get("name"):
            raise InvestigationSpecError(
                f"v3 study: variants[{i}] must be a mapping with a 'name'"
            )
```

with (note: `baseline` is the validated list from Task 4, in scope here):

```python
    baseline_names = {c["name"] for c in baseline}
    variants = spec.get("variants", [])
    if not isinstance(variants, list):
        raise InvestigationSpecError("v3 study: 'variants' must be a list")
    for i, v in enumerate(variants):
        if not isinstance(v, dict) or not v.get("name"):
            raise InvestigationSpecError(
                f"v3 study: variants[{i}] must be a mapping with a 'name'"
            )
        base = v.get("base_composite")
        if base and base not in baseline_names:
            raise InvestigationSpecError(
                f"v3 study: variants[{i}].base_composite {base!r} is not a "
                f"declared baseline composite ({sorted(baseline_names)})"
            )
        po = v.get("parameter_overrides", {})
        if not isinstance(po, dict):
            raise InvestigationSpecError(
                f"v3 study: variants[{i}].parameter_overrides must be a mapping"
            )
```

Then add an `interventions` block immediately after the `visualizations` block:

```python
    interventions = spec.get("interventions", [])
    if not isinstance(interventions, list):
        raise InvestigationSpecError("v3 study: 'interventions' must be a list")
    for i, iv in enumerate(interventions):
        if not isinstance(iv, dict) or not iv.get("name"):
            raise InvestigationSpecError(
                f"v3 study: interventions[{i}] must be a mapping with a 'name'"
            )
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `python -m pytest tests/test_v3_study_validation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vivarium_dashboard/lib/investigations.py tests/test_v3_study_validation.py
git commit -m "feat(validation): v3 variant base_composite + interventions[] checks"
```

---

## Task 6: End-to-end — `load_spec` on a real v2ecoli-shaped spec produces the new v3 shape

Integration check that the migration + validation compose correctly: a `spec.yaml` shaped like the real v2ecoli `t1` study loads through `load_spec` into the new v3 shape and passes validation.

**Files:**
- Test: `tests/test_v3_study_validation.py` (or `tests/test_investigations.py` — use whichever already imports `load_spec`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_v3_study_validation.py` (add `import yaml` and `from pathlib import Path` and `from vivarium_dashboard.lib.investigations import load_spec` if not already imported):

```python
def test_load_spec_migrates_real_v2ecoli_shape_end_to_end(tmp_path):
    """A spec.yaml in the real workspace shape (variants-as-composites +
    baseline string, no schema_version) loads into the v3 list-baseline shape."""
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump({
        "name": "t1",
        "baseline": "chromosome-partition",
        "variants": [
            {"name": "chromosome-partition",
             "source": "pkg.chromosome-partition",
             "document": "./composites/chromosome-partition.yaml"},
            {"name": "high-count",
             "extends": "chromosome-partition",
             "document": "./composites/high-count.yaml",
             "intervention": {"description": "",
                              "parameter_overrides": {"p.count": 2.0}}},
        ],
        "comparisons": [], "conclusions": "", "question": "",
        "hypothesis": "", "status": "draft",
    }))
    spec = load_spec(p)
    assert spec["schema_version"] == 3
    assert spec["baseline"] == [
        {"name": "chromosome-partition",
         "composite": "pkg.chromosome-partition", "params": {}},
    ]
    assert spec["variants"] == [
        {"name": "high-count", "base_composite": "chromosome-partition",
         "parameter_overrides": {"p.count": 2.0}},
    ]
    assert spec["interventions"] == []
```

- [ ] **Step 2: Run the test, verify it fails or passes**

Run: `python -m pytest tests/test_v3_study_validation.py::test_load_spec_migrates_real_v2ecoli_shape_end_to_end -v`
Expected: If Tasks 1–5 are done, this likely **passes immediately** — that is acceptable here because it is an *integration* test composing already-tested units; its job is to lock the end-to-end contract. If it fails, the failure pinpoints a gap between migration and validation — fix in the relevant lib file (not the test), re-run.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS except the 6 known pre-existing failures (`test_investigation_run_e2e.py` ×2, `test_investigations.py::test_run_investigation_iterates_runs_and_passes_state_doc`, `test_study_runs.py` ×2, `test_visualization_endpoints.py::test_post_create_from_composite_creates_v2_spec`). If any *other* test fails, it is fallout from the shape change — fix it (update assertions to the new list-baseline / `base_composite` shape; do not weaken the migration/validation).

- [ ] **Step 4: Commit**

```bash
git add tests/test_v3_study_validation.py
git commit -m "test: end-to-end load_spec migrates real v2ecoli shape to v3"
```

---

## Done criteria

- `migrate_v2_to_v3` produces `baseline` as a list for all three input shapes (legacy `composites:`, lone `composite:`, real `variants:`+`baseline:<string>`), reshapes variants to `{name, base_composite, parameter_overrides}`, and defaults/preserves `interventions[]`.
- `_validate_study_v3` accepts the list-shaped `baseline`, validates `base_composite` references, and validates `interventions[]`.
- `load_spec` on a real v2ecoli-shaped `spec.yaml` returns the new v3 shape end-to-end.
- Full suite green except the 6 known pre-existing failures.

**Not in this plan (Plans 2 & 3):** no endpoints, no `study-detail.html`, no `study-detail.js`, no CSS. `_render_study_detail_html` and the server handlers are not touched here — they receive the new shape once this plan lands and are updated in Plan 2/3.
