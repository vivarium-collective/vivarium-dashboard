"""Canonical ``vwb …`` command strings for a workbench entity — the SINGLE
source of truth for every "how to run this in your terminal" surface.

Every advertising surface (single-study report, investigation SPA, study-detail
page, and the composite / process / study / investigation cards) plus the CLI's
own help/examples consume these, so the commands shown to a reviewer can never
drift from what the CLI actually accepts. The frontend card chips
(``static/walkthrough.js`` — ``_runCmdChip`` and the DAG nodes) mirror the exact
formats built here; keep the two in sync.

``vwb`` is the current canonical CLI (``pyproject`` ``[project.scripts]``:
``vwb`` == ``vivarium-workbench``). The old ``vdash`` alias still works but is
deprecated, so these builders emit ``vwb``.
"""

from __future__ import annotations

# The user-facing CLI name. All builders below prefix with this.
CLI = "vwb"


def study_run_commands(spec: dict, slug: str) -> dict:
    """Build the run-command strings for one study spec.

    Returns ``{"baseline", "variants": [{name, cmd}], "simulations":
    [{name, cmd}], "rerun_hint"}``. Pure; tolerant of missing sections.
    """
    base = f"{CLI} run study {slug}"
    conds = spec.get("conditions") or {}
    variants = []
    for v in (conds.get("variants") or []):
        if not isinstance(v, dict):
            continue
        name = v.get("name")
        if not name:
            continue
        variants.append({"name": name, "cmd": f"{base} --variant {name}"})
    simulations = []
    for s in (spec.get("simulation_set") or []):
        if not isinstance(s, dict):
            continue
        name = s.get("name")
        if not name:
            continue
        simulations.append({"name": name, "cmd": base})
    return {
        "baseline": base,
        "variants": variants,
        "simulations": simulations,
        "rerun_hint": f"{CLI} rerun <run-id>",
    }


def composite_run_command(rec: dict) -> str:
    """Single-line command to run one composite for N steps.

    ``vwb run composite <spec_id> [--steps <default_n_steps>]``. Omits
    ``--steps`` when the composite declares no positive default (the CLI then
    falls back to its own default). Returns ``""`` when the record has no id.
    """
    spec_id = str((rec or {}).get("id") or "").strip()
    if not spec_id:
        return ""
    cmd = f"{CLI} run composite {spec_id}"
    steps = (rec or {}).get("default_n_steps")
    if isinstance(steps, bool):  # bool is an int subclass — never a step count
        steps = None
    if isinstance(steps, int) and steps > 0:
        cmd += f" --steps {steps}"
    return cmd


def investigation_run_command(slug: str) -> str:
    """``vwb run investigation <slug>`` — runs every study in the investigation."""
    slug = (slug or "").strip()
    return f"{CLI} run investigation {slug}" if slug else ""


def process_run_command(address: str, package: str) -> str:
    """A standalone ``python -c`` one-liner that runs one registry process once.

    There is no first-class ``vwb run process`` (a process runs inside a
    composite), so this mirrors ``env_worker._run_process``: build the workspace
    core, resolve the class by its registry ``address``, instantiate it with an
    empty config, fill its input ports with core defaults, and run a single
    ``update()`` (Steps take ``update(state)``, Processes ``update(state,
    interval)`` — dispatched by the update signature's arity).

    It is a copy-paste STARTER: a process that needs real config or sim_data will
    want the two ``{}`` placeholders edited. Returns ``""`` without an address or
    a workspace package (``build_core`` lives at ``<package>.core.build_core``).
    """
    address = (address or "").strip()
    package = (package or "").strip()
    if not address or not package:
        return ""
    # Short class name for the fallback match (strip a `local:` protocol and any
    # dotted module path), mirroring env_worker._run_process's `short`.
    short = address.split(":")[-1].split(".")[-1]
    body = (
        f"import {package}.core as _m; _c=_m.build_core(); "
        "_r=getattr(_c,'link_registry',{}); "
        "_cls=next((v for v in _r.values() if isinstance(v,type) and "
        f"(v.__module__+'.'+v.__qualname__=={address!r} or v.__qualname__=={short!r})), "
        f"_r.get({address!r})); "
        f"assert isinstance(_cls,type), 'process not found: {address}'; "
        "_p=_cls({}, _c); _s=_c.fill(_p.inputs(), {}); import inspect as _i; "
        "print(_p.update(_s) if len(_i.signature(_p.update).parameters)<2 "
        "else _p.update(_s, 1.0))"
    )
    return f'python3 -c "{body}"'
