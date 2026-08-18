"""Generalized local secrets store for vivarium-workbench (item 72 Phase 2).

Extends ``github_auth.py``'s existing keyring-backed credential mechanism —
factored into :mod:`vivarium_workbench.lib._secrets_backend` — to arbitrary
**named**, per-workspace secrets, not just GitHub tokens. This is what lets a
workspace hold a credential for any wrapped simulator/service that needs one:
e.g. ``pbg-ptools``' ``ui.ptools_server_url`` in ``workspace.yaml`` can only be
a bare URL today because there's nowhere safe to put an API key for it. This
module closes that gap generically; wiring a specific consumer (ptools or
otherwise) to it is separate, later work.

Storage model:
  - Secret **values** live only in the OS keyring, one entry per
    ``(workspace, name)`` pair, under the same ``vivarium-dashboard`` keyring
    service ``github_auth.py`` already uses (see ``_secrets_backend.KEYRING_SERVICE``).
    When the keyring is unavailable (e.g. headless Linux with no secret-service
    daemon), a value degrades to in-memory-only for the current process
    lifetime — the same degrade story ``github_auth.py`` already documents for
    GitHub sessions, not a new limitation.
  - Secret **names** (never values) are additionally recorded in a small
    per-workspace JSON index file under
    ``~/.config/vivarium-dashboard/secrets/<workspace-id>.json``. This mirrors
    ``github_auth.py``'s own ``_last_login_path()`` hint-file pattern, and
    exists only because the ``keyring`` package has no cross-backend "list
    keys for a service" API — the index is non-secret bookkeeping, never the
    store of record for a value.

Public API is deliberately minimal, matching the plan: list names, set,
delete, and a ``current_secret_env()`` helper mirroring
``github_auth.current_token_env()``'s shape for injecting one named secret
into a spawned subprocess's environment. There is no "get value" function —
a value is only ever returned packaged for env-injection, never returned or
logged bare.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from threading import Lock

from . import _secrets_backend as _backend
from .atomic_io import atomic_write_text

log = logging.getLogger(__name__)

_KEYRING_SERVICE = _backend.KEYRING_SERVICE
_KEY_PREFIX = "secret"  # keyring key shape: "secret:<workspace-id>:<name>"

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

# In-memory fallback for when the keyring is unavailable, keyed by
# (workspace_id, name). Mirrors github_auth.py's `_CACHED_SESSION` degrade
# story: values set here do not survive a process restart, same as an
# in-memory-only GitHub session does not — an OS keyring is the only
# durable store either mechanism has.
_MEM_LOCK = Lock()
_MEM_STORE: dict[tuple[str, str], str] = {}


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        raise ValueError(
            f"invalid secret name {name!r}: must be 1-128 characters of "
            "letters, digits, '.', '_', '-'"
        )
    return name


def _workspace_id(ws_root: Path | str) -> str:
    """Stable short id for a workspace root, used to namespace both the
    keyring key and the on-disk name index.

    Hashed (not the raw path) so the index filename and keyring key stay
    short/portable regardless of where a workspace happens to be checked out,
    and so a workspace path never appears in a keyring key string.
    """
    resolved = str(Path(ws_root).resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def _index_path(ws_root: Path | str) -> Path:
    return _backend.config_dir() / "secrets" / f"{_workspace_id(ws_root)}.json"


def _keyring_key(ws_root: Path | str, name: str) -> str:
    return f"{_KEY_PREFIX}:{_workspace_id(ws_root)}:{name}"


def _read_index(ws_root: Path | str) -> list[str]:
    p = _index_path(ws_root)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        names = data.get("names", [])
        return sorted({n for n in names if isinstance(n, str)})
    except (OSError, ValueError):
        log.warning("secrets index at %s is unreadable/corrupt; treating as empty", p)
        return []


def _write_index(ws_root: Path | str, names: set[str]) -> None:
    p = _index_path(ws_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps({"names": sorted(names)}, indent=2) + "\n")


def _get_secret_value(ws_root: Path | str, name: str) -> str | None:
    """Internal only — never expose this as public API. A value must only
    ever leave this module packaged by :func:`current_secret_env`."""
    ws_id = _workspace_id(ws_root)
    key = _keyring_key(ws_root, name)
    value = _backend.keyring_get(_KEYRING_SERVICE, key)
    if value is not None:
        return value
    with _MEM_LOCK:
        return _MEM_STORE.get((ws_id, name))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_secret_names(ws_root: Path | str) -> list[str]:
    """Sorted names of secrets set for this workspace. Never values."""
    return _read_index(ws_root)


def set_secret(ws_root: Path | str, name: str, value: str) -> bool:
    """Store ``value`` under ``name`` for this workspace.

    Returns whether the value was persisted to the OS keyring (``False``
    means it degraded to in-memory-only for this process's lifetime — the
    name is still recorded so :func:`list_secret_names` stays accurate, but
    :func:`current_secret_env` will find nothing to inject after a restart
    until a keyring becomes available).
    """
    name = _validate_name(name)
    if not value:
        raise ValueError("secret value must be non-empty")
    ws_id = _workspace_id(ws_root)
    key = _keyring_key(ws_root, name)
    persisted = _backend.keyring_set(_KEYRING_SERVICE, key, value)
    with _MEM_LOCK:
        if persisted:
            # Keyring is now the value of record; drop any stale in-memory copy.
            _MEM_STORE.pop((ws_id, name), None)
        else:
            _MEM_STORE[(ws_id, name)] = value
    names = set(_read_index(ws_root))
    names.add(name)
    _write_index(ws_root, names)
    return persisted


def delete_secret(ws_root: Path | str, name: str) -> None:
    """Remove a named secret's value (keyring + in-memory fallback) and drop
    it from the name index. No-op if the name was never set."""
    name = _validate_name(name)
    ws_id = _workspace_id(ws_root)
    key = _keyring_key(ws_root, name)
    _backend.keyring_delete(_KEYRING_SERVICE, key)
    with _MEM_LOCK:
        _MEM_STORE.pop((ws_id, name), None)
    names = set(_read_index(ws_root))
    if name in names:
        names.discard(name)
        _write_index(ws_root, names)


def current_secret_env(ws_root: Path | str, name: str, env_var: str) -> dict[str, str]:
    """Return ``{env_var: value}`` for a named secret, or ``{}`` if unset.

    Mirrors ``github_auth.current_token_env()``'s shape for injecting a
    credential into a spawned subprocess without ever writing it to disk::

        env = os.environ | current_secret_env(ws_root, "ptools_api_key", "PTOOLS_API_KEY")
        subprocess.run([...], env=env)

    This is the only path through which a stored value ever leaves this
    module — there is no "get value" function.
    """
    name = _validate_name(name)
    value = _get_secret_value(ws_root, name)
    if value is None:
        return {}
    return {env_var: value}


def mask_secret(text: str, *secrets: str) -> str:
    """Redact known secret value(s) from ``text`` before logging/returning it.

    Thin, module-local entry point over the shared value-based masker —
    mirrors ``github_auth.mask_token``'s shape (each module exposes its own
    masking helper, backed by the one shared implementation).
    """
    return _backend.mask_value(text, *secrets)
