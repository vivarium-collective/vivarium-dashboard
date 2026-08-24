"""Adapt a user-supplied flat JSON document onto a composite's declared params.

Backs the "external config" JSON-spec input mode (item 86): an alternative to
filling in the per-field parameter form one value at a time. The document is
matched against whichever composite it targets — no per-composite or
per-workspace special-casing, only mechanical name-matching against that
composite's own already-fetched ``parameters`` schema (the same shape
``GET /api/composite-resolve`` already returns and the per-field form already
renders from).

Deliberately narrower than a full legacy-config translator: this module maps
JSON keys onto a composite's *own* declared parameter names (plus one small,
fixed, shape-driven convention below), not a specific upstream tool's config
schema. A document needing broader reshaping (dropping unrelated keys,
renaming, unit bridging) is expected to be prepared into that shape before
being pasted/uploaded here — this stays a generic mechanism, not a home for
any one workspace's own config dialect.
"""

from __future__ import annotations

from typing import Any

# Known "process-injection" keys: when present at the top level of a supplied
# document and NOT themselves a declared param, they nest into a declared
# map-typed `injected_processes` param if the target composite has one. This
# is shape-driven (any composite declaring an equivalently-named map param
# benefits), not conditioned on which composite id is being targeted.
_INJECTION_KEYS = frozenset({
    "fork_repo", "add_processes", "swap_processes",
    "process_configs", "topology", "time_step", "exclude_processes",
})
_INJECTION_TARGET_PARAM = "injected_processes"


def adapt_translated_config(raw: dict[str, Any], declared_params: dict[str, Any]) -> dict[str, Any]:
    """Map ``raw``'s top-level keys onto ``declared_params``'s own names.

    ``declared_params`` is the ``parameters`` dict a composite-resolve payload
    already carries (``{name: {type, default, description}}``).

    Returns ``{"params": {...matched, ready to merge into overrides...},
    "unmatched": [...keys in raw that matched nothing...]}`` — nothing is
    silently dropped without being reported back to the caller.
    """
    declared_names = set(declared_params or {})
    has_injection_target = _INJECTION_TARGET_PARAM in declared_names

    params: dict[str, Any] = {}
    injected: dict[str, Any] = {}
    unmatched: list[str] = []

    for key, value in (raw or {}).items():
        if key in declared_names:
            params[key] = value
        elif key in _INJECTION_KEYS and has_injection_target:
            injected[key] = value
        else:
            unmatched.append(key)

    if injected:
        # Merge onto any injected_processes the caller's own raw doc already
        # supplied directly (a document may mix both shapes) rather than
        # silently overwriting it.
        existing = params.get(_INJECTION_TARGET_PARAM)
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(injected)
        params[_INJECTION_TARGET_PARAM] = merged

    return {"params": params, "unmatched": sorted(unmatched)}


def composite_config_translate(ws_root: Any, body: dict) -> tuple[dict, int]:
    """``POST /api/composite-config-translate`` handler body.

    Body: ``{composite_id: str, config_json: dict}``. Resolves the target
    composite's declared params (the same ``resolve_composite_for_request``
    call ``GET /api/composite-resolve`` already uses) and runs
    :func:`adapt_translated_config` against them. Returns
    ``({"params": {...}, "unmatched": [...]}, 200)`` or an error tuple.
    """
    composite_id = (body.get("composite_id") or "").strip()
    config_json = body.get("config_json")

    if not composite_id:
        return {"error": "missing composite_id"}, 400
    if not isinstance(config_json, dict):
        return {"error": "config_json must be a JSON object"}, 422

    from vivarium_workbench.lib.composite_resolve import resolve_composite_for_request

    resolved = resolve_composite_for_request(ws_root, composite_id, {})
    if resolved is None:
        return {"error": f"composite not found: {composite_id}"}, 404
    if resolved.get("error") and not resolved.get("parameters"):
        return {"error": resolved["error"]}, 422

    declared_params = resolved.get("parameters") or {}
    result = adapt_translated_config(config_json, declared_params)
    return result, 200
