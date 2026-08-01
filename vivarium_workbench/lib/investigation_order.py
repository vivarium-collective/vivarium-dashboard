"""Stable topological ordering of investigation member studies by their
``pipeline_gate.prerequisites`` edges. Declared order is the tie-break, so an
investigation with no prerequisites is returned unchanged (backward-compatible
with the historical flat declared-order loop in prepare_investigation)."""
from __future__ import annotations
from typing import Callable


class CycleError(Exception):
    """A prerequisite cycle among member studies."""
    def __init__(self, slugs):
        self.slugs = list(slugs)
        super().__init__(f"prerequisite cycle among studies: {sorted(self.slugs)}")


def prerequisite_order(declared: list[str],
                       prereqs_of: Callable[[str], list[str]]) -> list[str]:
    members = set(declared)
    # Only intra-investigation prerequisites constrain ordering.
    unmet = {s: [p for p in prereqs_of(s) if p in members and p != s]
             for s in declared}
    done: list[str] = []
    done_set: set[str] = set()
    remaining = list(declared)
    while remaining:
        # First slug in declared order whose prerequisites are all satisfied.
        pick = next((s for s in remaining
                     if all(p in done_set for p in unmet[s])), None)
        if pick is None:
            raise CycleError(remaining)
        done.append(pick)
        done_set.add(pick)
        remaining.remove(pick)
    return done
