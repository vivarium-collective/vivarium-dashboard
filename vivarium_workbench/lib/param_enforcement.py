"""Param-enforcement gate — declared params must actually be applied.

v2ecoli expert-feedback round 1 (2026-05-21): the reviewer's "newly provided
transcription and translation parameters … have not been implemented." The
Stage-1 params were catalogued (expert doc + dataset + investigation
guideline) but never wired into the model, so every run used v2ecoli's ParCa
defaults (translation efficiency ~20× instead of the intended 1). The
reviewer recognized the unimplemented params instantly. As the PLAN put it:
**"the gap is enforcement, not availability."**

This module is the shared core for an enforcement gate: a study *declares*
the params it enforces (``enforced_params`` in study.yaml), and the framework
*verifies* they were actually applied to each run — flagging any declared
param that's missing from, or differs from, the applied params. The report
surfaces violations prominently so "declared but not applied" is visible
rather than silent.

Design notes:

- Declarations use the **composite param names** the run actually takes (the
  author maps the science params — "translation efficiency" — onto the
  composite knob). The framework only does the comparison; it can't know a
  workspace's science→param mapping.
- "Applied" params come from a run's recorded overrides (``runs_meta.params_json``).
  A declared param that's *absent* from the applied set is a violation
  (``kind="missing"``) — which is exactly the "left at the default" case the
  reviewer hit. A present-but-different value is ``kind="mismatch"``.
- Numeric comparison uses a relative+absolute tolerance so ``1`` and ``1.0``
  match; bools and strings compare exactly; containers compare structurally.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


_MISSING = object()  # sentinel: declared param not present in applied params


@dataclass
class ParamViolation:
    """One enforced param that was not applied as declared."""

    param: str
    expected: Any
    actual: Any          # the applied value, or the string "<missing>" sentinel
    kind: str            # "missing" | "mismatch"

    def describe(self) -> str:
        if self.kind == "missing":
            return (f"{self.param}: declared {self.expected!r} but the run did "
                    f"not set it (left at the composite default)")
        return (f"{self.param}: declared {self.expected!r} but the run applied "
                f"{self.actual!r}")


def _values_match(expected: Any, actual: Any, *, rel_tol: float, abs_tol: float) -> bool:
    # Bools first — bool is an int subclass and `True == 1` is truthy in
    # Python, so require BOTH sides to be bool for a boolean flag to match.
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(expected) is bool and type(actual) is bool and expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(expected), float(actual),
                            rel_tol=rel_tol, abs_tol=abs_tol)
    return expected == actual


def check_enforced_params(
    declared: dict | None,
    applied: dict | None,
    *,
    rel_tol: float = 1e-9,
    abs_tol: float = 0.0,
) -> list[ParamViolation]:
    """Verify every declared ``{param: expected}`` is applied with that value.

    Returns the list of :class:`ParamViolation` (empty when all enforced
    params are applied as declared). Params in ``applied`` that aren't
    declared are ignored — enforcement only constrains the declared subset.
    """
    declared = declared or {}
    applied = applied or {}
    violations: list[ParamViolation] = []
    for param, expected in declared.items():
        actual = applied.get(param, _MISSING)
        if actual is _MISSING:
            violations.append(ParamViolation(param, expected, "<missing>", "missing"))
        elif not _values_match(expected, actual, rel_tol=rel_tol, abs_tol=abs_tol):
            violations.append(ParamViolation(param, expected, actual, "mismatch"))
    return violations


def load_enforced_params(spec: dict | None) -> dict:
    """Read the ``enforced_params`` declaration from a study/investigation spec.

    Accepts the canonical mapping form::

        enforced_params:
          translation_efficiency: 1
          mrna_per_min_per_gene: 1.5

    or a wrapped form ``{enforced_params: {params: {...}, source: "..."}}``
    so a declaration can cite where the values came from. Returns the flat
    ``{param: value}`` dict (empty when absent or malformed).
    """
    if not isinstance(spec, dict):
        return {}
    raw = spec.get("enforced_params")
    if isinstance(raw, dict):
        # Wrapped form: {params: {...}, source: ...}
        if "params" in raw and isinstance(raw["params"], dict):
            return dict(raw["params"])
        # Reject the wrapped-but-no-params shape so we don't treat a `source`
        # string as a param.
        if "params" in raw or "source" in raw:
            return {}
        return dict(raw)
    return {}


def format_violations(violations: list[ParamViolation]) -> str:
    """One-line-per-violation human summary for reports / lint output."""
    if not violations:
        return "all enforced params applied"
    return "\n".join("⚠ " + v.describe() for v in violations)
