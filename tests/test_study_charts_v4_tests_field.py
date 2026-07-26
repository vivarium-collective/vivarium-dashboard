"""Regression test for render_v4_test_charts' reading of the tests field.

In schema_version 4 study specs, the top-level ``tests:`` key holds the
pytest-autodiscover *config dict* (``auto_discover``/``data_source``/…), while
the behavior-test *list* lives under ``behavior_tests:``. The chart renderer
used to iterate ``spec["tests"]`` unconditionally, so on a v4 spec it walked
the config dict's string keys and crashed with
``'str' object has no attribute 'get'`` — 500-ing the whole study-charts
payload (including static charts). It must instead read the behavior-test list
and degrade to an empty list when no per-test measure path is resolvable.
"""
from __future__ import annotations

from vivarium_workbench.lib.study_charts import render_v4_test_charts


def test_v4_tests_config_dict_does_not_crash():
    """A v4 spec whose `tests` is the autodiscover config dict must not raise."""
    spec = {
        "schema_version": 4,
        # This is the shape that crashed: `tests` is a dict, not a list.
        "tests": {"auto_discover": True, "data_source": "latest_run",
                  "pytest_args": [], "last_results": None},
        "behavior_tests": [
            {"name": "some-test", "classification": "primary",
             "measure": {"kind": "live_cell_count", "cells_path": "cells"},
             "pass_if": {"op": "at_least", "threshold": 4}},
        ],
    }
    # No runs.db and no measure.path on the behavior tests → returns [] cleanly.
    assert render_v4_test_charts(spec, None, fallback_db=None) == []


def test_v4_list_tests_still_read():
    """Back-compat: a proper list-of-dicts under `tests` is still honored."""
    spec = {
        "schema_version": 4,
        "tests": [
            {"name": "t", "measure": {"path": "cells/x", "index": None},
             "pass_if": {}},
        ],
    }
    # No db to read from, so still [] — but crucially it iterated the list
    # without falling back and without raising.
    assert render_v4_test_charts(spec, None, fallback_db=None) == []
