"""The content address — **single-sourced from process-bigraph**.

This module used to be a hand-port of ``process_bigraph/artifacts.py``, kept
in lock-step by a comment asking that both copies be edited together. That is
not a guarantee, it is a hope: the two stay in sync only as long as nobody
forgets, and the failure is silent — the workbench and the engine compute
different addresses, every cache lookup misses, and the pipeline recomputes
everything while appearing to work perfectly.

The dependency already runs this way (the workbench depends on
process-bigraph, never the reverse), so there is no reason for a second
implementation to exist. These are re-exports, not copies.

The formula is a **wire format**: every artifact already in every store was
placed by it, so changing it orphans them all.
``tests/test_artifact_hashing.py`` pins it with the same golden constants
process-bigraph's own suite asserts — so the value is checked from both sides
of the dependency, and a change that passed one repo's tests cannot quietly
pass the other's.
"""

from __future__ import annotations

from process_bigraph.artifacts import (  # noqa: F401
    artifact_id,
    canonical,
)

__all__ = ["artifact_id", "canonical"]
