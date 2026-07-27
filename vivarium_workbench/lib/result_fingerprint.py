"""Result fingerprint over a run's DECLARED fields (reproducible-rerun-spine
Task 3 / G4 — item 5 of the spine).

Where env_id (Task 2) answers "did this run execute under the same software
environment", ``result_fingerprint`` answers "did it produce the same
result": a sha256 digest of ROUNDED/canonical values for a run's declared
``fingerprint_fields`` (default: the study's declared observable paths,
resolved at launch — see ``composite_runs.build_run_manifest``), read from
the run's own output snapshot.

Deliberately excludes everything volatile — timestamps, absolute paths,
run_id, PID, etc. — by construction: only the ``fingerprint_fields`` the
caller names ever enter the hash. A field absent from the snapshot hashes as
an explicit ``null`` rather than being skipped, so a declared-but-missing
field is still deterministic (and still visible as a difference if it later
appears).

Two halves:
  - :func:`write_snapshot` — best-effort, WRITE side. Walks each declared
    field's slash-joined path against the run's final composite state (with
    the same ``agents/0/`` retry ``collect_emit_paths_from_spec`` uses for
    v2ecoli single-cell composites) and persists the resolved values as
    ``run_dir/observables.json`` — the run's "canonical output" snapshot.
  - :func:`fingerprint_run` — pure READ side. Reads that snapshot back and
    hashes only the declared fields. Split this way so the hash is
    reproducible from disk alone (no live composite needed), which is what
    the drift/verification tests exercise.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Filename of the per-run canonical output snapshot written by
# write_snapshot() and read by fingerprint_run(). Lives directly under the
# run's own directory (``.pbg/runs/<run_id>/``), never the shared runs.db.
SNAPSHOT_FILENAME = "observables.json"

# Floats are rounded to this many decimal places before hashing so
# insignificant float noise (last-bit differences across platforms/BLAS
# versions) doesn't register as a "different result". Declared fields that
# need tighter/looser tolerance are a future knob; this is a single global
# default for now.
_ROUND_NDIGITS = 6


def _to_native(v):
    """Best-effort conversion of a numpy/other scalar-like value to a plain
    Python type so it round-trips through ``json.dumps``. Never raises —
    values that don't convert are returned unchanged (``json.dumps``'s
    ``default=str`` is the final safety net)."""
    item = getattr(v, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:  # noqa: BLE001 — best-effort; fall through
            pass
    tolist = getattr(v, "tolist", None)
    if callable(tolist):
        try:
            return tolist()
        except Exception:  # noqa: BLE001 — best-effort; fall through
            pass
    return v


def _canonicalize(v):
    """Recursively round floats and normalize a value for stable hashing.

    - float  -> rounded to ``_ROUND_NDIGITS`` (avoids platform float noise).
    - bool   -> passed through as-is (bool is an int subclass; must not be
                rounded/coerced or True/False would collide with 1/0).
    - list/tuple/dict -> recursed into.
    - numpy scalar/array -> converted to native Python first.
    - anything else (str, int, None, ...) -> passed through.
    """
    v = _to_native(v)
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, _ROUND_NDIGITS)
    if isinstance(v, dict):
        return {k: _canonicalize(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_canonicalize(x) for x in v]
    return v


def _resolve_path(state: dict, parts: list[str]):
    node = state
    for p in parts:
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def _lookup_field(state: dict, field: str):
    """Resolve one declared field (a slash- or dot-joined path) against a
    composite's final state tree.

    Mirrors ``composite_runs.collect_emit_paths_from_spec``'s ``agents/0/``
    retry: v2ecoli single-cell composites scope biology under
    ``agents.0....``, so a field declared at the bare biology path (e.g.
    ``listeners/mass/dry_mass``) still resolves. Returns ``None`` when the
    path resolves nowhere under either form — the caller records that as an
    explicit ``null``, not a KeyError.
    """
    parts = [p for p in str(field).replace(".", "/").split("/") if p]
    if not parts:
        return None
    val = _resolve_path(state, parts)
    if val is None and parts[:1] != ["agents"]:
        val = _resolve_path(state, ["agents", "0"] + parts)
    return val


def write_snapshot(run_dir, state: dict, fingerprint_fields) -> bool:
    """Persist ``run_dir/observables.json``: this run's resolved values for
    ``fingerprint_fields``, read from its (still in-memory) final ``state``.

    Best-effort — a write failure returns ``False`` rather than raising, so
    it can never block a run from completing. Returns ``True`` on success.
    """
    try:
        run_dir = Path(run_dir)
        snapshot = {
            str(field): _canonicalize(_lookup_field(state or {}, field))
            for field in (fingerprint_fields or [])
        }
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / SNAPSHOT_FILENAME).write_text(
            json.dumps(snapshot, sort_keys=True, default=str), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001 — best-effort, never block a run
        return False


def _load_snapshot(run_dir) -> dict:
    p = Path(run_dir) / SNAPSHOT_FILENAME
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — corrupt/partial snapshot -> empty
        return {}


def fingerprint_run(run_dir, fingerprint_fields) -> str:
    """sha256 hex digest over the ROUNDED/canonical values of
    ``fingerprint_fields``, read from ``run_dir``'s canonical output
    snapshot (:data:`SNAPSHOT_FILENAME`, written by :func:`write_snapshot`).

    Deterministic and volatile-field-blind by construction: only the named
    ``fingerprint_fields`` are ever read out of the snapshot — a timestamp,
    path, or run_id living alongside them in the same file is never hashed.
    A declared field missing from the snapshot hashes as an explicit
    ``null`` (not skipped), so two runs that both lack a field still compare
    equal on it, while a run that later gains/loses it changes the hash.
    """
    snapshot = _load_snapshot(run_dir)
    fields = sorted({str(f) for f in (fingerprint_fields or [])})
    # Round/canonicalize at hash time too (not just in write_snapshot): the
    # snapshot on disk may have been produced by any writer, so rounding
    # must not depend on the writer having already done it.
    payload = {field: _canonicalize(snapshot.get(field)) for field in fields}
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
