"""Recipe operations on a process-bigraph composite document.

Pure logic; no I/O. Used by the Investigation Composites tab endpoints and
the runtime orchestrator.
"""
from __future__ import annotations
from typing import Any


def _follow_dotted_path(doc: dict, dotted: str) -> tuple[dict, str]:
    """Return (parent_container, final_key) for the addressed value.

    Path resolution:
      - 'rate'                                  -> doc['parameters']['rate'] container, key='default'
      - 'state.chromosome.DnaA_count._default'  -> doc['state']['chromosome']['DnaA_count'] container, key='_default'
      - 'state.replication.config.rate'         -> doc['state']['replication']['config'] container, key='rate'
    """
    if '.' in dotted:
        parts = dotted.split('.')
        node: Any = doc
        for p in parts[:-1]:
            if not isinstance(node, dict) or p not in node:
                raise KeyError(
                    f"path component {p!r} not found while resolving {dotted!r}; "
                    f"available keys: {list(node.keys()) if isinstance(node, dict) else 'n/a'}"
                )
            node = node[p]
        if not isinstance(node, dict):
            raise KeyError(f"path {dotted!r} ends in a non-mapping container")
        return node, parts[-1]
    # Bare name: assume a declared parameter; key is 'default'.
    params = doc.get('parameters') or {}
    if dotted not in params:
        raise KeyError(
            f"parameter {dotted!r} undeclared; available: {list(params.keys())}"
        )
    return params[dotted], 'default'


def apply_parameter_overrides(doc: dict, overrides: dict) -> None:
    """Apply scalar overrides to ``doc`` in place.

    Two override shapes:
      - bare name (``rate: 2.0``) -> sets ``parameters[name]['default']``.
      - dotted path (``state.chromosome.DnaA_count._default: 200``) -> sets
        the addressed scalar.
    Raises KeyError if a non-existent path is referenced.
    """
    for key, value in (overrides or {}).items():
        container, final = _follow_dotted_path(doc, key)
        container[final] = value


def apply_process_overrides(doc: dict, overrides: dict) -> None:
    """Apply process swap/removal overrides to ``doc`` in place.

    Each entry is ``process_name -> spec``:
      - None       -> remove the process
      - str        -> set address (keep config)
      - dict       -> may contain 'address' and/or 'config' to swap/replace
    Raises KeyError if the process doesn't exist.
    """
    state = doc.get('state') or {}
    for proc_name, spec in (overrides or {}).items():
        if proc_name not in state:
            raise KeyError(
                f"unknown process {proc_name!r}; available: {list(state.keys())}"
            )
        if spec is None:
            del state[proc_name]
            continue
        node = state[proc_name]
        if not isinstance(node, dict) or node.get('_type') != 'process':
            raise KeyError(f"{proc_name!r} is not a process node; cannot override")
        if isinstance(spec, str):
            node['address'] = spec
            continue
        if isinstance(spec, dict):
            if 'address' in spec:
                node['address'] = spec['address']
            if 'config' in spec:
                node['config'] = spec['config']
            continue
        raise TypeError(f"process_overrides[{proc_name!r}] must be None, str, or dict")


def walk_state_tree(doc: dict) -> list[dict]:
    """Flatten ``doc['state']`` into a list of node records.

    Each record:
        {path: [...], kind: 'store' | 'process',
         type?: str, default?: Any,
         address?: str, config?: dict}
    """
    state = doc.get('state') or {}
    out: list[dict] = []

    def _walk(node: Any, path: tuple):
        if not isinstance(node, dict):
            # Plain scalar leaf (e.g. a value or placeholder string).
            out.append({
                'path': list(path),
                'kind': 'store',
                'type': type(node).__name__,
                'default': node,
            })
            return
        if node.get('_type') == 'process':
            out.append({
                'path': list(path),
                'kind': 'process',
                'address': node.get('address', ''),
                'config': node.get('config', {}),
            })
            return
        if '_type' in node:
            out.append({
                'path': list(path),
                'kind': 'store',
                'type': node.get('_type', ''),
                'default': node.get('_default'),
            })
            return
        for key, child in node.items():
            _walk(child, path + (key,))

    for key, child in state.items():
        _walk(child, (key,))
    return out
