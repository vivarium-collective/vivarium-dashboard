"""Deployment-config layer for ``ui.*`` bindings (workbench issue #471).

``workspace.yaml``'s ``ui:`` block is a three-way straddler: it holds genuine
workspace preferences (``composite_view``, ``auto_results``) alongside
**deployment / integration
bindings** — URLs to hosted external singletons such as ``ptools_server_url``,
``dashboard_public_base_url`` and ``viz_viewer_urls``. The latter belong to a
deployment-config layer, not to the scientific record (see ``lib/staging.py``,
which already excludes them from scoped commits, and REFACTOR-PLAN's "three
categories, not two").

Until now the deployment supplied those bindings by **rewriting
``workspace.yaml`` in place** at pod start, which makes a workspace carry the
identity of the site it happens to be running on. This module replaces that with
a read-only overlay:

    workspace.yaml ui:   what this thing needs to work on a laptop
    deploy.yaml    ui:   what this *site* substitutes instead

Precedence is lowest-first through an **ordered list of sources**, so a future
per-user layer (``~/.vivarium-workbench/config_ui.yaml``) is a one-line
insertion rather than a rewrite.

Semantics:

* The overlay is **shallow, at the ``ui.*`` key level.** A source that declares
  a mapping value (e.g. ``viz_viewer_urls``) supplies the whole map; it is not
  deep-merged. That keeps the rule to one sentence and lets a site *remove* an
  entry the workspace declares.
* A value of ``None`` (YAML ``null``) **unsets** the key, which is what makes
  the layer able to express everything the imperative seed script did (it had to
  ``pop()`` ``ptools_data_dir``).
* Nothing here raises. A missing, unreadable or malformed source degrades to
  "contributes nothing", so a stale ``DEPLOY_CONFIG`` pointing at nothing can
  never take the workbench down.

With no deployment config present the result is byte-identical to reading
``workspace.yaml`` directly, which is what keeps local development working with
no configuration at all.
"""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Callable, Iterable

import yaml

from vivarium_workbench.lib.env_compat import get_env

#: Env var naming the deployment config file (``VIVARIUM_WORKBENCH_DEPLOY_CONFIG``).
DEPLOY_CONFIG_ENV_SUFFIX = "DEPLOY_CONFIG"

UiSource = Callable[[], dict]


def _ui_block(path: Path) -> dict:
    """The ``ui:`` mapping from a YAML file, or ``{}`` for anything unusable."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - a bad config must never break the server
        return {}
    if not isinstance(data, dict):
        return {}
    ui = data.get("ui")
    return ui if isinstance(ui, dict) else {}


def workspace_ui(ws_root: Path | str) -> dict:
    """The ``ui:`` block from ``<ws_root>/workspace.yaml`` (or ``{}``)."""
    return _ui_block(Path(ws_root) / "workspace.yaml")


def deploy_config_path() -> Path | None:
    """Path named by ``VIVARIUM_WORKBENCH_DEPLOY_CONFIG``, or ``None`` if unset."""
    raw = (get_env(DEPLOY_CONFIG_ENV_SUFFIX, "") or "").strip()
    return Path(raw) if raw else None


def deploy_ui() -> dict:
    """The ``ui:`` block from the deployment config (or ``{}`` when unset)."""
    path = deploy_config_path()
    return _ui_block(path) if path is not None else {}


def default_sources(ws_root: Path | str) -> list[UiSource]:
    """The standard source chain, **lowest precedence first**.

    A per-user layer would be inserted between these two.
    """
    return [partial(workspace_ui, ws_root), deploy_ui]


def resolve_ui_config(
    ws_root: Path | str,
    *,
    sources: Iterable[UiSource] | None = None,
) -> dict:
    """Merge the ``ui.*`` sources, later ones overriding earlier ones.

    ``None`` values unset the key. Sources that raise are skipped.
    """
    merged: dict = {}
    for source in (default_sources(ws_root) if sources is None else sources):
        try:
            layer = source() or {}
        except Exception:  # noqa: BLE001 - one bad source must not lose the rest
            continue
        if not isinstance(layer, dict):
            continue
        for key, value in layer.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
    return merged
