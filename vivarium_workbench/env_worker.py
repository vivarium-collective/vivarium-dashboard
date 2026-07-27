"""Env worker — the per-session subprocess that holds a workspace's compute
environment out of the HTTP process.

Full contract: ``docs/env-worker-protocol.md``. This is the **worker program**
(spec §4): a single self-contained file, shipped by the workbench but run on the
workspace's interpreter by path, importing **only the standard library** (plus,
in later slices, what the workspace venv already has). It never imports
``vivarium_workbench``.

**Scope so far:** the transport + lifecycle (``initialize`` / ``ping`` /
``shutdown``) and the environment queries ``list_generators``,
``registry_catalog``, and ``viz_classes`` — each imports the workspace's own
package (and, for the latter two, calls ``build_core``) **in this process**, so
the imports the HTTP process must not do live here instead. The remaining
``build_core``-backed methods (``resolve_composite_state``, ``observables`` …)
land in later slices. These import viva_superpowers + the workspace package (both
workspace-venv deps, spec §4); everything else is stdlib.

Invocation (spec §4/§5)::

    <python> <path>/env_worker.py --socket-fd <n> --workspace <dir>

``--socket-fd`` is the inherited end of a ``socket.socketpair()`` (passed via
``subprocess(pass_fds=...)``); ``stdout``/``stderr`` are for logs, never the
protocol (spec §5).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import sys
import time
import traceback

PROTOCOL_VERSION = "1.0"
_MAX_FRAME = 64 * 1024 * 1024  # 64 MiB cap (spec §5) — over-cap is an error, not an OOM
_started = time.monotonic()
_workspace = ""


class _MethodError(Exception):
    """A structured JSON-RPC error (spec §9)."""

    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _recv_exact(sock: socket.socket, n: int) -> "bytes | None":
    """Read exactly ``n`` bytes, or ``None`` on EOF (the parent went away)."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _read_frame(sock: socket.socket) -> "dict | None":
    """One length-prefixed JSON frame (uint32 BE length + UTF-8 JSON), or None on EOF."""
    hdr = _recv_exact(sock, 4)
    if hdr is None:
        return None
    (n,) = struct.unpack(">I", hdr)
    if n > _MAX_FRAME:
        raise _MethodError(-32600, f"frame too large: {n} bytes")
    body = _recv_exact(sock, n)
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))


def _write_frame(sock: socket.socket, obj: dict) -> None:
    # default=str coerces the odd non-JSON leaf (numpy scalar, Path, …) that
    # survives a state doc, matching the old composite subprocess's
    # json.dumps(default=str). Cheap for the string-only methods (never fires).
    body = json.dumps(obj, default=str).encode("utf-8")
    sock.sendall(struct.pack(">I", len(body)) + body)


_CAPABILITIES = ["initialize", "ping", "list_generators", "registry_catalog",
                 "run_process", "process_template",
                 "viz_classes", "resolve_composite_state", "observables",
                 "study_readout_check", "attach_process_docs", "discover_composites", "composites_full",
                 "validate_generated_visualization", "run_study_analyses", "viz_class_inputs", "render_viz_doc", "viz_preview", "report_core_snapshot", "reexport_map", "data_sources_provider", "analysis_viewers", "shutdown"]

_FRAMEWORK_PKGS = {
    "process_bigraph", "bigraph_schema", "bigraph_viz",
    "viva_superpowers", "vivarium_workbench", "pbg_emitters",
}


def _describe_class(cls) -> str:
    """Human description for a registered class: an explicit ``description``
    attribute (the pbg convention) if present, else the first paragraph of the
    docstring. Best-effort — never raises."""
    import inspect as _inspect
    try:
        d = getattr(cls, "description", None)
        if isinstance(d, str) and d.strip():
            return d.strip()
    except Exception:
        pass
    try:
        doc = _inspect.getdoc(cls)
        return doc.strip() if doc else ""
    except Exception:
        return ""


def _port_schema(cls, which: str):
    """Best-effort ports (``inputs``/``outputs``) schema for a Process/Step
    class, WITHOUT instantiating it.

    ``inputs()``/``outputs()`` are normally instance methods returning a schema
    dict; most implementations return a static schema and tolerate being called
    with the class in place of ``self``. We try that and degrade to ``None`` when
    the method genuinely needs a configured instance. Returns a JSON-safe dict
    (port name -> type schema) or ``None``."""
    import inspect as _inspect
    import json as _json
    fn = getattr(cls, which, None)
    if fn is None:
        return None
    try:
        sig = _inspect.signature(fn)
        got = fn(cls) if len(sig.parameters) >= 1 else fn()
    except Exception:
        return None
    if not isinstance(got, dict):
        return None
    try:
        return _json.loads(_json.dumps(got, default=str))
    except Exception:
        return None


def _workspace_meta(workspace: str):
    """``(package_name, workspace_pkgs_set, ws_data)`` from ``workspace.yaml`` —
    faithful to ``registry.build_registry``'s pre-script computation (both
    ``imports:`` shapes: dict keyed by catalog name, or list of dicts/strings)."""
    from pathlib import Path

    import yaml
    ws_data = yaml.safe_load((Path(workspace) / "workspace.yaml").read_text(encoding="utf-8")) or {}
    slug = ws_data.get("name", "")
    package_name = ws_data.get("package_path") or ("pbg_" + str(slug).replace("-", "_"))
    imports_raw = ws_data.get("imports") or []
    pkgs: list = []
    if isinstance(imports_raw, dict):
        for cat_name, imp_val in imports_raw.items():
            pkg = (imp_val.get("package") if isinstance(imp_val, dict) else None) \
                or cat_name.replace("-", "_")
            pkgs.append(pkg.split(".")[0])
    elif isinstance(imports_raw, list):
        for entry in imports_raw:
            if isinstance(entry, dict):
                pkg = entry.get("package") or (entry.get("name") or "").replace("-", "_")
            elif isinstance(entry, str):
                pkg = entry.replace("-", "_")
            else:
                continue
            if pkg:
                pkgs.append(pkg.split(".")[0])
    pkgs.append(package_name.split(".")[0])
    return package_name, set(dict.fromkeys(pkgs)), ws_data


def _registry_catalog() -> dict:
    """Build the workspace's core and introspect its registered processes/types
    (spec §11). A faithful in-worker port of ``registry.build_registry``'s
    embedded subprocess script — the ``core`` object can't cross the socket, so
    the introspection must run where the core lives. Returns the RAW
    ``{processes, types, workspace_pkgs}`` (the workbench applies its emitter
    ``is_workspace_default`` post-processing on top)."""
    import inspect as _inspect
    import json as _json

    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    try:
        package_name, workspace_pkgs, _ws_data = _workspace_meta(_workspace)
    except Exception as e:  # noqa: BLE001
        return {"error": f"workspace.yaml unreadable: {e}", "processes": [], "types": []}

    try:
        mod = __import__(f"{package_name}.core", fromlist=["build_core"])
        core = mod.build_core()
    except ImportError as e:
        return {"error": f"could not import {package_name}.core: {e}", "processes": [], "types": []}
    except Exception as e:  # noqa: BLE001
        return {"error": f"build_core() failed: {e}", "processes": [], "types": []}

    import process_bigraph as _pb
    EMITTER_CLS = getattr(_pb, "Emitter", None)
    try:
        from viva_superpowers.visualization import Visualization as VISUALIZATION_CLS
    except ImportError:
        VISUALIZATION_CLS = None

    def _classify_source(cls):
        try:
            top_pkg = cls.__module__.split(".")[0]
        except Exception:
            return "environment_only"
        if top_pkg in workspace_pkgs:
            return "in_workspace"
        if top_pkg in _FRAMEWORK_PKGS:
            return "framework"
        return "environment_only"

    processes: list = []
    seen_classes: dict = {}
    link_reg = getattr(core, "link_registry", {}) or {}
    for name, cls in link_reg.items():
        cls_id = id(cls)
        is_qualified = "." in name
        if cls_id in seen_classes:
            existing = seen_classes[cls_id]
            if not is_qualified and "." in processes[existing]["name"]:
                processes[existing]["aliases"].append(processes[existing]["name"])
                processes[existing]["name"] = name
            else:
                processes[existing]["aliases"].append(name)
            continue
        try:
            addr = f"{cls.__module__}.{cls.__qualname__}"
        except Exception:
            addr = str(cls)
        kind = "other"
        if isinstance(cls, type):
            if EMITTER_CLS is not None and issubclass(cls, EMITTER_CLS) and cls is not EMITTER_CLS:
                kind = "emitter"
            elif VISUALIZATION_CLS is not None and issubclass(cls, VISUALIZATION_CLS) and cls is not VISUALIZATION_CLS:
                kind = "visualization"
            elif hasattr(cls, "__mro__"):
                for ancestor in cls.__mro__:
                    if ancestor.__name__ in ("Process", "ProcessEnsemble"):
                        kind = "process"
                        break
                    # ReportCardStep is a Step subclass — classify it FIRST as its
                    # own kind so the Registry's "Report Cards" tab can list them.
                    if ancestor.__name__ == "ReportCardStep":
                        kind = "report_card"
                        break
                    if ancestor.__name__ == "Step":
                        kind = "step"
                        break
        schema_preview = ""
        config_schema = None
        if hasattr(cls, "config_schema"):
            try:
                config_schema = _json.loads(_json.dumps(cls.config_schema, default=str))
                schema_preview = _json.dumps(cls.config_schema, default=str)[:400]
            except Exception:
                schema_preview = "<unserializable>"
        description = _describe_class(cls)
        inputs_schema = _port_schema(cls, "inputs")
        outputs_schema = _port_schema(cls, "outputs")
        source = _classify_source(cls)
        # Framework hygiene: hide process_bigraph's OWN built-in process/step/other
        # classes from every workspace's registry (emitters + visualizations kept).
        _topmod = (getattr(cls, "__module__", "") or "").split(".")[0]
        if _topmod == "process_bigraph" and kind in ("process", "step", "other"):
            continue
        try:
            if isinstance(cls, type) and _inspect.isabstract(cls):
                continue
        except Exception:
            pass
        seen_classes[cls_id] = len(processes)
        processes.append({
            "name": name, "address": addr, "kind": kind,
            "schema_preview": schema_preview, "aliases": [], "source": source,
            "description": description,
            "config_schema": config_schema,
            "inputs": inputs_schema,
            "outputs": outputs_schema,
        })
    _source_order = {"in_workspace": 0, "framework": 1, "environment_only": 2}
    processes.sort(key=lambda p: (
        _source_order.get(p.get("source", "environment_only"), 2),
        "." in p["name"], p["name"]))

    types: list = []
    type_reg = getattr(core, "registry", {}) or {}
    for name in sorted(type_reg.keys()):
        try:
            td = core.access(name)
            preview = str(td)[:200] if td is not None else ""
        except Exception as e:  # noqa: BLE001
            preview = f"<error: {e}>"
        types.append({"name": name, "schema_preview": preview})

    return {"processes": processes, "types": types, "workspace_pkgs": list(workspace_pkgs)}


def _list_visualizations() -> dict:
    """Registered Visualization / Analysis classes for this environment (spec §11).

    A faithful in-worker port of ``visualization_classes.list_visualization_classes``
    — build the workspace core, snapshot its ``link_registry``, inject the default
    ``viva_superpowers`` viz classes + any workspace-local ``<pkg>.visualizations``
    submodules, filter to ``Visualization`` subclasses, and append the v2ecoli
    ``Analysis`` steps. Returns the JSON ``{"classes": [...]}`` (the live classes
    can't cross the socket, so this introspection runs where they live). Tolerant:
    a build_core / import failure degrades to the classes still discoverable."""
    from pathlib import Path

    import yaml

    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)

    # Build the class registry from the workspace's core module (tolerant).
    try:
        ws_data = (
            yaml.safe_load((Path(_workspace) / "workspace.yaml").read_text(encoding="utf-8")) or {}
        )
        pkg = ws_data.get("package_path") or ("pbg_" + str(ws_data.get("name", "")).replace("-", "_"))
        core_module = __import__(f"{pkg}.core", fromlist=["build_core"])
        core = core_module.build_core()
        registry: dict = dict(core.link_registry)
    except Exception:  # noqa: BLE001 — a broken core still yields the defaults below
        registry = {}
        ws_data = {}

    # Inject the standard pbg-superpowers visualization classes.
    try:
        from viva_superpowers.visualizations import (
            Distribution, Heatmap, ParamVsObservable, PhaseSpace, TimeSeriesPlot,
        )
        for cls in [TimeSeriesPlot, ParamVsObservable, Distribution, PhaseSpace, Heatmap]:
            registry[cls.__name__] = cls
    except ImportError:
        pass

    # Inject workspace-local viz classes (non-pip-installed) from <pkg>.visualizations.
    try:
        import importlib as _importlib
        import pkgutil as _pkgutil

        from viva_superpowers.visualization import Visualization as _VizBase
        _pkg_name = ws_data.get("package_path") or (
            "pbg_" + str(ws_data.get("name", "")).replace("-", "_"))
        viz_pkg = _importlib.import_module(f"{_pkg_name}.visualizations")
        for _, modname, _ in _pkgutil.iter_modules(viz_pkg.__path__):
            try:
                mod = _importlib.import_module(f"{_pkg_name}.visualizations.{modname}")
                for attr_val in vars(mod).values():
                    if not isinstance(attr_val, type):
                        continue
                    if attr_val is _VizBase:
                        continue
                    if issubclass(attr_val, _VizBase):
                        registry[attr_val.__name__] = attr_val
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass

    try:
        from viva_superpowers.visualization import Visualization as _VB
    except ImportError:
        _VB = None

    def _is_viz(cls):
        if _VB is not None and cls is _VB:
            return False
        marker = getattr(cls, "is_visualization", None)
        if callable(marker):
            try:
                if marker() is True:
                    return True
            except Exception:  # noqa: BLE001
                pass
        if _VB is not None:
            try:
                if isinstance(cls, type) and issubclass(cls, _VB):
                    return True
            except TypeError:
                pass
        return False

    per_cls: dict = {}
    for name, cls in registry.items():
        if not _is_viz(cls) or name == "Visualization":
            continue
        existing = per_cls.get(id(cls))
        if existing is None or len(name) < len(existing[0]):
            per_cls[id(cls)] = (name, cls)

    out = []
    for name, cls in sorted(per_cls.values(), key=lambda kv: kv[0]):
        try:
            doc = (cls.__doc__ or "").strip().split("\n", 1)[0] if cls.__doc__ else ""
        except Exception:  # noqa: BLE001
            doc = ""
        out.append({"address": f"local:{name}", "name": name, "doc": doc, "kind": "visualization"})

    # Append Analysis classes (process-bigraph Steps) from v2ecoli, if installed.
    try:
        import v2ecoli.workflow.analyses  # noqa: F401  (import-time registration)
        from v2ecoli.workflow.analysis import ANALYSIS_REGISTRY, Analysis
        for _name, _cls in sorted(ANALYSIS_REGISTRY.items()):
            if isinstance(_cls, type) and issubclass(_cls, Analysis):
                try:
                    _doc = (_cls.__doc__ or "").strip().split("\n")[0]
                except Exception:  # noqa: BLE001
                    _doc = ""
                out.append({
                    "address": f"local:{_cls.__module__}.{_cls.__qualname__}",
                    "name": _name, "doc": _doc, "kind": "analysis",
                })
    except Exception:  # noqa: BLE001
        pass

    return {"classes": out}


# --- process-doc decoration (ported from lib/process_docs.py; the worker can't
#     import vivarium_workbench, and these must run where the workspace classes +
#     the built doc's numpy values live, i.e. in this process) ------------------
def _pd_describe_class(cls) -> str:
    """Formal description for a process/step class via ``Edge.describe()`` on an
    uninitialized instance, falling back to ``description`` / ``__doc__``."""
    try:
        inst = cls.__new__(cls)  # uninitialized — skips __init__/core requirement
        describe = getattr(inst, "describe", None)
        if callable(describe):
            text = describe()
            if isinstance(text, str) and text.strip():
                return text.strip()
    except Exception:  # noqa: BLE001
        pass
    desc = getattr(cls, "description", "")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    doc = getattr(cls, "__doc__", None)
    return doc.strip() if isinstance(doc, str) else ""


def _pd_class_for_address(address: str):
    """Import the class a ``local:<dotted.path>`` address names, or ``None``.

    The single address→class resolver reused for both docstrings and contracts.
    All failures (bad address, unimportable module, missing attribute) swallowed
    → ``None``.
    """
    import importlib
    if not isinstance(address, str) or not address:
        return None
    addr = address.split(":", 1)[1] if ":" in address else address
    if "." not in addr:
        return None  # bare registry name — can't import a dotted path
    module_path, _, cls_name = addr.rpartition(".")
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, cls_name, None)
    except Exception:  # noqa: BLE001
        return None


def _pd_doc_for_address(address: str) -> str:
    """Formal description for a ``local:<dotted.path>`` address, or ''."""
    cls = _pd_class_for_address(address)
    return _pd_describe_class(cls) if cls is not None else ""


def _class_for_address(address: str, core=None):
    """Resolve a process address to its class — dotted OR bare registry name.

    ``_pd_class_for_address`` only handles a dotted ``local:pkg.mod.Cls`` address
    (it imports the module). A bare registry-name address (``local:EcoliWCM``,
    the ``register_link`` convention) has no importable path, so it must be
    resolved through the composite's own ``core.link_registry``. ``core`` is the
    one built from the generator's ``core_extensions`` (see
    ``_resolve_composite_state``); ``None`` when unavailable. All failures → None.
    """
    cls = _pd_class_for_address(address)
    if cls is not None:
        return cls
    if core is None or not isinstance(address, str):
        return None
    name = address.split(":", 1)[1] if ":" in address else address
    if not name or "." in name:
        return None  # dotted already handled above; bare name only here
    reg = getattr(core, "link_registry", None)
    try:
        if isinstance(reg, dict):
            return reg.get(name)
        if reg is not None and hasattr(reg, "get"):
            return reg.get(name)
    except Exception:  # noqa: BLE001
        pass
    return None


def _is_composite_process_class(cls) -> bool:
    """True when ``cls`` is a "Composite Process" — a process whose inner model
    is itself a bigraph ``Composite`` the loom can drill into. Two signals:
    the class IS a ``Composite`` subclass, or it declares the ``inner_composite``
    convention method (a wrapper ``Process`` holding an inner composite, e.g.
    ``EcoliWCM``). Cheap: class introspection only, no instantiation."""
    if cls is None or not isinstance(cls, type):
        return False
    try:
        from process_bigraph import Composite
        if issubclass(cls, Composite):
            return True
    except Exception:  # noqa: BLE001
        pass
    return hasattr(cls, "inner_composite")


def _inner_composite_of(inst):
    """The inner ``Composite`` a live process instance wraps, or ``None``.

    Mirror of ``_is_composite_process_class`` on the instance side: the instance
    IS a ``Composite``, or exposes ``inner_composite()`` (builds it lazily —
    e.g. ``EcoliWCM``), or holds one as an attribute. Used to drill one level."""
    if inst is None:
        return None
    try:
        from process_bigraph import Composite
    except Exception:  # noqa: BLE001
        return None
    if isinstance(inst, Composite):
        return inst
    fn = getattr(inst, "inner_composite", None)
    if callable(fn):
        try:
            got = fn()
        except Exception:  # noqa: BLE001
            return None
        return got if isinstance(got, Composite) else None
    try:
        for v in vars(inst).values():
            if isinstance(v, Composite):
                return v
    except Exception:  # noqa: BLE001
        pass
    return None


def _nav_state(state_tree, segs):
    """Navigate a composite ``state`` tree by a list of key segments (the loom
    node ``path``). Tolerates one leading ``{'state': ...}`` wrapper per level
    (build_generator emits it; a live ``Composite.state`` does not), matching
    ``convert.ts``'s ``state?.state ?? state`` unwrap. Returns the node or None."""
    cur = state_tree
    for s in segs:
        if not isinstance(cur, dict):
            return None
        if s not in cur and isinstance(cur.get("state"), dict):
            cur = cur["state"]
        if not isinstance(cur, dict) or s not in cur:
            return None
        cur = cur[s]
    return cur


def _pd_json_sanitize(obj):
    """Stdlib-only JSON-safety pass for the small structures we attach here
    (``config_schema``): drop non-finite floats, stringify anything not
    JSON-native. The env worker must not import ``vivarium_workbench.lib``, so
    this mirrors ``lib.json_serialize._json_sanitize`` in miniature."""
    import math as _math
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        return obj if _math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _pd_json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_pd_json_sanitize(v) for v in obj]
    return str(obj)


def _pd_instance_config(inst):
    """The live process instance's actual config dict (ParCa-hydrated, the values
    it will SIMULATE with). Native pbg processes keep it on ``_config``;
    vivarium-wrapped V1 processes keep it on ``parameters``. First non-empty dict
    wins; ``None`` if the instance is absent or exposes no config dict."""
    if inst is None or isinstance(inst, str):
        return None
    for attr in ("parameters", "_config", "config"):
        v = getattr(inst, attr, None)
        if isinstance(v, dict) and v:
            return v
    return None


def _pd_config_sanitize(obj, depth=0):
    """JSON-safe, SIZE-BOUNDED view of a loaded config value: keep scalars and
    small collections verbatim, but summarize the ParCa-scale arrays / matrices /
    lookup dicts (which would otherwise bloat the doc by megabytes) to a shape
    string. Conveys "this is loaded and ready to simulate" without dumping every
    element. Callables render as ``<fn name>``, quantities as their str form."""
    import math as _math
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if _math.isfinite(obj) else None
    if isinstance(obj, str):
        return obj if len(obj) <= 200 else obj[:197] + "…"
    if callable(obj):
        return f"<fn {getattr(obj, '__name__', type(obj).__name__)}>"
    # pint Quantity → split magnitude (the VALUE) from unit (the TYPE). Must run
    # BEFORE the numpy-shape branch: a scalar Quantity is numpy-backed, so it has
    # a `.shape` and would otherwise summarize as "Quantity() float64" — losing
    # both the number AND the unit. Emit `{_type: <unit>, _value: <magnitude>}`
    # so the card shows e.g. value 1100, type "gram / liter" (units never sit in
    # the value string). config_schema's own type is unreliable for wrapped V1
    # processes (reports bare `float`), so the unit from the live value wins.
    mag = getattr(obj, "magnitude", None)
    units = getattr(obj, "units", None)
    if mag is not None and units is not None:
        unit = str(units)
        mshape = getattr(mag, "shape", None)
        if mshape:  # array quantity
            return {"_type": f"array[{unit}]", "_value": f"array{tuple(mshape)}"}
        try:
            v = float(mag)
            v = v if _math.isfinite(v) else None
        except Exception:  # noqa: BLE001
            v = str(mag)[:60]
        return {"_type": unit, "_value": v}
    # numpy / array-likes carrying a shape → summarize as Type(shape) dtype.
    shape = getattr(obj, "shape", None)
    if shape is not None and not isinstance(obj, dict):
        dt = getattr(getattr(obj, "dtype", None), "name", "")
        return f"{type(obj).__name__}{tuple(shape)}" + (f" {dt}" if dt else "")
    if isinstance(obj, dict):
        # The top-level config dict is the parameter list — keep every key. A
        # NESTED large dict is a lookup table (e.g. a matrix as dict) — summarize.
        if depth > 0 and len(obj) > 16:
            return f"dict[{len(obj)} keys]"
        return {str(k): _pd_config_sanitize(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        seq = list(obj)
        n = len(seq)
        if n > 8:
            et = type(seq[0]).__name__ if n else ""
            return f"[{n} {et}s]" if et else f"[{n} items]"
        return [_pd_config_sanitize(v, depth + 1) for v in seq]
    return str(obj)[:120]


import re as _re

# ``repr`` of a live process instance once the state has been JSON-serialized:
# ``<v2ecoli.processes.rna_degradation.RnaDegradation object at 0x…>`` — the
# dotted class path is recoverable from it.
_OBJ_REPR_RE = _re.compile(r"^<([A-Za-z_][\w.]*)\s+object at 0x[0-9A-Fa-f]+>$")


def _pd_resolve_contract_from_value(value):
    """Resolve a contract from a wrapped-process VALUE, which may be a live
    instance, an ``address`` string, a serialized ``repr`` string, or a 1-tuple
    quoting any of those. Returns a ``ProcessContract`` or ``None``."""
    try:
        from bigraph_schema.contract import resolve_contract
    except Exception:  # noqa: BLE001
        return None
    if isinstance(value, (list, tuple)):  # quoted process port → (instance,)
        value = value[0] if value else None
    if value is None:
        return None
    try:
        if isinstance(value, str):
            m = _OBJ_REPR_RE.match(value.strip())
            dotted = m.group(1) if m else value  # repr → path; else an address
            cls = _pd_class_for_address(dotted)
            return resolve_contract(cls) if cls is not None else None
        return resolve_contract(value)  # a live instance
    except Exception:  # noqa: BLE001
        return None


def _pd_contract_for_node(node, parent=None, key=None, get_core=None) -> "dict | None":
    """Resolve the JSON-safe ``_contract`` dict for a process/step ``node``, or
    ``None``. Handles the ``Requester``/``Evolver`` partition wrappers: their
    contract belongs to the WRAPPED ``PartitionedProcess``, which is carried
    either in ``config['process']`` (the live-build shape) or — once the state
    has been serialized — in the sibling ``process`` store keyed by the wrapper
    node's ``<base_name>`` (its own key minus ``_requester``/``_evolver``). The
    result is tagged with ``role: "request"|"execute"``. Never raises — any
    failure (old bigraph-schema, unresolvable wrapped class, …) → ``None``
    rather than a partial document.
    """
    try:
        from bigraph_schema.contract import resolve_contract  # noqa: F401
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(node, dict):
        return None
    addr = node.get("address", "")
    cls = _pd_class_for_address(addr)
    # Bare registry-name address (local:EcoliWCM / local:PymunkProcess) — not
    # importable by path; resolve it through the composite's core link_registry
    # so registry-linked processes still get their declared contract.
    if cls is None and get_core is not None:
        cls = _class_for_address(addr, get_core())
    cfg = node.get("config")
    cfg = cfg if isinstance(cfg, dict) else {}
    cls_name = getattr(cls, "__name__", "")

    is_wrapper = cls_name in ("Requester", "Evolver") or ("process" in cfg)
    if is_wrapper:
        role = {"Requester": "request", "Evolver": "execute"}.get(cls_name)
        # Source order: declared config['process'], then the sibling `process`
        # store (the serialized shape) looked up by the node's base name.
        contract = None
        if cfg.get("process") is not None:
            contract = _pd_resolve_contract_from_value(cfg.get("process"))
        if contract is None and isinstance(parent, dict) and isinstance(key, str):
            base = key
            for suf in ("_requester", "_evolver"):
                if base.endswith(suf):
                    base = base[: -len(suf)]
                    break
            store = parent.get("process")
            if isinstance(store, dict) and base in store:
                contract = _pd_resolve_contract_from_value(store.get(base))
        if contract is None:
            return None  # wrapper but wrapped process unresolvable → no contract
    else:
        role = None
        if cls is None:
            return None
        try:
            contract = resolve_contract(cls)
        except Exception:  # noqa: BLE001
            return None
        if contract is None:
            return None

    try:
        d = contract.to_dict()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(d, dict):
        return None
    return {**d, "role": role} if role else d


def _summarize_large_values(node, max_list: int = 40, max_str: int = 2000):
    """Copy of a composite-state doc with large leaf VALUES summarized — the
    multi-MB numpy ``bulk`` store becomes ``⟨N items⟩`` so the response stays
    small. Pure; must run here (numpy can't cross the socket)."""
    if isinstance(node, dict):
        return {k: _summarize_large_values(v, max_list, max_str) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        if len(node) > max_list:
            return f"⟨{len(node)} items⟩"
        return [_summarize_large_values(v, max_list, max_str) for v in node]
    if isinstance(node, str):
        return node[:max_str] + "…" if len(node) > max_str else node
    if isinstance(node, (bytes, bytearray)):
        return f"⟨{len(node)} bytes⟩"
    try:
        n = len(node)
    except TypeError:
        return node
    return f"⟨{n} items⟩" if n > max_list else node


def _attach_process_docs(doc, get_core=None):
    """Walk a composite-state doc in place, setting ``node['doc']`` for each
    process/step from its address's class description. All failures swallowed.

    ``get_core`` is an optional zero-arg callable returning the composite's core
    (built lazily from its ``core_extensions``) — used only to resolve bare
    registry-name addresses (``local:EcoliWCM``) when flagging Composite
    Processes, so a composite with no such addresses never pays to build one."""
    _cache: dict = {}

    def walk(node, parent=None, key=None):
        if isinstance(node, dict):
            if node.get("_type") in ("process", "step"):
                addr = node.get("address", "")
                if "doc" not in node:
                    if addr not in _cache:
                        _cache[addr] = _pd_doc_for_address(addr)
                    d = _cache[addr]
                    if d:
                        node["doc"] = d
                # Additive: config_schema (from the address class) + _contract
                # (contract-aware, wrapper-aware). Each guarded independently so
                # an older bigraph-schema, or an unresolvable address, still
                # yields a valid document (no crash, no partial keys).
                if "config_schema" not in node:
                    try:
                        cls = _pd_class_for_address(addr)
                        schema = getattr(cls, "config_schema", None) if cls is not None else None
                        if schema:
                            node["config_schema"] = _pd_json_sanitize(schema)
                    except Exception:  # noqa: BLE001
                        pass
                # Flag Composite Processes (a process whose inner model is itself
                # a bigraph Composite) so the loom shows a drill-in affordance.
                # Resolve the class dotted-first, then via the composite's core
                # for bare registry-name addresses (local:EcoliWCM). get_core is
                # only invoked when the cheap dotted resolve fails, so a flat
                # composite of dotted-address leaf processes never builds a core.
                if "is_composite_process" not in node:
                    try:
                        cls = _pd_class_for_address(addr)
                        if cls is None and get_core is not None:
                            cls = _class_for_address(addr, get_core())
                        if _is_composite_process_class(cls):
                            node["is_composite_process"] = True
                    except Exception:  # noqa: BLE001
                        pass
                # Fully-loaded config: the spec's `config` is usually {} (the
                # process runs on defaults), but the LIVE instance carries its
                # actual ParCa-hydrated config — the values it will simulate with.
                # Serialize that (size-bounded) so cards show a ready-to-simulate
                # config, not empty/defaults. Only when the spec didn't set one.
                if not node.get("config"):
                    try:
                        loaded = _pd_instance_config(node.get("instance"))
                        if loaded:
                            node["config"] = _pd_config_sanitize(loaded)
                    except Exception:  # noqa: BLE001
                        pass
                if "_contract" not in node:
                    try:
                        contract = _pd_contract_for_node(node, parent, key, get_core)
                        if contract:
                            node["_contract"] = contract
                    except Exception:  # noqa: BLE001
                        pass
                # Port TYPE schemas: a hand-authored composite node (e.g. the
                # colony's `ecoli`/`multibody`) carries only wiring, not port
                # types, so the card/inspector show port names with no type. When
                # `_inputs`/`_outputs` are absent, read them off a lightweight
                # instance of the process class (inputs()/outputs() return the
                # declared type map). Guarded + only-when-absent, so instantiated
                # docs and processes that already ship `_inputs` are untouched.
                if not node.get("_inputs") or not node.get("_outputs"):
                    try:
                        pcls = _pd_class_for_address(addr)
                        if pcls is None and get_core is not None:
                            pcls = _class_for_address(addr, get_core())
                        if pcls is not None:
                            pcore = get_core() if get_core is not None else None
                            inst = pcls(node.get("config") or {}, pcore)
                            if not node.get("_inputs"):
                                pi = inst.inputs() if hasattr(inst, "inputs") else None
                                if isinstance(pi, dict):
                                    node["_inputs"] = pi
                            if not node.get("_outputs"):
                                po = inst.outputs() if hasattr(inst, "outputs") else None
                                if isinstance(po, dict):
                                    node["_outputs"] = po
                    except Exception:  # noqa: BLE001
                        pass
            for k, v in node.items():
                walk(v, node, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, parent, key)

    try:
        walk(doc)
    except Exception:  # noqa: BLE001
        pass
    return doc


def _lazy_core_for_ref(ref):
    """Zero-arg callable building generator ``ref``'s core from its
    ``core_extensions`` (which register the composite's local process classes,
    e.g. ``EcoliWCM``), or ``None`` when ``ref`` is falsy/unregistered.

    Lazily built + cached, so a doc with no bare registry-name address never
    pays for a core. Mirrors the ``_get_core`` closure the live-build method
    already uses — it exists so the *attach* path can resolve bare addresses
    (``local:EcoliWCM``) on a committed-artifact doc that was NOT live-built."""
    if not ref:
        return None
    try:
        from viva_superpowers.composite_generator import (
            _REGISTRY, apply_core_extensions, discover_generators,
        )
    except Exception:  # noqa: BLE001
        return None
    _import_workspace_package(_workspace)
    if not _REGISTRY:
        try:
            discover_generators()
        except Exception:  # noqa: BLE001
            return None
    entry = _REGISTRY.get(ref)
    if entry is None:
        return None
    _core_cache: dict = {}

    def _get_core():
        if "c" not in _core_cache:
            try:
                from bigraph_schema import allocate_core
                _core_cache["c"] = apply_core_extensions(entry, allocate_core())
            except Exception:  # noqa: BLE001
                _core_cache["c"] = None
        return _core_cache["c"]

    return _get_core


def _attach_process_docs_method(params: dict) -> dict:
    """Attach per-process docstrings to an already-resolved state ``document``
    passed inline (spec §11 ``{document}``). Read-shaped: the workbench owns the
    science file, hands us the doc, and we import the process classes to read
    their descriptions — so the HTTP process imports no workspace Python for the
    composite-state static-fallback / spec branches.

    When a generator ``ref`` is supplied, a lazy core is built from its
    ``core_extensions`` so bare registry-name addresses (``local:EcoliWCM``)
    resolve for Composite-Process flagging + port-type reads. Without it the
    committed-artifact resolve path (``GET /api/composite-resolve`` serving
    ``reports/composite-state/<id>.json``) never sets ``is_composite_process``,
    so the Explorer's inner-composite drill-in mini-map silently disappears —
    even though the live-built study path shows it."""
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    p = params or {}
    get_core = _lazy_core_for_ref(p.get("ref"))
    return {"document": _attach_process_docs(p.get("document"), get_core=get_core)}


def _render_port_schemas(doc):
    """Serialize each process/step port TYPE to its bigraph type-name form.

    A process may declare a port type as a bigraph type OBJECT (e.g. division's
    ``inputs()`` returns ``InPlaceDict()``); left as-is it JSON-serializes to a
    Python class repr (``InPlaceDict(_default=None, _value=Node(_default=None))``).
    Running each ``_inputs``/``_outputs`` value through ``render`` turns a type
    object into its registered NAME (``inplace_dict``, ``float``, ``overwrite[…]``)
    — the same clean form processes that authored string types already emit.
    Best-effort: an older bigraph-schema or an unrenderable value is left alone.
    """
    try:
        from bigraph_schema.methods.serialize import render
        from bigraph_schema.schema import Node
    except Exception:  # noqa: BLE001
        return

    def conv(v):
        if isinstance(v, Node):
            try:
                return render(v)
            except Exception:  # noqa: BLE001
                return str(v)
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v

    def walk(node):
        if isinstance(node, dict):
            if node.get("_type") in ("process", "step"):
                for key in ("_inputs", "_outputs"):
                    if isinstance(node.get(key), dict):
                        node[key] = {p: conv(t) for p, t in node[key].items()}
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    try:
        walk(doc)
    except Exception:  # noqa: BLE001
        pass


def _resolve_composite_state(params: dict) -> dict:
    """Build a ``@composite_generator``'s state (spec §11), summarized +
    doc-decorated. A faithful in-worker port of
    ``composite_state_views.composite_state_via_subprocess``'s embedded script —
    which ran under ``sys.executable``; now it runs on the workspace's own
    interpreter. Returns ``{state, module, emitters}`` on success,
    ``{__build_error__, emitters}`` if the build raised, ``{__not_registered__}``
    if ``ref`` is not a registered generator."""
    ref = (params or {}).get("ref")
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    # Import the workspace's own package so its @composite_generators register
    # (discover_generators alone won't import a non-installed workspace package —
    # same priming _list_generators does).
    _import_workspace_package(_workspace)
    out: dict = {"__not_registered__": True}
    try:
        from viva_superpowers.composite_generator import (
            _REGISTRY, apply_core_extensions, build_generator,
            discover_generators, emitter_defaults,
        )
        if not _REGISTRY:
            discover_generators()
        entry = _REGISTRY.get(ref)
        if entry is not None:
            # Parameter overrides (from the Explore Config panel's Apply) — build
            # the generator WITH them so the wiring reflects the edited config
            # (e.g. n_cells=1 → one cell). Filter to declared params so a stray
            # key can't make build_generator raise.
            _raw_ov = (params or {}).get("overrides") or {}
            overrides = ({k: v for k, v in _raw_ov.items() if k in (entry.parameters or {})}
                         if isinstance(_raw_ov, dict) else {})
            try:
                declared_emitters = emitter_defaults(entry)
            except Exception:  # noqa: BLE001
                declared_emitters = []
            # Lazy: only built if a bare registry-name address needs class
            # resolution for Composite-Process flagging (see _attach_process_docs).
            _core_cache: dict = {}

            def _get_core():
                if "c" not in _core_cache:
                    try:
                        from bigraph_schema import allocate_core
                        _core_cache["c"] = apply_core_extensions(entry, allocate_core())
                    except Exception:  # noqa: BLE001
                        _core_cache["c"] = None
                return _core_cache["c"]

            try:
                doc = build_generator(entry, overrides or None)
                doc = _summarize_large_values(doc)
                _attach_process_docs(doc, get_core=_get_core)
                _render_port_schemas(doc)
                out = {"state": doc, "module": getattr(entry, "module", None),
                       "emitters": declared_emitters}
            except Exception as e:  # noqa: BLE001
                out = {"__build_error__": str(e), "emitters": declared_emitters}
    except Exception as e:  # noqa: BLE001
        out = {"__build_error__": str(e)}
    return out


def _resolve_inner_composite_state(params: dict) -> dict:
    """Drill into a Composite Process: return the loom state of the inner
    ``Composite`` embedded at ``hops`` under generator ``ref``.

    ``params`` = ``{ref, hops}`` where ``hops`` is a list of node paths (each a
    list of key segments, as ``convert.ts`` emits), one per drill level. The
    root generator is instantiated (``apply_core_extensions`` → ``build_generator``
    → ``Composite``); for each hop we navigate to that node's live instance, take
    its inner composite (``_inner_composite_of`` — ``inner_composite()`` /
    ``Composite`` self / wrapped attr), and recurse. The final inner composite's
    ``state`` is summarized + doc-decorated (its own Composite Processes flagged,
    so drilling continues all the way down) and returned as ``{state, crumbs}``.

    Returns ``{__not_registered__}`` (bad ref), ``{__error__}`` (bad hop / not a
    composite process), or ``{__build_error__}`` (instantiation raised)."""
    ref = (params or {}).get("ref")
    hops = (params or {}).get("hops") or []
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    _import_workspace_package(_workspace)
    try:
        from viva_superpowers.composite_generator import (
            _REGISTRY, apply_core_extensions, build_generator, discover_generators,
        )
        from bigraph_schema import allocate_core
        from process_bigraph import Composite
    except Exception as e:  # noqa: BLE001
        return {"__build_error__": str(e)}
    if not _REGISTRY:
        try:
            discover_generators()
        except Exception:  # noqa: BLE001
            pass
    entry = _REGISTRY.get(ref)
    if entry is None:
        return {"__not_registered__": True}
    try:
        core = apply_core_extensions(entry, allocate_core())
        doc = build_generator(entry, core=core)
        state = doc["state"] if isinstance(doc, dict) and "state" in doc else doc
        cur = Composite({"state": state}, core=core)
        crumbs: list = []
        for hop in hops:
            node = _nav_state(cur.state, hop)
            if not isinstance(node, dict):
                return {"__error__": f"path not found: {hop}"}
            inner = _inner_composite_of(node.get("instance"))
            if inner is None:
                return {"__error__": f"not a composite process: {hop}"}
            crumbs.append(hop[-1] if hop else "?")
            cur = inner
        inner_doc = _summarize_large_values(cur.state)
        icore = getattr(cur, "core", None) or core
        _attach_process_docs(inner_doc, get_core=lambda: icore)
        _render_port_schemas(inner_doc)
        return {"state": inner_doc, "crumbs": crumbs}
    except Exception as e:  # noqa: BLE001
        return {"__build_error__": str(e)}


# --- observables (spec §11): build + available_observables + validate, all
#     in-worker (available_observables/validate_readouts need the live core +
#     polars, which live here). The workbench owns spec-file resolution and hands
#     us either a generator `ref` or an inline resolved `{state, schema}`. --------
_OBS_LINEAGE_AGENT_RE = None  # compiled lazily (re import kept local to workers)


def _obs_resolve_registry_ref(ref: str, keys):
    """Resolve a short composite ``ref`` to a canonical registry key by matching
    the trailing ``.composites.<slug>`` segment (else the last dotted segment),
    preferring the shortest match. Port of
    observables_views._resolve_registry_ref."""
    keys = list(keys)
    if ref in keys:
        return ref
    def tail(k):
        return k.rsplit(".composites.", 1)[-1] if ".composites." in k else k.rsplit(".", 1)[-1]
    rt = tail(ref)
    matches = [k for k in keys if tail(k) == rt]
    return min(matches, key=len) if matches else None


def _obs_augment_lineage_aliases(available: dict) -> dict:
    """Strip a leading ``agents.<n>.`` from every leaf/catalog key and add the
    remainder as an alias (whole-cell composites nest the cell under
    ``agents.<n>.`` but studies author bare single-cell paths). Only a leading
    ``agents.<n>.`` is stripped, never an arbitrary suffix, so a genuinely-absent
    observable still fails to match. Port of
    observables_views.augment_lineage_aliases (the agent-structure convention
    lives in the dashboard worker, not the general validator)."""
    import re
    global _OBS_LINEAGE_AGENT_RE
    if _OBS_LINEAGE_AGENT_RE is None:
        _OBS_LINEAGE_AGENT_RE = re.compile(r"^agents\.\d+\.(.+)$")
    leaves = list(available.get("leaves", []) or [])
    catalogs = dict(available.get("catalogs", {}) or {})
    seen = set(leaves)
    extra = []
    for leaf in leaves:
        m = _OBS_LINEAGE_AGENT_RE.match(leaf)
        if m and m.group(1) not in seen:
            extra.append(m.group(1))
            seen.add(m.group(1))
    for key, val in list(catalogs.items()):
        m = _OBS_LINEAGE_AGENT_RE.match(key)
        if m:
            catalogs.setdefault(m.group(1), val)
    return {"leaves": leaves + extra, "catalogs": catalogs}


def _obs_build_core():
    """Best-effort workspace ``build_core()`` for LabeledArray catalog resolution
    — tolerated if it fails (None; only static catalogs degrade)."""
    try:
        package_name, _pkgs, _ws = _workspace_meta(_workspace)
        mod = __import__(f"{package_name}.core", fromlist=["build_core"])
        return mod.build_core()
    except Exception:  # noqa: BLE001
        return None


def _obs_available(params: dict) -> dict:
    """Compute ``available_observables`` for a composite named by ``ref`` (a
    registered generator) OR given inline as ``{state, schema}`` (a resolved spec
    doc the workbench parsed). Returns ``{leaves, catalogs}`` on success, else a
    sentinel: ``{__no_validator__}`` / ``{__not_registered__}`` / ``{__build_error__}``
    / ``{__introspect_error__}``. Faithful to
    observables_views.build_composite_state_for_observables + available_observables."""
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    _import_workspace_package(_workspace)
    try:
        from viva_superpowers.readout_validation import available_observables
    except Exception as e:  # noqa: BLE001
        return {"__no_validator__": str(e)}

    core = _obs_build_core()
    ref = (params or {}).get("ref")
    if ref is not None:
        # Generator branch: resolve via the live registry (+ short-ref alias).
        entry = None
        apply_core_extensions = None
        build_generator = None
        try:
            from viva_superpowers.composite_generator import (
                _REGISTRY,
                apply_core_extensions as _ace,
                build_generator as _bg,
                discover_generators,
            )
            apply_core_extensions, build_generator = _ace, _bg
            if not _REGISTRY:
                try:
                    discover_generators()
                except Exception:  # noqa: BLE001
                    pass
            entry = _REGISTRY.get(ref)
            if entry is None:
                canon = _obs_resolve_registry_ref(ref, _REGISTRY.keys())
                if canon is not None:
                    entry = _REGISTRY.get(canon)
        except ImportError:
            entry = None
        if entry is None:
            return {"__not_registered__": True}
        if core is not None and apply_core_extensions is not None:
            try:
                core = apply_core_extensions(entry, core)
            except Exception:  # noqa: BLE001
                pass
        try:
            doc = build_generator(entry, core=core)
        except Exception as e:  # noqa: BLE001
            return {"__build_error__": f"generator build failed: {e}"}
        if isinstance(doc, dict) and isinstance(doc.get("state"), dict):
            state, schema = doc["state"], doc.get("schema")
        else:
            state, schema = doc, None
    else:
        # Static branch: the workbench already resolved the spec file.
        state = (params or {}).get("state")
        schema = (params or {}).get("schema")

    try:
        available = available_observables(core, state, schema)
    except Exception as e:  # noqa: BLE001
        return {"__introspect_error__": f"observable introspection failed: {e}"}
    return {"leaves": available.get("leaves", []) or [],
            "catalogs": available.get("catalogs", {}) or {}}


def _observables(params: dict) -> dict:
    """``{ref}`` or ``{state, schema}`` → ``{leaves, catalogs}`` (or a sentinel)."""
    return _obs_available(params)


def _study_readout_check(params: dict) -> dict:
    """Validate a study's readouts against its composite's real structure
    (never-fabricate guard). Params carry the study ``spec`` inline plus the
    composite as ``ref`` or ``{state, schema}``. Returns ``{readouts}`` on
    success, else a sentinel (``__not_registered__`` / ``__build_error__`` /
    ``__no_validator__`` / ``__validate_error__``)."""
    spec = (params or {}).get("spec") or {}
    avail = _obs_available(params)
    if any(k.startswith("__") for k in avail):
        return avail  # not_registered / build_error / no_validator / introspect_error
    try:
        from viva_superpowers.readout_validation import validate_readouts
    except Exception as e:  # noqa: BLE001
        return {"__no_validator__": str(e)}
    try:
        augmented = _obs_augment_lineage_aliases(avail)
        results = validate_readouts(spec, available=augmented)
    except Exception as e:  # noqa: BLE001
        return {"__validate_error__": f"readout validation failed: {e}"}
    return {"readouts": results}


def _composites_full() -> dict:
    """The full ``GET /api/composites`` payload (``{"composites": [...]}``) built
    in the WARM pooled worker, so the workspace package + build_core imports are
    paid ONCE and reused — instead of a fresh per-request subprocess that
    re-imports everything (~8s cold, and the source of the recurring CI timeout).
    Best-effort; a build failure returns ``{"composites": [], "error": ...}``."""
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    _import_workspace_package(_workspace)
    try:
        from pathlib import Path as _Path
        from vivarium_workbench.lib.composite_lookup import composites_data
        return composites_data(_Path(_workspace))
    except Exception as e:  # noqa: BLE001
        return {"composites": [], "error": f"composites_data failed: {e}"}


def _discover_composites() -> dict:
    """Generator composite entries for this environment (spec §11).

    Imports the workspace package + runs viva_superpowers generator discovery in
    THIS process, returning the raw ``{gid: entry}`` **generator** half as JSON
    (the workbench keeps its pure FS/YAML spec scan + dedup and merges these in).
    So the HTTP process no longer imports/executes ``@composite_generator``
    modules to build `discover_all_composites` / `known_composite_ids`."""
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    _import_workspace_package(_workspace)

    reg_keys: list = []
    try:
        from viva_superpowers.composite_generator import _REGISTRY, discover_generators
        if not _REGISTRY:
            try:
                discover_generators()
            except Exception:  # noqa: BLE001
                pass
        reg_keys = list(_REGISTRY.keys())
    except Exception:  # noqa: BLE001
        pass

    out: dict = {}
    try:
        from viva_superpowers.composite_discovery import discover_all
        merged = discover_all() or {}
    except Exception:  # noqa: BLE001 — no generator discovery available → spec-only
        merged = {}
    for gid, entry in merged.items():
        if isinstance(entry, dict) and entry.get("kind") == "generator":
            out[gid] = {
                "name": entry.get("name"),
                "description": entry.get("description", ""),
                "parameters": entry.get("parameters") or {},
                "module": entry.get("module"),
                "default_n_steps": entry.get("default_n_steps"),
                "visualizations": list(entry.get("visualizations") or []),
            }
    # Belt-and-suspenders: any registry key discover_all missed (mirrors the old
    # known_composite_ids direct-registry union).
    for gid in reg_keys:
        out.setdefault(gid, {"name": None, "description": "", "parameters": {},
                             "module": None, "default_n_steps": None, "visualizations": []})
    return {"generators": out}


def _validate_generated_visualization(params: dict) -> dict:
    """Smoke-test a just-accepted generated visualization module (spec §11), in
    the workspace's env (import-verify → `build_core()` → class discovery) — the
    write-path equivalent of the old in-process ``visualization_accept`` verify.
    A warm worker may already hold the module, so **reload** it (picks up an edit).
    Returns ``{"ok": True}`` or a structured ``{"error", "code"}`` (import_failed /
    build_core_failed / class_not_found) — the workbench maps ``error`` to a 500."""
    import importlib

    pkg = (params or {}).get("pkg") or ""
    snake = (params or {}).get("module") or ""
    class_name = (params or {}).get("class_name") or ""
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)

    mod_name = f"{pkg}.visualizations.{snake}"
    try:
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
        else:
            __import__(mod_name)
        pkg_viz_mod = f"{pkg}.visualizations"
        if pkg_viz_mod in sys.modules:
            importlib.reload(sys.modules[pkg_viz_mod])
    except Exception as e:  # noqa: BLE001
        return {"error": f"generated file failed to import: {type(e).__name__}: {e}",
                "code": "import_failed"}

    # Invalidate the cached base core so build_core re-walks the new module.
    try:
        import bigraph_schema.core as _bsc
        _bsc._cached_base_core = None
    except Exception:  # noqa: BLE001
        pass
    try:
        core_module = __import__(f"{pkg}.core", fromlist=["build_core"])
        core_module.build_core()
    except Exception as e:  # noqa: BLE001
        return {"error": ("workspace build_core() failed after importing the generated "
                          f"file: {type(e).__name__}: {e}"), "code": "build_core_failed"}

    if class_name:
        found = False
        mod = sys.modules.get(mod_name)
        if mod is not None:
            for attr_val in vars(mod).values():
                if not isinstance(attr_val, type):
                    continue
                if getattr(attr_val, "__name__", None) != class_name:
                    continue
                marker = getattr(attr_val, "is_visualization", None)
                if callable(marker):
                    try:
                        if marker() is True:
                            found = True
                            break
                    except Exception:  # noqa: BLE001
                        pass
                if not found:
                    try:
                        from viva_superpowers.visualization import Visualization as _VizBase
                        if issubclass(attr_val, _VizBase) and attr_val is not _VizBase:
                            found = True
                            break
                    except ImportError:
                        pass
        if not found:
            return {"error": (f"class {class_name!r} not found in generated file after "
                              "import; check the @as_visualization name= argument matches"),
                    "code": "class_not_found"}
    return {"ok": True}


def _run_study_analyses(params: dict) -> dict:
    """Run a study's ``spec.analyses`` over its parquet output, in the workspace
    env (v2ecoli ``ANALYSIS_REGISTRY`` scale lookup + ``run_analyses``). Returns
    ``{"written": [paths], "errors": [dicts]}`` — never raises. Faithful port of
    ``study_run_post.build_analysis_options`` + the v2ecoli half of
    ``run_study_analyses``; the workbench keeps the parquet/sim_data path
    resolution."""
    import time
    import traceback
    from pathlib import Path

    p = params or {}
    entries = list(p.get("entries") or [])
    sweep_dir = p.get("sweep_dir")
    sim_data_path = p.get("sim_data_path")
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    _import_workspace_package(_workspace)
    if not entries:
        return {"written": [], "errors": []}

    # 1. build_analysis_options: map entries → {scale: {name: params}} via the registry.
    try:
        from v2ecoli.workflow.analysis import ANALYSIS_REGISTRY
    except ImportError:
        return {"written": [], "errors": [
            {"error": "v2ecoli not installed; cannot resolve analysis scales"}]}
    analysis_options: dict = {}
    build_errors: list = []
    for entry in entries:
        name = entry.get("name")
        if not name:
            continue
        step_cls = ANALYSIS_REGISTRY.get(name)
        if step_cls is None:
            build_errors.append({"analysis": name,
                                 "error": f"unknown analysis {name!r} (not in ANALYSIS_REGISTRY)"})
            continue
        scale = getattr(step_cls, "scale", None)
        if not scale:
            build_errors.append({"analysis": name,
                                 "error": f"analysis {name!r} has no scale attribute"})
            continue
        analysis_options.setdefault(scale, {})[name] = entry.get("params") or {}
    if not analysis_options:
        return {"written": [], "errors": build_errors}

    # 2. Run the analyses + collect written files (mtime newer than call start).
    try:
        import v2ecoli.workflow.analyses  # noqa: F401 — register analysis ports
        from v2ecoli.workflow.analysis_runner import run_analyses
        t_start = time.time()
        results = run_analyses(str(sweep_dir), analysis_options, sim_data_path=sim_data_path)
        written: list = []
        sd = Path(sweep_dir)
        for sub in ("ptools", "viz"):
            sub_dir = sd / sub
            if sub_dir.is_dir():
                for f in sub_dir.iterdir():
                    if f.is_file() and f.stat().st_mtime >= t_start:
                        written.append(str(f))
        analysis_json = sd / "analysis.json"
        if analysis_json.is_file() and analysis_json.stat().st_mtime >= t_start:
            written.append(str(analysis_json))
        errors = list(build_errors)
        for scale_results in results.values():
            for aname, groups in (scale_results or {}).items():
                for gstr, val in (groups or {}).items():
                    if isinstance(val, dict) and "error" in val:
                        errors.append({"analysis": aname, "group": gstr, "error": val["error"]})
        return {"written": written, "errors": errors}
    except Exception as exc:  # noqa: BLE001 — never crash the run
        return {"written": [], "errors": [
            {"error": f"_run_study_analyses failed: {type(exc).__name__}: {exc}",
             "traceback": traceback.format_exc()}]}


# --- viz rendering (spec §11): build_core + viz-class registration + Composite.run
#     all in-worker (live viz classes + core can't cross the socket). Cached per
#     worker — build_core is ~15s and every viz render reuses it. --------------
_VIZ_CORE = None  # (core, registry) once built


def _build_viz_core():
    """Build the workspace core + register every Visualization class onto it
    (viva_superpowers defaults + the whole Visualization subclass tree), cached per
    worker. Faithful port of study_run_post.render_study_visualizations' in-process
    core+registry build. Returns ``(core, registry_dict)``."""
    global _VIZ_CORE
    if _VIZ_CORE is not None:
        return _VIZ_CORE
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    package_name, _pkgs, _ws = _workspace_meta(_workspace)
    core_module = __import__(f"{package_name}.core", fromlist=["build_core"])
    core = core_module.build_core()
    registry = dict(core.link_registry)

    try:
        from viva_superpowers.visualizations import (
            Distribution, Heatmap, ParamVsObservable, PhaseSpace, TimeSeriesPlot,
        )
        for cls in (TimeSeriesPlot, ParamVsObservable, Distribution, PhaseSpace, Heatmap):
            core.register_link(cls.__name__, cls)
            registry[cls.__name__] = cls
    except ImportError:
        pass

    try:
        from viva_superpowers.composite_generator import discover_generators
        from viva_superpowers.visualization import Visualization
        discover_generators()  # force-load packages so @Visualization classes appear

        def _walk(cls):
            for sub in cls.__subclasses__():
                yield sub
                yield from _walk(sub)
        for sub in _walk(Visualization):
            if sub.__name__ in registry:
                continue
            try:
                core.register_link(sub.__name__, sub)
                registry[sub.__name__] = sub
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001 — discovery is best-effort
        pass

    _VIZ_CORE = (core, registry)
    return _VIZ_CORE


def _viz_class_inputs() -> dict:
    """``{class_name: declared_inputs}`` for every registered class (spec §11), so
    the workbench's ``build_viz_composite`` can assemble viz docs without holding
    the live class objects. Presence in the map == 'registered'."""
    _core, registry = _build_viz_core()
    out: dict = {}
    for name, cls in registry.items():
        try:
            inp = cls.__new__(cls).inputs()
            out[name] = inp if isinstance(inp, dict) else {}
        except Exception:  # noqa: BLE001
            out[name] = {}
    return {"inputs": out}


def _render_viz_doc(params: dict) -> dict:
    """Render ONE viz composite doc → HTML: ``Composite({'state': doc}, core).run(1)``
    against the cached viz core, extracting ``output_store`` (spec §11). Faithful
    port of the old in-process ``build_and_run`` hook."""
    viz_doc = (params or {}).get("viz_doc")
    core, _registry = _build_viz_core()
    from process_bigraph import Composite
    composite = Composite({"state": viz_doc}, core=core)
    composite.run(1)
    state = composite.state
    html = state.get("output_store")
    if isinstance(html, dict):
        html = html.get("value") or html.get("_value") or ""
    return {"html": html if isinstance(html, str) else ""}


# Synthetic demo states for the 5 built-in viva_superpowers Visualization classes
# (byte-identical to lib.viz_core.BUILTIN_VIZ_DEMOS). Used when previewing a viz
# without real run data, or as a fallback when investigation data is incompatible.
_BUILTIN_VIZ_DEMOS: dict = {
    "TimeSeriesPlot": {
        "observable": [
            [1.0, 1.4, 2.1, 3.0, 4.2, 5.7, 7.1, 8.0, 8.3, 8.4],
            [2.0, 2.6, 3.5, 4.6, 5.9, 7.3, 8.5, 9.1, 9.3, 9.3],
            [0.5, 0.7, 1.1, 1.7, 2.5, 3.5, 4.6, 5.5, 6.1, 6.4],
        ],
        "time": [
            [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5],
            [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5],
            [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5],
        ],
        "_run_labels": ["rate=1.0", "rate=2.0", "rate=0.5"],
    },
    "ParamVsObservable": {
        "sweep_param_values": [0.1, 0.5, 1.0, 2.0, 5.0],
        "reduced_observable": [3.0, 7.5, 12.0, 17.5, 21.0],
    },
    "Distribution": {
        "samples": [
            10.0, 10.3, 10.1, 10.6, 10.4, 10.2, 10.5, 10.9, 10.7, 10.4,
            10.8, 10.3, 10.5, 11.0, 10.6, 10.2, 10.4, 10.7, 10.5, 10.8,
        ],
    },
    "PhaseSpace": {
        "x": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0, 2.0, 1.0],
        "y": [0.0, 0.8, 1.5, 1.8, 1.5, 0.8, 0.0, -0.8, -1.5, -0.8],
    },
    "Heatmap": {
        "x_params": [0.1, 0.5, 1.0, 2.0, 5.0],
        "y_params": [10.0, 20.0, 30.0],
        "z_values": [
            [1.0, 2.0, 3.0, 4.0, 5.0],
            [2.0, 4.0, 6.0, 8.0, 10.0],
            [3.0, 6.0, 9.0, 12.0, 15.0],
        ],
    },
}


def _demo_state_for(cls, class_key: str) -> dict:
    """Synthetic state dict for previewing ``cls`` (byte-identical to
    lib.viz_core.demo_state_for). Priority: ``cls.demo()`` classmethod →
    built-in demo map → empty dict."""
    if hasattr(cls, "demo") and callable(getattr(cls, "demo")):
        try:
            state = cls.demo()
            if isinstance(state, dict):
                return state
        except Exception:  # noqa: BLE001
            pass
    return dict(_BUILTIN_VIZ_DEMOS.get(class_key, {}))


def _viz_preview(params: dict) -> dict:
    """Render a Visualization class to preview HTML entirely in the worker (spec §11).

    Faithful port of the class-touching half of ``viz_preview_views.visualization_preview``
    + ``viz_core.resolve_viz_class``/``demo_state_for``: resolve the class off the cached
    viz core, then render via a bare-instance ``.update()`` — demo (single update),
    streaming (12 synthetic scalar timesteps), or investigation (an ``inputs_store``
    already assembled HTTP-side by ``build_viz_composite``, since that is workbench code).

    ``params``: ``{address, config, source, investigation_inputs_store?, note_prefix?}``.
    Returns ``{"status": "not_registered"}`` (the workbench maps it to 404) OR
    ``{"ok", "html", "source_used", "notes"}`` — mirroring the old in-process contract
    where only validation is non-200 and every render outcome (including a raise) is a
    200 body."""
    p = params or {}
    address = p.get("address") or ""
    config = p.get("config") or {}
    source = p.get("source") or "demo"
    inv_inputs_store = p.get("investigation_inputs_store")
    notes = list(p.get("note_prefix") or [])

    # Resolve the class off the cached viz core (viva_superpowers builtins + the
    # workspace Visualization subclass tree). Presence in the registry == registered.
    core, registry = _build_viz_core()
    raw_key = address.split(":", 1)[1] if ":" in address else address
    short = raw_key.rsplit(".", 1)[-1]
    cls = None
    for key in (raw_key, short):
        cls = registry.get(key)
        if cls is not None:
            break
    if cls is None:
        return {"status": "not_registered"}
    class_key = short  # match viz_core.resolve_viz_class's returned short name

    # Investigation source first (its inputs_store is built HTTP-side).
    if source.startswith("investigation:") and inv_inputs_store is not None:
        inv_name = source.split(":", 1)[1].strip()
        try:
            inst = cls.__new__(cls)
            inst.config = config or {}
            html = inst.update(dict(inv_inputs_store)).get("html", "")
            if html:
                return {"ok": True, "html": html,
                        "source_used": f"investigation:{inv_name}",
                        "notes": "; ".join(notes)}
            notes.append("investigation render produced empty html; falling back to demo")
        except Exception as e:  # noqa: BLE001
            notes.append(f"investigation render failed ({type(e).__name__}: {e}); falling back to demo")

    # Demo path (default or fallback).
    try:
        state = _demo_state_for(cls, class_key)

        # Streaming-style viz (all inputs scalar) get N synthetic timesteps fed
        # through the accumulator; list-input classes render in one update().
        scalar_types = {"float", "integer", "string", "boolean"}
        probe = cls.__new__(cls)
        try:
            probe.config = config or {}
        except Exception:  # noqa: BLE001
            pass
        declared: dict = {}
        try:
            declared = probe.inputs() or {}
        except Exception:  # noqa: BLE001
            pass
        is_streaming = (
            bool(declared)
            and all(t in scalar_types for t in declared.values())
            and not state
        )

        inst = None
        if is_streaming:
            # Streaming viz usually need __init__ to build accumulator buffers;
            # try a real constructor with the workspace core, else allocate_core,
            # else a bare instance.
            ctor_core = core
            if ctor_core is None:
                try:
                    from bigraph_schema import allocate_core
                    ctor_core = allocate_core()
                except Exception:  # noqa: BLE001
                    ctor_core = None
            for ctor_args in (
                {"config": config or {}, "core": ctor_core},
                {"config": config or {}},
            ):
                try:
                    inst = cls(**ctor_args)
                    break
                except Exception:  # noqa: BLE001
                    continue
        if inst is None:
            inst = cls.__new__(cls)
            try:
                inst.config = config or {}
            except Exception:  # noqa: BLE001
                pass

        if is_streaming:
            import math
            html = ""
            for step in range(12):
                synth: dict = {}
                for port, port_type in declared.items():
                    if port_type == "float":
                        if port in ("time", "t"):
                            synth[port] = float(step) * 0.5
                        else:
                            phase = (hash(port) & 0xff) / 40.0
                            synth[port] = 1.0 + 0.5 * math.sin(step * 0.6 + phase) + step * 0.1
                    elif port_type == "integer":
                        synth[port] = int(50 + step * 7)
                    elif port_type == "boolean":
                        synth[port] = step % 2 == 0
                    else:
                        synth[port] = f"step-{step}"
                result = inst.update(synth) or {}
                html = result.get("html", "") or html
        else:
            html = inst.update(state).get("html", "")

        if not html:
            html = (
                f'<div style="padding:20px;font-family:system-ui">'
                f'<p><strong>{class_key}</strong>: no demo state available.</p>'
                f'<p style="color:#666">Add a <code>demo()</code> classmethod to '
                f'the viz class, or register an instance in workspace.yaml and '
                f'use the Preview button on the instance row to render against '
                f'real emitter data.</p></div>'
            )
        return {"ok": True, "html": html, "source_used": "demo",
                "notes": "; ".join(notes)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False,
                "html": f'<p style="color:#991b1b">demo render failed: {type(e).__name__}: {e}</p>',
                "source_used": "demo", "notes": "; ".join(notes)}


def _report_core_snapshot(params: dict) -> dict:
    """Registry snapshot (process/type names) + the workspace document for the
    report render (spec §11) — imports ``<pkg>.core`` (registry_snapshot) +
    ``<pkg>.document`` (build_document) in the worker. Faithful port of
    report._load_registry + _load_document. Returns finite JSON."""
    package_path = (params or {}).get("package_path")
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)

    registry = {"processes": [], "types": []}
    warning = None
    if package_path:
        try:
            core = __import__(f"{package_path}.core", fromlist=["build_core"])
            build_core = getattr(core, "build_core", None)
            registry_snapshot = getattr(core, "registry_snapshot", None)
            if build_core is None or registry_snapshot is None:
                warning = (f"{package_path}.core imported but missing build_core() or "
                           "registry_snapshot().")
            else:
                build_core()
                snap = registry_snapshot()

                def _names(items):
                    if not items:
                        return []
                    if isinstance(items[0], str):
                        return list(items)
                    return [it.get("name", str(it)) for it in items]
                registry = {"processes": _names(snap.get("processes", [])),
                            "types": _names(snap.get("types", []))}
        except ModuleNotFoundError:
            warning = (f"Package '{package_path}' is not importable — registry shown as "
                       "empty. Install it in the workspace venv or run /pbg-pull-processes.")
        except Exception as exc:  # noqa: BLE001
            warning = f"{package_path}.core raised {type(exc).__name__}: {exc}"

    document: dict = {}
    if package_path:
        try:
            doc_mod = __import__(f"{package_path}.document", fromlist=["build_document"])
            build_document = getattr(doc_mod, "build_document", None)
            if build_document is not None:
                document = build_document() or {}
        except Exception:  # noqa: BLE001
            document = {}

    return {"registry": registry, "registry_warning": warning, "document": document}


def _reexport_map(params: dict) -> dict:
    """Map re-exported classes → the allow-listed package that re-exports them
    (spec §11) — imports each allow-listed package + scans its namespace in the
    worker. Faithful port of registry._build_reexport_map."""
    import importlib
    import inspect

    include = set((params or {}).get("include") or [])
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    framework = {"process_bigraph", "bigraph_schema", "bigraph_viz",
                 "viva_superpowers", "vivarium_workbench"}
    reexports: dict = {}
    for pkg in sorted(include):
        try:
            mod = importlib.import_module(pkg)
        except Exception:  # noqa: BLE001
            continue
        for attr in dir(mod):
            try:
                obj = getattr(mod, attr)
            except Exception:  # noqa: BLE001
                continue
            if not inspect.isclass(obj):
                continue
            def_mod = getattr(obj, "__module__", "") or ""
            def_top = def_mod.split(".")[0].replace("-", "_")
            if not def_top or def_top == pkg:
                continue
            if def_top in include or def_top in framework:
                continue
            qualname = getattr(obj, "__qualname__", attr) or attr
            reexports[f"{def_mod}.{qualname}"] = pkg
            reexports[f"{def_top}::{qualname}"] = pkg
    return {"reexports": reexports}


def _data_sources_provider(params: dict) -> dict:
    """Import + invoke the workspace's ``dashboard.data_sources`` provider (spec §11)
    — a ``module:func`` spec that usually resolves into the workspace's own package,
    so the import must not run in the HTTP process. Faithful port of
    ``data_sources.import_provider`` + the ``fn()`` call.

    Returns ``{"rows": [...], "error": None}`` on success, else ``{"rows": [],
    "error": "TypeName: msg"}`` — the worker CATCHES the provider exception (rather
    than raising) so the workbench reproduces the old in-process
    ``{"sources": [], "error": ...}`` degrade verbatim."""
    import importlib

    spec = str((params or {}).get("provider") or "").strip()
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    try:
        if ":" not in spec:
            raise ValueError(f"provider must be 'module:func', got {spec!r}")
        mod_name, _, func_name = spec.partition(":")
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, func_name)
        if not callable(fn):
            raise TypeError(f"provider {spec!r} is not callable")
        rows = list(fn() or [])
        return {"rows": rows, "error": None}
    except Exception as e:  # noqa: BLE001 — degrade, never crash the dashboard
        return {"rows": [], "error": f"{type(e).__name__}: {e}"}


# --- analysis viewers (spec §11): discover + launch repo-contributed viewers ----
#     A workspace/pbg-* package MAY expose a ``workbench_viewers`` module with
#     ``get_viewers(ws_root) -> [dict]`` (callables for applies/launch/targets).
#     Discovery, predicate evaluation, target resolution, and launch all touch the
#     contributor's live callables, so they run here; only JSON-safe descriptors +
#     launch-result dicts cross the socket. Faithful port of lib.analysis_viewers.


def _av_workspace_package(ws_root) -> str:
    import yaml as _yaml
    try:
        ws_data = _yaml.safe_load((ws_root / "workspace.yaml").read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return ""
    return ws_data.get("package_path") or (
        "pbg_" + str(ws_data.get("name", "")).replace("-", "_"))


def _av_candidate_packages(ws_root) -> list:
    import importlib.metadata as _metadata
    seen: set = set()
    out: list = []

    def _add(pkg: str) -> None:
        if pkg and pkg not in seen:
            seen.add(pkg)
            out.append(pkg)

    _add(_av_workspace_package(ws_root))
    try:
        for dist in _metadata.distributions():
            name = (dist.metadata.get("Name") or "").strip()
            if name.startswith("pbg-"):
                _add(name.replace("-", "_"))
    except Exception:  # noqa: BLE001
        pass
    return out


def _av_load_viewers_module(pkg: str):
    import importlib
    import warnings
    mod_name = f"{pkg}.workbench_viewers"
    try:
        return importlib.import_module(mod_name)
    except ModuleNotFoundError:
        return None
    except Exception as e:  # noqa: BLE001 — a broken contributor must not 500 the page
        warnings.warn(f"analysis_viewers: {mod_name} failed to import: "
                      f"{type(e).__name__}: {e}", stacklevel=2)
        return None


def _av_applies(viewer: dict, ws_root) -> bool:
    cond = viewer.get("applies", True)
    if callable(cond):
        try:
            return bool(cond(ws_root))
        except Exception:  # noqa: BLE001
            return False
    return bool(cond)


def _av_discover_viewers(ws_root) -> list:
    import warnings
    out: list = []
    for pkg in _av_candidate_packages(ws_root):
        mod = _av_load_viewers_module(pkg)
        if mod is None or not hasattr(mod, "get_viewers"):
            continue
        try:
            viewers = mod.get_viewers(ws_root) or []
        except Exception as e:  # noqa: BLE001
            warnings.warn(f"analysis_viewers: {pkg}.workbench_viewers.get_viewers raised "
                          f"{type(e).__name__}: {e}", stacklevel=2)
            continue
        for v in viewers:
            if not isinstance(v, dict) or not v.get("id"):
                continue
            if not _av_applies(v, ws_root):
                continue
            rec = dict(v)
            rec["package"] = pkg
            rec["uid"] = f"{pkg}::{v['id']}"
            out.append(rec)
    return out


def _av_resolve_targets(viewer: dict, ws_root) -> list:
    t = viewer.get("targets")
    if callable(t):
        try:
            t = t(ws_root)
        except Exception:  # noqa: BLE001
            return []
    if not isinstance(t, list):
        return []
    out: list = []
    for item in t:
        if isinstance(item, dict) and item.get("study"):
            out.append({
                "study": str(item["study"]),
                "label": str(item.get("label") or item["study"]),
                "detail": str(item.get("detail") or ""),
            })
    return out


def _av_public_spec(viewer: dict, ws_root) -> dict:
    assets = viewer.get("assets") or {}
    return {
        "uid": viewer["uid"],
        "id": viewer.get("id"),
        "package": viewer.get("package"),
        "title": viewer.get("title") or viewer.get("id"),
        "description": viewer.get("description", ""),
        "kind": viewer.get("kind", "launcher"),
        "targets": _av_resolve_targets(viewer, ws_root),
        "assets": {
            "js": list(assets.get("js") or []),
            "mount_id": assets.get("mount_id"),
            "api_prefix": assets.get("api_prefix"),
        } if assets else None,
    }


def _av_resolve_launch(ws_root, uid, study, run, ctx) -> dict:
    ctx = ctx or {}
    match = next((v for v in _av_discover_viewers(ws_root) if v.get("uid") == uid), None)
    if match is None:
        return {"error": f"viewer not found: {uid}", "status": 404}
    launch = match.get("launch")
    if not callable(launch):
        return {"error": f"viewer {uid} is not launchable", "status": 400}
    try:
        result = launch(ws_root, study, run, ctx)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "status": 500}
    if not isinstance(result, dict):
        return {"error": "viewer launch returned a non-dict result", "status": 500}
    return result


def _analysis_viewers(params: dict) -> dict:
    """List JSON-safe viewer descriptors, or resolve+invoke a viewer's launch (spec §11).

    ``params``: ``{"action": "list"}`` → ``{"viewers": [public_spec...]}``; or
    ``{"action": "launch", "uid", "study"?, "run"?, "ctx"?}`` → ``{"result": {...}}``
    (the contributor's launch dict, or a shaped error). Faithful port of
    ``analysis_viewers.viewers_public`` / ``resolve_launch``."""
    from pathlib import Path
    p = params or {}
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    ws_root = Path(_workspace) if _workspace else Path(".")
    action = p.get("action")
    if action == "launch":
        return {"result": _av_resolve_launch(
            ws_root, p.get("uid"), p.get("study"), p.get("run"), p.get("ctx"))}
    # default / "list"
    return {"viewers": [_av_public_spec(v, ws_root) for v in _av_discover_viewers(ws_root)]}


def _import_workspace_package(workspace: str) -> None:
    """Import the workspace's own package so its ``@composite_generator``s register
    into *this worker's* process registry. Best-effort — a workspace without a
    package (or an unparseable ``workspace.yaml``) just yields no workspace-local
    generators. Uses pyyaml (a workspace-venv dep, spec §4); falls back to a
    minimal ``package_path:`` scan if pyyaml is unavailable."""
    import importlib
    from pathlib import Path

    ws_yaml = Path(workspace) / "workspace.yaml"
    if not ws_yaml.is_file():
        return
    text = ws_yaml.read_text(encoding="utf-8")
    pkg = None
    try:
        import yaml
        data = yaml.safe_load(text) or {}
        pkg = data.get("package_path") or (
            "pbg_" + str(data.get("name", "")).replace("-", "_") if data.get("name") else None)
    except Exception:  # pyyaml absent / parse error → cheap line scan for package_path
        for line in text.splitlines():
            if line.strip().startswith("package_path:"):
                pkg = line.split(":", 1)[1].strip().strip("'\"") or None
                break
    if pkg:
        try:
            importlib.import_module(pkg)
        except Exception:  # noqa: BLE001 — a broken workspace package must not crash the worker
            pass


def _list_generators() -> dict:
    """Registry keys for this worker's environment (spec §11) — the workspace's
    own ``@composite_generator``s plus installed bigraph-package generators, held
    in THIS process (isolated from the HTTP process and from other sessions)."""
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    _import_workspace_package(_workspace)
    from viva_superpowers.composite_generator import _REGISTRY, discover_generators
    try:
        if not _REGISTRY:
            discover_generators()
    except Exception:  # noqa: BLE001 — best-effort; return whatever registered
        pass
    return {"generators": sorted(_REGISTRY.keys())}


_WS_CORE: dict = {}


def _get_workspace_core():
    """Build (once, cached) the workspace's core — reused across run-process calls."""
    if "c" in _WS_CORE:
        return _WS_CORE["c"]
    if _workspace and _workspace not in sys.path:
        sys.path.insert(0, _workspace)
    package_name, _pkgs, _ws = _workspace_meta(_workspace)
    mod = __import__(f"{package_name}.core", fromlist=["build_core"])
    _WS_CORE["c"] = mod.build_core()
    return _WS_CORE["c"]


def _json_safe(obj):
    """Coerce update() outputs (numpy arrays/scalars, sets, nested) to JSON."""
    try:
        import numpy as _np
    except Exception:
        _np = None
    if _np is not None:
        if isinstance(obj, _np.ndarray):
            return obj.tolist()
        if isinstance(obj, _np.generic):
            return obj.item()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def _resolve_registry_class(core, address: str):
    """Find a registered class by full address (preferred) or short name."""
    short = address.split(".")[-1]
    found = None
    for n, c in (getattr(core, "link_registry", {}) or {}).items():
        if not isinstance(c, type):
            continue
        addr = f"{getattr(c, '__module__', '')}.{getattr(c, '__qualname__', '')}"
        if addr == address:
            return c
        if found is None and (n == address or getattr(c, "__qualname__", "") == short):
            found = c
    return found


def _class_is_step(cls) -> bool:
    for anc in getattr(cls, "__mro__", []):
        if anc.__name__ in ("Process", "ProcessEnsemble"):
            return False
        if anc.__name__ == "Step":
            return True
    return False


def _process_template(params: dict) -> dict:
    """Resolved default config + input-port VALUES for a process/step, via
    ``core.fill(schema, {})`` — real defaults (paths, numbers, nested stores),
    not the null-heavy client-side ``_default`` template. Prefills the run panel."""
    p = params or {}
    address = p.get("address") or ""
    try:
        core = _get_workspace_core()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"build_core failed: {e}"}
    if core is None:
        return {"ok": False, "error": "workspace core unavailable"}
    cls = _resolve_registry_class(core, address)
    if cls is None:
        return {"ok": False, "error": f"class not found: {address}"}
    is_step = _class_is_step(cls)

    config = {}
    try:
        cs = getattr(cls, "config_schema", {}) or {}
        config = core.fill(cs, {}) if hasattr(core, "fill") else {}
    except Exception:
        config = {}

    inputs = {}
    inputs_schema = {}
    try:
        inst = cls(config if isinstance(config, dict) else {}, core)
        in_schema = inst.inputs()
        if isinstance(in_schema, dict):
            inputs_schema = _json_safe(in_schema)
            inputs = core.fill(in_schema, {}) if hasattr(core, "fill") else {}
    except Exception:
        inputs = {}

    return {
        "ok": True,
        "kind": "step" if is_step else "process",
        "config": _json_safe(config) if isinstance(config, dict) else {},
        "inputs": _json_safe(inputs) if isinstance(inputs, dict) else {},
        "inputs_schema": inputs_schema if isinstance(inputs_schema, dict) else {},
    }


def _run_process(params: dict) -> dict:
    """Instantiate a registry Process/Step with the given config, validate + fill
    the provided input-port values, and run one update() — returning outputs.

    Steps run as ``update(state)``; Processes as ``update(state, interval)``.
    Any failure (missing sim_data, bad config, un-fillable ports) degrades to a
    structured ``{ok: False, stage, error}`` rather than raising."""
    import traceback as _tb
    p = params or {}
    address = p.get("address") or ""
    config = p.get("config") if isinstance(p.get("config"), dict) else {}
    inputs = p.get("inputs") if isinstance(p.get("inputs"), dict) else {}
    interval = p.get("interval")

    try:
        core = _get_workspace_core()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stage": "core", "error": f"build_core failed: {e}"}
    if core is None:
        return {"ok": False, "stage": "core", "error": "workspace core unavailable"}

    # Resolve the class by full address (preferred) or short name.
    cls = None
    short = address.split(".")[-1]
    for n, c in (getattr(core, "link_registry", {}) or {}).items():
        if not isinstance(c, type):
            continue
        addr = f"{getattr(c, '__module__', '')}.{getattr(c, '__qualname__', '')}"
        if addr == address:
            cls = c
            break
        if cls is None and (n == address or getattr(c, "__qualname__", "") == short):
            cls = c
    if cls is None:
        return {"ok": False, "stage": "resolve", "error": f"class not found: {address}"}

    is_step = False
    for anc in getattr(cls, "__mro__", []):
        if anc.__name__ in ("Process", "ProcessEnsemble"):
            is_step = False
            break
        if anc.__name__ == "Step":
            is_step = True
            break

    try:
        inst = cls(config, core)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stage": "config", "error": str(e), "trace": _tb.format_exc()[-1200:]}

    try:
        in_schema = inst.inputs()
    except Exception:
        in_schema = {}
    state = inputs
    if isinstance(in_schema, dict) and hasattr(core, "fill"):
        try:
            state = core.fill(in_schema, inputs)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "stage": "inputs", "error": f"input validation failed: {e}"}

    try:
        if is_step:
            out = inst.update(state)
        else:
            try:
                iv = float(interval)
            except Exception:
                iv = 1.0
            out = inst.update(state, iv)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stage": "run", "error": str(e), "trace": _tb.format_exc()[-1200:]}

    return {"ok": True, "kind": "step" if is_step else "process", "outputs": _json_safe(out)}


def _handle(method: str, params: dict) -> dict:
    """Dispatch one method (spec §11)."""
    if method == "ping":
        return {"ok": True, "uptime_s": time.monotonic() - _started}
    if method == "initialize":
        # Handshake. build_core is deferred to the environment methods (warm on
        # first query, protocol §17), keeping initialize cheap.
        return {
            "protocol_version": PROTOCOL_VERSION,
            "workspace": _workspace,
            "python": sys.version.split()[0],
            "pid": os.getpid(),
            "capabilities": _CAPABILITIES,
        }
    if method == "list_generators":
        return _list_generators()
    if method == "registry_catalog":
        return _registry_catalog()
    if method == "run_process":
        return _run_process(params)
    if method == "process_template":
        return _process_template(params)
    if method == "viz_classes":
        return _list_visualizations()
    if method == "resolve_composite_state":
        return _resolve_composite_state(params)
    if method == "resolve_inner_composite_state":
        return _resolve_inner_composite_state(params)
    if method == "observables":
        return _observables(params)
    if method == "study_readout_check":
        return _study_readout_check(params)
    if method == "attach_process_docs":
        return _attach_process_docs_method(params)
    if method == "discover_composites":
        return _discover_composites()
    if method == "composites_full":
        return _composites_full()
    if method == "validate_generated_visualization":
        return _validate_generated_visualization(params)
    if method == "run_study_analyses":
        return _run_study_analyses(params)
    if method == "viz_class_inputs":
        return _viz_class_inputs()
    if method == "render_viz_doc":
        return _render_viz_doc(params)
    if method == "viz_preview":
        return _viz_preview(params)
    if method == "report_core_snapshot":
        return _report_core_snapshot(params)
    if method == "reexport_map":
        return _reexport_map(params)
    if method == "data_sources_provider":
        return _data_sources_provider(params)
    if method == "analysis_viewers":
        return _analysis_viewers(params)
    if method == "shutdown":
        return {"ok": True}
    raise _MethodError(-32601, f"unknown method: {method!r}")


def _serve(sock: socket.socket) -> None:
    """Serial request loop (spec §8): one request at a time, FIFO."""
    while True:
        req = _read_frame(sock)
        if req is None:  # parent closed the connection
            return
        rid = req.get("id")
        method = req.get("method")
        try:
            result = _handle(method, req.get("params") or {})
            _write_frame(sock, {"jsonrpc": "2.0", "id": rid, "result": result})
            if method == "shutdown":
                return
        except _MethodError as e:
            _write_frame(sock, {"jsonrpc": "2.0", "id": rid, "error": {
                "code": e.code, "message": e.message, "data": e.data}})
        except Exception as e:  # noqa: BLE001 — surface as a structured env error (spec §9)
            _write_frame(sock, {"jsonrpc": "2.0", "id": rid, "error": {
                "code": 2000, "message": str(e),
                "data": {"exc_type": type(e).__name__,
                         "traceback_tail": traceback.format_exc()[-2000:]}}})


def main(argv=None) -> int:
    global _workspace
    parser = argparse.ArgumentParser(prog="env_worker")
    parser.add_argument("--socket-fd", type=int, required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    _workspace = args.workspace

    # Wrap the inherited fd as an AF_UNIX stream socket (the socketpair peer).
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM, fileno=args.socket_fd)
    try:
        _serve(sock)
    finally:
        try:
            sock.close()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
