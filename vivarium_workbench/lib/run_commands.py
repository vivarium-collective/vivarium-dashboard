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


def _steps_suffix(steps) -> str:
    """`` --steps N`` for a positive int step count, else ``""`` (bool rejected)."""
    if isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0:
        return ""
    return f" --steps {steps}"


def study_run_commands(spec: dict, slug: str, *, steps=None) -> dict:
    """Build the run-command strings for one study spec.

    Returns ``{"baseline", "variants": [{name, cmd}], "simulations":
    [{name, cmd}], "rerun_hint"}``. Pure; tolerant of missing sections. When
    ``steps`` is a positive int (typically the study's baseline composite
    ``default_n_steps``) it's appended as ``--steps N`` so the study reads as
    runnable-like-a-composite.
    """
    base = f"{CLI} run study {slug}{_steps_suffix(steps)}"
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


def investigation_run_command(slug: str, *, steps=None) -> str:
    """``vwb run investigation <slug> [--steps N]`` — runs every study in it.

    ``steps`` (a positive int) forces every study to run that many ticks — a
    quick whole-investigation smoke run; omit it and each study uses the length
    declared in its own simulation spec.
    """
    slug = (slug or "").strip()
    return f"{CLI} run investigation {slug}{_steps_suffix(steps)}" if slug else ""


def process_run_command(address: str) -> str:
    """``vwb run process <address>`` — instantiate one registry process/step from
    the workspace core and run a single ``update()``.

    A process normally runs inside a composite, so this is the standalone
    equivalent: the CLI builds the workspace core, resolves the class by its
    registry ``address`` (e.g. ``pkg.processes.Foo`` or ``local:Foo``), fills its
    input ports, and steps it once (see ``cli_runs.run_process``). Returns ``""``
    without an address.
    """
    address = (address or "").strip()
    return f"{CLI} run process {address}" if address else ""
