"""Deterministic study `kind` resolution — biological | computational | theoretical.

Explicit `spec.kind` wins when valid; otherwise inferred from unanimous finding
kinds; otherwise defaults to `computational` (never silently `biological`).
"""
from __future__ import annotations

VALID_KINDS = ("biological", "computational", "theoretical")
DEFAULT_KIND = "computational"


def infer_study_kind(spec: dict) -> str:
    explicit = (spec.get("kind") or "").strip().lower()
    if explicit in VALID_KINDS:
        return explicit
    kinds = {
        (f.get("kind") or "").strip().lower()
        for f in (spec.get("findings") or [])
        if isinstance(f, dict) and (f.get("kind") or "").strip().lower() in VALID_KINDS
    }
    if len(kinds) == 1:
        return next(iter(kinds))
    return DEFAULT_KIND
