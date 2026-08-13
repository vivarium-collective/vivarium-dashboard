"""A workspace-local Visualization class for the env-worker viz-discovery test.

``tests/test_env_worker.py::test_viz_classes_discovers_workspace_and_default_classes``
asserts the worker returns *this workspace's own* ``Demo*`` viz class alongside
the framework defaults. Previously the test passed only by coincidence: the
``Demo*`` names it matched came from ``viva_superpowers._demo_visualizations``
(``DemoTimeSeriesPlot`` et al.), a framework demo module that the pbg->viva
rebrand removed in viva-superpowers 0.22. The fixture workspace never actually
shipped a viz class of its own, so the test was really exercising framework
demo classes, not workspace-local discovery.

Defining a real ``Demo*`` class here decouples the test from framework internals
and makes it verify what it claims: that the env worker walks
``<pkg>.visualizations`` and surfaces the workspace's own Visualization
subclasses. Modelled on ``process_bigraph.visualizations.distribution``.
"""
from __future__ import annotations

import json

from process_bigraph.visualization import Visualization


class DemoWorkspacePlot(Visualization):
    """Minimal workspace-local plot: render a scalar ``value`` as a bar.

    Wire ``inputs: {value: [path, to, scalar, store]}``. This exists to prove
    the env worker discovers viz classes declared inside the workspace package
    (``pbg_ws_increase_demo.visualizations``), independent of any framework-
    provided demo classes.
    """

    def inputs(self):
        return {"value": "float"}

    def update(self, state):
        value = state.get("value") or 0.0
        traces = [{"x": ["value"], "y": [value], "type": "bar",
                   "marker": {"color": "#6366f1"}}]
        layout = {"margin": {"l": 40, "r": 15, "t": 20, "b": 30},
                  "showlegend": False}
        return {"html": (
            '<div id="viz" style="height:280px"></div>'
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
            '<script>Plotly.newPlot("viz", '
            + json.dumps(traces) + ", " + json.dumps(layout)
            + ", {responsive:true, displayModeBar:false});</script>"
        )}
