"""Run a bare process-bigraph ``Step`` as a study baseline — no hand-written
single-Step composite wrapper.

A study ``baseline`` entry may be ``{name, step: "<address>", params: {...}}``
instead of ``{name, composite: "<id>", params}``. ``<address>`` is a registered
Step (a dotted ``local:pkg.module.Class`` address, or a bare short name
registered in the workspace core). The study runner recognizes such a baseline
by an internal ``step:<address>`` spec_id and asks this module to synthesize the
minimal composite *state* that wraps the Step.

Why this exists: the workbench study runner's only entry point is a composite
that resolves to a process-bigraph state document. Historically, exposing a
single Step as a runnable study meant hand-writing a thin
``@composite_generator`` that wires ``Step + RAMEmitter + run_steps_on_init`` —
pure boilerplate that also clutters the Composites tab with entries that aren't
really compositions. This module removes that: given a Step address it builds
the exact same document shape at run time, so the Step *is* the baseline.

The synthesized state mirrors what those thin composites produce — a step node
with explicit output wiring, a top-level store per output, and a ``RAMEmitter``
over the outputs — so the existing state-serialization run path
(``resolve_study_baseline_state`` → ``run_composite_subprocess`` legacy branch)
runs and emits it with no runner changes.
"""
from __future__ import annotations

import importlib
from typing import Any, Optional, Tuple

STEP_PREFIX = "step:"


def is_step_spec(spec_id: Any) -> bool:
    """True when a baseline spec_id denotes a bare Step (``step:<address>``)."""
    return isinstance(spec_id, str) and spec_id.startswith(STEP_PREFIX)


def step_address(spec_id: str) -> str:
    """The Step address inside a ``step:<address>`` spec_id (identity otherwise)."""
    return spec_id[len(STEP_PREFIX):] if is_step_spec(spec_id) else spec_id


def _resolve_step_class(address: str, core):
    """Resolve a Step *address* to its class.

    Supports a dotted ``local:pkg.module.Class`` address (imported directly) and
    a bare short name (looked up in the workspace ``core``'s process registry,
    where ``build_core`` registers each local Step by ``cls.__name__``).
    """
    raw = address.split("local:", 1)[-1].strip()
    if "." in raw:
        mod_name, cls_name = raw.rsplit(".", 1)
        return getattr(importlib.import_module(mod_name), cls_name)
    # Bare short name: try the core's process registry (API varies by
    # process-bigraph version), best-effort.
    for attr in ("process_registry", "registry"):
        reg = getattr(core, attr, None)
        if reg is None:
            continue
        for meth in ("access", "get"):
            fn = getattr(reg, meth, None)
            if callable(fn):
                try:
                    got = fn(raw)
                    if got is not None:
                        return got
                except Exception:  # noqa: BLE001
                    pass
    raise ValueError(
        f"cannot resolve Step address {address!r}: use a dotted "
        "'local:pkg.module.Class' address, or register the short name in the "
        "workspace core."
    )


def build_step_state(spec_id_or_address: str, pkg: str,
                     config: Optional[dict]) -> Tuple[Optional[dict], Optional[dict]]:
    """Synthesize the composite *state* wrapping a bare Step.

    Builds the workspace core (``<pkg>.core.build_core``), instantiates the Step
    with ``config`` to read its input/output ports, and returns
    ``(state, None)`` — a dict with a top-level store per output, the step node
    wired to those stores, and a ``RAMEmitter`` over the outputs. Returns
    ``(None, {"error": ...})`` on any failure (unimportable core, unknown
    address, introspection error) so the caller can surface it like any other
    baseline-resolution error.
    """
    address = step_address(spec_id_or_address)
    try:
        build_core = importlib.import_module(f"{pkg}.core").build_core
    except Exception as e:  # noqa: BLE001
        return None, {"error": f"cannot import {pkg}.core.build_core: {e}"}
    try:
        core = build_core()
    except Exception as e:  # noqa: BLE001
        return None, {"error": f"{pkg}.core.build_core() failed: {e}"}
    try:
        cls = _resolve_step_class(address, core)
        step = cls(config=dict(config or {}), core=core)
        out_ports = list(step.outputs().keys())
        in_ports = list(step.inputs().keys())
    except Exception as e:  # noqa: BLE001
        return None, {"error": f"cannot introspect Step {address!r}: {e}"}
    if not out_ports:
        return None, {"error": f"Step {address!r} declares no outputs to emit"}

    state: dict = {port: {} for port in out_ports}
    state["step"] = {
        "_type": "step",
        "address": address,
        "config": dict(config or {}),
        "inputs": {p: [p] for p in in_ports},
        "outputs": {p: [p] for p in out_ports},
    }
    # RAMEmitter over the outputs — the run's captured result (mirrors the shape
    # the hand-written single-Step composites use).
    state["emitter"] = {
        "_type": "step",
        "address": "local:RAMEmitter",
        "config": {"emit": {p: "node" for p in out_ports}},
        "inputs": {p: [p] for p in out_ports},
    }
    return state, None
