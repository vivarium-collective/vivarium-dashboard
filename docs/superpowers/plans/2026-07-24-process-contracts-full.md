# Full v2ecoli Process Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give every real-science v2ecoli process a structured `ProcessContract` — per-port input/output semantics, per-config meaning, symbols with units, assumptions, references — so the loom process card (already shipped in PR #558) renders complete, correct, mathematically-legible self-descriptions for modelers and mathematicians.

**Architecture:** `ProcessContract` is a dataclass in **bigraph-schema**, attached to `Edge` alongside the existing `description`/`config_schema`/`describe()`. It is a STRUCTURED SUPERSET of `description`: `summary` and `math` fall back to parsing the existing `description` string (16/16 v2ecoli processes already populate it with governing math), so the math is single-sourced and not rewritten. Authoring adds only the structured rows a flat string cannot hold. The workbench env-worker attaches the resolved `_contract` to composite-state nodes; loom already reads `node._contract` (`convert.ts`, Task 8) and renders it across the five zoom tiers — **no loom change is needed**.

**Supersedes:** `docs/superpowers/plans/2026-07-23-process-contract-and-config.md` (its Edge-location, method-name, and "contract is net-new" assumptions were stale; verified against source 2026-07-24).

## Global Constraints

- Three repos, committed separately (no shared branch):
  - `/Users/eranagmon/code/bigraph-schema` — the `ProcessContract` dataclass, `Edge.contract()` resolver, `_contract` serialization
  - `/Users/eranagmon/code/vivarium-dashboard` (package `vivarium_workbench`) — attach `_contract` + `config_schema` in the env worker
  - `/Users/eranagmon/code/v2ecoli` — author the contracts
- **Correctness is the deliverable.** Every contract MUST be derived from the process's actual source, never guessed. The math already lives in each class's `description` attribute; the per-port/per-config semantics come from reading the real `update` (plain `EcoliStep`) or `calculate_request` + `evolve_state` (`PartitionedProcess`) method and the wiring. An authored line that the source does not support is a defect, worse than an empty row.
- **Reuse `description`, do not duplicate it.** If a contract omits `summary`/`math`, they derive from the existing `description` via a parser. Only override when the structured form genuinely improves on the flat string. Never author math into the contract that contradicts or silently diverges from `description`.
- **Partitioned processes are ONE science class surfaced as TWO nodes.** `Requester`/`Evolver` (`v2ecoli/steps/partition.py`) are generic wrappers around a shared `PartitionedProcess` instance passed as config `process`. The contract belongs on the underlying `PartitionedProcess` subclass; both the `_requester` and `_evolver` composite nodes must resolve to it, each labeled with which half (request vs execute) it plays.
- **Additive only.** A `contract` class attribute resolves through normal Python MRO and does not depend on `EcoliStep.__init__` (which bypasses `super().__init__()`). Adding it must not change any process's runtime behavior, and every existing composite must still build. `describe()` and `description` stay working unchanged.
- Python ≥ 3.11 (dataclasses stdlib). bigraph-schema and process-bigraph tests: `pytest`. Building a v2ecoli composite needs the ParCa cache at `out/cache` — if absent, tests error at fixture setup, not a code bug.
- Commit after each task. Prefixes: `feat(contract):`, `feat(v2ecoli):`, `test(...)`.

## Coverage

The composite surfaces ~24 process nodes from **16 concrete science modules** in `v2ecoli/processes/` plus `ppgpp_initiation` and the partition wrappers. Author contracts on the 16 modules' concrete classes (and `SteadyStatePolypeptideElongation`, the baseline's elongation subclass). Skip bookkeeping (`unique_update_*`, `allocator_*`, `*_listener`, `global_clock`, `mark_d_period`, `shape_step`, `emitter`) — hidden by default, no science to advertise. Net: ~18 authored classes covering the ~24 visible science nodes.

---

## Phase A — Infrastructure

### Task A1: `ProcessContract` dataclass + `Edge.contract()` resolver + serialization

**Repo:** `/Users/eranagmon/code/bigraph-schema`

**Files:**
- Create: `bigraph_schema/contract.py`
- Modify: `bigraph_schema/edge.py` (add `contract` class attr + `contract()` method, near `description`/`describe()` at lines 34-38/147-157), `bigraph_schema/__init__.py` (export `ProcessContract`)
- Modify: `bigraph_schema/methods/serialize.py` (the `serialize(schema: Link, state)` overload, `encode` dict ~713-728 — add `_contract`)
- Test: `tests/test_process_contract.py`

**Interfaces:**
- Produces: `ProcessContract` dataclass — fields `summary: str = ""`, `description: str = ""`, `inputs: dict[str,str] = {}`, `outputs: dict[str,str] = {}`, `config: dict[str,str] = {}`, `math: list[str] = []`, `symbols: dict[str,str] = {}`, `assumptions: list[str] = []`, `references: list[str] = []`; methods `to_dict() -> dict`, `classmethod from_description(text: str|None) -> ProcessContract|None`, `merged_with_description(desc: str) -> ProcessContract` (fills empty `summary`/`math`/`description` from parsing `desc`); a module fn `resolve_contract(instance) -> ProcessContract|None`
- Edge gains: `contract = None` class attr (the DATA slot subclasses assign); `describe_contract()` instance method returning the resolved `ProcessContract` (a `contract()` method is impossible — it would collide with the data slot). Downstream (A2, Phase B) resolve via `resolve_contract(instance)` / `describe_contract()`, NEVER `.contract()`.

- [ ] **Step 1: Write the failing test** — cover: mutable-default isolation; `to_dict` JSON-safe; `from_description` splits first line→summary, equation lines (markers `= ~ ≈ ← ≥ ≤ ∑ ∏` or a distribution name)→`math`, rest→`description`; `from_description(None/'')` → None; `merged_with_description` fills only EMPTY summary/math/description and leaves authored inputs/outputs/config/symbols intact; `resolve_contract` returns the declared contract merged with `description`, else a description-derived one, else a docstring-derived one, else None; `resolve_contract(None/object())` never raises.

```python
# tests/test_process_contract.py
from bigraph_schema.contract import ProcessContract, resolve_contract

DESC = """Distributes activated RNAPs across TUs by weighted multinomial sampling.

    n_to_activate = round(f_active · n_total_RNAP) - n_active
    p_i = max(0, basal_prob_i + sum_j delta_prob[i,j] · bound_TF_j)
"""

def test_mutable_defaults_isolated():
    a, b = ProcessContract(summary="a"), ProcessContract(summary="b")
    a.inputs["x"] = "y"
    assert b.inputs == {}

def test_from_description_splits_summary_and_math():
    c = ProcessContract.from_description(DESC)
    assert c.summary.startswith("Distributes activated RNAPs")
    assert len(c.math) == 2 and c.math[0].startswith("n_to_activate =")

def test_from_description_none():
    assert ProcessContract.from_description("") is None
    assert ProcessContract.from_description(None) is None

def test_merged_preserves_authored_rows_fills_math():
    authored = ProcessContract(inputs={"RNAs": "reads transcripts"})
    merged = authored.merged_with_description(DESC)
    assert merged.inputs == {"RNAs": "reads transcripts"}   # untouched
    assert merged.math and merged.summary                    # filled from desc

def test_merged_does_not_override_authored_math():
    authored = ProcessContract(summary="mine", math=["x = 1"])
    merged = authored.merged_with_description(DESC)
    assert merged.summary == "mine" and merged.math == ["x = 1"]

class _Declared:
    contract = ProcessContract(inputs={"p": "reads p"})
    description = DESC

class _DescOnly:
    description = DESC

class _Bare:
    """Plain docstring, no math."""

def test_resolve_declared_merges_description():
    c = resolve_contract(_Declared())
    assert c.inputs == {"p": "reads p"}       # authored
    assert c.math                              # merged from description

def test_resolve_description_only():
    c = resolve_contract(_DescOnly())
    assert c.math and not c.inputs

def test_resolve_docstring_fallback_then_none_safe():
    assert resolve_contract(_Bare()).summary == "Plain docstring, no math."
    assert resolve_contract(None) is None
    assert resolve_contract(object()) is None
```

- [ ] **Step 2: Run, confirm failure** — `cd /Users/eranagmon/code/bigraph-schema && pytest tests/test_process_contract.py -x` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `bigraph_schema/contract.py`** — the dataclass with `field(default_factory=...)` for every mutable field; `to_dict` via `dataclasses.asdict`; a `_MATH_RE` matching the markers above; `from_description` (first non-empty line → summary, marker lines → math, remainder joined → description); `merged_with_description` returning a copy with only empty `summary`/`math`/`description` filled from `from_description(desc)`; `resolve_contract(instance)` = declared `contract` (a `ProcessContract` or dict) `.merged_with_description(instance.description or '')` if a `description` attr exists, else `from_description(instance.description)`, else `from_description(getdoc(type(instance)))`, all guarded so odd input returns None.

- [ ] **Step 4: Add `contract` attr + `contract()` method to `Edge`** — in `edge.py` beside `description`: `contract = None` class attr; a `contract()` method delegating to `resolve_contract(self)`. Import `resolve_contract` at module top (watch for import cycle — if any, import inside the method).

- [ ] **Step 5: Export** — add `from bigraph_schema.contract import ProcessContract` to `bigraph_schema/__init__.py`.

- [ ] **Step 6: Serialize `_contract`** — in `methods/serialize.py`'s `Link` overload, after the `encode` dict is built (~717), add the resolved contract when non-null: read it via the instance if available (`state.get('instance')` carries the live object on this path) or via `resolve_contract`; set `encode['_contract'] = contract.to_dict()` only when not None. Guard in a `try/except` so a process without contract support never breaks serialization.

- [ ] **Step 7: Run** — `pytest tests/test_process_contract.py -v` → all pass. Then `pytest -x` (full bigraph-schema suite) → green; the additive `contract = None` must not perturb anything.

- [ ] **Step 8: Commit** — `feat(contract): ProcessContract as a structured superset of Edge.description`.

---

### Task A2: Attach `_contract` + `config_schema` in the workbench env worker

**Repo:** `/Users/eranagmon/code/vivarium-dashboard`

**Files:**
- Modify: `vivarium_workbench/env_worker.py` (`_attach_process_docs`, ~lines 427-451 — it already imports the class from `node['address']` to read the docstring)
- Test: `tests/test_process_docs_attach.py`

**Interfaces:**
- Consumes: `resolve_contract` (A1)
- Produces: composite-state process nodes carrying `config_schema` and `_contract`; for a `Requester`/`Evolver` wrapper node, `_contract` resolves to the WRAPPED `PartitionedProcess`'s contract with a `role: "request" | "execute"` marker.

- [ ] **Step 1: Read the existing walk** — `sed -n '400,455p' vivarium_workbench/env_worker.py`. Note the class-resolution helper and its import guard; reuse both. Note how a node's `config` carries `process` for partition wrappers (the wrapped instance/address).

- [ ] **Step 2: Write the failing test** — a fake plain process class (with `config_schema` + a `description` with math) yields `config_schema` + `_contract` (summary+math) on its node; a fake Requester wrapper whose `config['process']` names a science class yields that science class's `_contract` plus `role: "request"`; an unresolvable address still yields a document (no crash, no keys). Use `monkeypatch` on the class-resolution helper (its real name from Step 1).

- [ ] **Step 3: Run, confirm failure** — `pytest tests/test_process_docs_attach.py -x`.

- [ ] **Step 4: Attach both** — in the branch that resolved the class: `schema = getattr(cls, 'config_schema', None); if schema: node['config_schema'] = _json_sanitize(schema)`. For the contract: if the class is a `Requester`/`Evolver` wrapper (detect by class name or by a `process` config key), resolve the WRAPPED process's class from `node['config']['process']` (address or instance) and tag `role`; else resolve `cls` directly. `from bigraph_schema.contract import resolve_contract`; set `node['_contract'] = {**contract.to_dict(), **({'role': role} if role else {})}` when non-null. Wrap in `try/except` so an older bigraph-schema without contracts cannot break rendering.

- [ ] **Step 5: Run** — `pytest tests/test_process_docs_attach.py -v` → pass.

- [ ] **Step 6: Verify against the real baseline** — regenerate and inspect:
```bash
cd /Users/eranagmon/code/v2ecoli && python scripts/regenerate_composite_states.py
python3 -c "
import json; d=json.load(open('reports/composite-state/v2ecoli.composites.baseline.json'))
def w(n):
  if not isinstance(n,dict): return
  if n.get('_type') in ('process','step'): yield n; return
  for k,v in n.items():
    if not k.startswith('_'): yield from w(v)
ps=list(w(d['state']))
print('with config_schema:', sum(1 for p in ps if p.get('config_schema')))
print('with _contract    :', sum(1 for p in ps if p.get('_contract')))
print('with contract math:', sum(1 for p in ps if p.get('_contract',{}).get('math')))
print('requester role    :', sum(1 for p in ps if p.get('_contract',{}).get('role')))
"
```
Expect `config_schema` ≥ 16, `_contract` ≥ 24 (every non-bookkeeping node incl. wrappers), math ≥ 16, roles ≥ 6. If `_contract` is near zero, bigraph-schema A1 isn't installed in the v2ecoli venv (`pip show bigraph-schema`).

- [ ] **Step 7: Commit** — `feat(workbench): attach process contracts + config_schema to composite state`.

---

## Phase B — Authoring (fan-out after Phase A lands)

Each batch below is one task: **author the structured contract on each class from its source, then a separate adversarial verification against the source.** Every task follows the same contract-authoring rubric:

**Authoring rubric (apply per class):**
1. Read the class's `description` (keep it — it holds the math; do NOT restate it in `math` unless improving it).
2. Read `config_schema` → author `config={param: what it controls}` for the scientifically meaningful params (skip pure plumbing like `seed`, `time_step` unless load-bearing).
3. Read the real method — `update(self, states, ...)` for `EcoliStep`; `calculate_request` + `evolve_state` for `PartitionedProcess` — and the port wiring, to author `inputs={port: what is read and WHY}` and `outputs={port: what is written}`. State what the process DOES with the port, never what the port contains ("decrements free RNAP by the number activated", not "reads bulk counts").
4. Author `symbols={sym: meaning + units}` for every symbol used in the math.
5. Author `assumptions` and `references` where the source/docstring supports them.
6. For a `PartitionedProcess`, put the contract on the science subclass; note in the summary that `calculate_request` sizes the request and `evolve_state` applies it.
7. Import `from bigraph_schema.contract import ProcessContract` (or the v2ecoli re-export) and set `contract = ProcessContract(...)` as a class attribute beside `config_schema`/`description`.

**Verification (per batch, separate agent):** for each authored class, open the source and confirm every `inputs`/`outputs` key is a real port; every `config` key exists in `config_schema`; every `symbols` entry appears in the math; and no authored claim contradicts the `update`/`calculate_request`/`evolve_state` logic. Report any unsupported line as a defect to fix — do NOT rubber-stamp.

**Batch tests (per batch):** a parametrized `pytest` asserting each class in the batch (a) declares a `contract`, (b) `resolve_contract(cls)` documents ≥1 input and ≥1 output, (c) names no port/config absent from the class's real `inputs()`/`outputs()`/`config_schema`, (d) states math or explicit logic.

### Task B1 — Transcription (unique.promoter / unique.active_RNAP clusters)
`transcript_initiation.py` (`TranscriptInitiation`), `transcript_elongation.py` (the `PartitionedProcess` subclass used by baseline), `tf_binding.py` (`TfBinding`), `tf_unbinding.py` (`TfUnbinding`), `ppgpp_initiation` (the class computing ppGpp-dependent basal_prob/fracActiveRnap).

### Task B2 — Translation (unique.active_ribosome cluster)
`polypeptide_initiation.py` (`PolypeptideInitiation`), `polypeptide_elongation.py` (`SteadyStatePolypeptideElongation`, the baseline subclass), `rna_degradation.py` (the `PartitionedProcess` subclass), `complexation.py` (`Complexation`), `rna_maturation.py` (`RnaMaturation`).

### Task B3 — Replication & chromosome (unique.full_chromosome / DnaA_box)
`chromosome_replication.py`, `chromosome_structure.py`, `equilibrium.py` (`Equilibrium`), and `mark_d_period`'s underlying class IF it carries science (else skip per coverage rule).

### Task B4 — Metabolism, environment, regulation (boundary cluster)
`metabolism.py` (`Metabolism`), `two_component_system.py` (`TwoComponentSystem`), `protein_degradation.py` (`ProteinDegradation`), `exchange_data` + `media_update` (author only if they carry model logic beyond bookkeeping; else note skipped), `counts_deriver` (`CountsDeriver` — the observable derivation), `division` (the division-detection science).

Each Bn task: author (rubric) → commit → adversarial verify → fix findings → re-verify. Batches are independent and MAY run in parallel once Phase A is merged into the v2ecoli venv; within a batch, author then verify sequentially.

---

## Phase C — Render check

### Task C1: End-to-end contract render verification
- [ ] Regenerate the baseline composite state; confirm every batch's classes now emit a rich `_contract` (structured `inputs`/`outputs`/`config`/`symbols`, not just math).
- [ ] Build loom (`scripts/build_loom.sh`), serve the v2ecoli workspace, open the baseline in process-column mode, zoom a representative process from each batch to the `contract` and `full` tiers, and confirm the card shows: summary, math, per-port semantics on the wires (focused), config rows, symbols with units. Screenshot each batch's exemplar.
- [ ] Confirm a bookkeeping node (e.g. `unique_update_1`) shows no authored contract (docstring fallback only) — no empty structured rows.
- [ ] Confirm a partitioned pair (`_requester`/`_evolver`) both show the underlying science contract, each marked with its half.

## Self-Review Notes

- **Reconciliation with `description` is the crux.** Every authored contract reuses the existing `description` math via `merged_with_description`; authoring adds structure, never rewrites math. A batch that restates or diverges the math is doing it wrong.
- **Correctness gate.** The per-batch adversarial verification against source is not optional — it is the mechanism that makes "correct for mathematicians" true rather than asserted.
- **loom needs no change.** PR #558 already renders `node._contract` across tiers; this plan only makes the backend emit richer contracts. If a tier renders a structured row wrong, that is a PR #558 bug, tracked there, not here.
- **Config VALUES vs semantics.** This plan surfaces config NAMES/TYPES (`config_schema`, A2) and config MEANING (contract `config`, authored). The separate `_raw_config` values fix (empty on 45/46 processes) is out of scope here — the contract's `config` semantics render regardless of whether runtime values are present.
