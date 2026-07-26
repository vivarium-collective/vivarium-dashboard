import hashlib, json

def _stable(o):
    if isinstance(o, float) and o.is_integer():
        return int(o)
    raise TypeError(type(o))

def canonical(config: dict) -> str:
    return json.dumps(config or {}, sort_keys=True, separators=(",", ":"), default=_stable)

def artifact_id(*, composite_id: str, config: dict, input_ids: list[str], commit: str) -> str:
    payload = "\n".join([composite_id, canonical(config),
                         "\n".join(sorted(input_ids or [])), commit or ""])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
