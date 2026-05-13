"""Test config for vivarium-dashboard.

The dashboard package itself is import-able from the venv (``pip install -e .``)
so we don't need to munge sys.path for ``vivarium_dashboard.*``. We do need
the fixture workspaces (``_fixtures/<name>/<pbg_pkg>``) on sys.path for
end-to-end tests that import the workspace's own package.
"""
from __future__ import annotations
import sys
from pathlib import Path

_FIXTURES = Path(__file__).parent / "_fixtures"
for fixture_ws in _FIXTURES.iterdir() if _FIXTURES.is_dir() else []:
    if fixture_ws.is_dir() and (fixture_ws / "workspace.yaml").exists():
        p = str(fixture_ws)
        if p not in sys.path:
            sys.path.insert(0, p)
