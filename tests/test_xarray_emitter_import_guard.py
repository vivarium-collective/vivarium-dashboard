"""Regression for #857 — the xarray emitter import must survive the
``pbg_emitters`` -> ``viva_emitters`` package rename.

``vivarium_workbench.lib.emitters._run_xarray`` used to import unconditionally
from ``pbg_emitters.xarray_emitter``. In the v2ecoli venv the emitters package
is installed as ``viva_emitters`` only (the workbench .venv has the mirror
image: ``pbg_emitters`` only), so that dead import raised ``ModuleNotFoundError``
at run time. The import is now dual-name guarded (viva first, pbg fallback).

This test masks ``pbg_emitters`` so the OLD unguarded import path fails, makes
``viva_emitters`` importable (real if installed, otherwise a stub module tree),
and drives ``_run_xarray`` far enough to execute the guarded import. It asserts
the emitter import no longer raises ``ModuleNotFoundError``. On unpatched main
(bare ``pbg_emitters`` import) it fails; with the fix it passes.
"""
from __future__ import annotations

import sys
import types


def _ensure_viva_emitters(monkeypatch):
    """Make ``viva_emitters.xarray_emitter`` importable, returning without
    change if the real package is present, otherwise injecting a minimal stub
    module tree into ``sys.modules`` (auto-removed by monkeypatch)."""
    try:  # prefer the real package when the test env provides it
        import viva_emitters.xarray_emitter  # noqa: F401
        import viva_emitters.xarray_emitter.view  # noqa: F401
        return
    except ImportError:
        pass

    pkg = types.ModuleType("viva_emitters")
    pkg.__path__ = []  # mark as a package
    xe = types.ModuleType("viva_emitters.xarray_emitter")
    xe.__path__ = []

    class XArrayEmitter:  # minimal stand-in; only needs to be importable
        pass

    xe.XArrayEmitter = XArrayEmitter
    view = types.ModuleType("viva_emitters.xarray_emitter.view")
    view.view_from_emit_paths = lambda *a, **k: {}

    monkeypatch.setitem(sys.modules, "viva_emitters", pkg)
    monkeypatch.setitem(sys.modules, "viva_emitters.xarray_emitter", xe)
    monkeypatch.setitem(sys.modules, "viva_emitters.xarray_emitter.view", view)


def test_run_xarray_import_survives_pbg_to_viva_rename(tmp_path, monkeypatch):
    from vivarium_workbench.lib import emitters

    # Mask the OLD path so an unguarded ``pbg_emitters`` import raises.
    monkeypatch.setitem(sys.modules, "pbg_emitters", None)
    _ensure_viva_emitters(monkeypatch)

    # core=None makes execution fail AFTER the guarded emitter import (at the
    # first ``core.register_link`` call) — we only care that the import itself
    # did not raise ModuleNotFoundError for the emitter packages.
    try:
        emitters._run_xarray(
            state={},
            run_id="t",
            emit_paths=["anything"],
            out_dir=str(tmp_path),
            core=None,
            steps=[],
            progress_cb=lambda *a, **k: None,
            emitter_config={},
        )
    except ModuleNotFoundError as e:  # the bug we are guarding against
        if "pbg_emitters" in str(e) or "viva_emitters" in str(e):
            raise AssertionError(
                f"xarray emitter import is not rename-guarded (#857): {e}"
            ) from e
        raise  # an unrelated missing module — surface it
    except Exception:
        pass  # any non-import failure past the guarded import is fine here
