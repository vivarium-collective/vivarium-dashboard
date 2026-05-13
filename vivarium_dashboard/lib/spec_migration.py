"""Migration helper: legacy `composites:` shape → v2 `variants:` shape."""
from __future__ import annotations
import pathlib, os
import yaml


def migrate_study_to_v2_vocabulary(spec_path: pathlib.Path) -> bool:
    """Migrate one spec.yaml from legacy composites-shape to v2 variants-shape.

    Returns True if a migration was applied, False if the file was already v2.
    """
    text = spec_path.read_text()
    data = yaml.safe_load(text) or {}
    if 'variants' in data:
        # Ensure new top-level fields present for idempotency.
        defaults = {
            'comparisons': [],
            'groups': [],
            'conclusions': '',
            'question': '',
            'hypothesis': '',
            'status': 'draft',
            'topic': '',
        }
        changed = False
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
                changed = True
        if not changed:
            return False
        _atomic_write(spec_path, yaml.safe_dump(data, sort_keys=False))
        return True
    if 'composites' not in data:
        return False
    composites = data.pop('composites') or []
    variants = []
    baseline_name = None
    for entry in composites:
        entry = dict(entry)
        intervention = {}
        if 'parameter_overrides' in entry:
            intervention['parameter_overrides'] = entry.pop('parameter_overrides')
        if 'process_overrides' in entry:
            intervention['process_overrides'] = entry.pop('process_overrides')
        if intervention:
            description = entry.pop('intervention_description', '')
            entry['intervention'] = {'description': description, **intervention}
        if baseline_name is None and entry.get('source') and not entry.get('extends'):
            baseline_name = entry['name']
        variants.append(entry)
    data['baseline'] = baseline_name or (variants[0]['name'] if variants else '')
    data['variants'] = variants
    data.setdefault('comparisons', [])
    data.setdefault('groups', [])
    data.setdefault('conclusions', '')
    data.setdefault('question', '')
    data.setdefault('hypothesis', '')
    data.setdefault('status', 'draft')
    data.setdefault('topic', '')
    _atomic_write(spec_path, yaml.safe_dump(data, sort_keys=False))
    return True


def _atomic_write(path: pathlib.Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text)
    os.replace(tmp, path)
