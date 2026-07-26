"""Pre-build inner-composite states for the loom's static (read-only) drill.

The Composite Explorer's inner-composite drill-in mini-map fetches
``GET /api/composite-inner-state?ref=<rootId>&hops=<json>`` live. A published
read-only bundle has no server, so the drill needs the same payloads as static
files. This module enumerates the Composite-Process nodes in a resolved
composite state, builds each inner composite (recursively, bounded), and keys
them by a deterministic, filesystem-safe id that the loom recomputes
client-side — see ``loom/src/api.ts:innerCompositeKey``. Both sides MUST agree,
so the key format is frozen here and mirrored there.

Heavy generators (e.g. v2ecoli's EcoliWCM cells) can't be instantiated at
publish time — the same reason their outer state is a committed artifact. So a
workspace commits inner-states to ``reports/composite-inner-state/<key>.json``
(via ``scripts/regenerate_composite_states.py``, run where the ParCa cache
exists); ``publish.build_bundle`` copies those verbatim and only live-builds the
light composites that resolve at publish time.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

# colony -> cell is depth 1; a small cap guards pathological / cyclic nesting
# while still covering "all the way down" for realistic composites.
_MAX_DEPTH = 4

# Meta / non-store keys that are not part of a bigraph store path (so they never
# appear in a `data.path` the loom stamps). Mirrors the client's path model.
_SKIP_KEYS = {"instance", "config", "inputs", "outputs", "interface", "wires"}


def inner_state_key(root_id: str, hops: list) -> str:
    """Deterministic, filesystem-safe key for a ``(root_id, hops)`` inner target.

    MUST match ``loom/src/api.ts:innerCompositeKey``: base64url (``+/`` → ``-_``,
    padding stripped) of ``root_id + '::' + compact-json(hops)``, where
    compact-json uses no whitespace (matching JS ``JSON.stringify``)."""
    raw = root_id + "::" + json.dumps(hops, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _composite_process_paths(state: Any, prefix: "list | None" = None) -> list:
    """Return the path (list of key segments) to each ``is_composite_process``
    node in ``state`` — the dict-key path, skipping meta keys. Matches the
    loom's ``data.path`` so the hops we build key-match the client's fetch."""
    prefix = prefix or []
    out: list = []
    if isinstance(state, dict):
        if state.get("_type") in ("process", "step") and state.get("is_composite_process"):
            out.append(list(prefix))
        for k, v in state.items():
            if not isinstance(k, str) or k.startswith("_") or k in _SKIP_KEYS:
                continue
            out.extend(_composite_process_paths(v, prefix + [k]))
    return out


def _unwrap_state(payload: Any) -> "dict | None":
    """Unwrap an ``/api/composite-inner-state`` / resolve payload to the bare
    store mapping (``{"state": {"state": {...}}}`` or ``{"state": {...}}``)."""
    st = payload.get("state") if isinstance(payload, dict) else payload
    if isinstance(st, dict) and isinstance(st.get("state"), dict):
        st = st["state"]
    return st if isinstance(st, dict) else None


def build_inner_states_for(ws_root, root_id: str, root_state: dict) -> dict:
    """Return ``{key: payload}`` for every Composite Process reachable from
    ``root_state``, recursively (bounded by ``_MAX_DEPTH``). Each ``payload`` is
    the ``/api/composite-inner-state`` body (``{state, crumbs}``). Best-effort:
    a target that fails to build (e.g. no ParCa cache in this interpreter) is
    skipped, so callers get whatever could be built without raising."""
    from vivarium_workbench.lib.composite_state_views import build_inner_composite_state

    out: dict = {}
    frontier = [([], root_state)]  # (accumulated hops, state at that level)
    depth = 0
    while frontier and depth < _MAX_DEPTH:
        nxt: list = []
        for base_hops, st in frontier:
            for path in _composite_process_paths(st):
                hops = base_hops + [path]
                key = inner_state_key(root_id, hops)
                if key in out:
                    continue
                try:
                    body, status = build_inner_composite_state(Path(ws_root), root_id, hops)
                except Exception:  # noqa: BLE001 — best-effort; skip unbuildable
                    continue
                if status != 200 or not isinstance(body, dict):
                    continue
                out[key] = body
                inner = _unwrap_state(body)
                if inner is not None:
                    nxt.append((hops, inner))
        frontier = nxt
        depth += 1
    return out
