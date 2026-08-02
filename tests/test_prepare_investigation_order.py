import yaml
from pathlib import Path
import vivarium_workbench.lib.prepare_investigation as pi


def _mk(ws: Path, inv: str, members: list[str], specs: dict[str, dict]):
    (ws / "investigations" / inv).mkdir(parents=True)
    (ws / "investigations" / inv / "investigation.yaml").write_text(
        yaml.safe_dump({"name": inv, "studies": members}))
    for slug, spec in specs.items():
        d = ws / "studies" / slug
        d.mkdir(parents=True)
        (d / "study.yaml").write_text(yaml.safe_dump(spec))


def _record(monkeypatch):
    seq = []
    monkeypatch.setattr(pi, "prepare_study",
                        lambda ws, slug, *a, **k: seq.append(slug) or {"study": slug})
    return seq


def test_no_prereq_preserves_declared_order(tmp_path, monkeypatch):
    _mk(tmp_path, "inv", ["a", "b", "c"],
        {"a": {}, "b": {}, "c": {}})
    seq = _record(monkeypatch)
    pi.prepare_investigation(tmp_path, investigation="inv", render_only=True)
    assert seq == ["a", "b", "c"]


def test_prereq_runs_before_dependent(tmp_path, monkeypatch):
    # 'cfg' declares parca as a prerequisite but is declared FIRST
    _mk(tmp_path, "inv", ["cfg", "parca"], {
        "cfg": {"pipeline_gate": {"prerequisites": [{"study": "parca", "relation": "leads-to"}]}},
        "parca": {},
    })
    seq = _record(monkeypatch)
    pi.prepare_investigation(tmp_path, investigation="inv", render_only=True)
    assert seq.index("parca") < seq.index("cfg")


def test_legacy_parent_studies_does_NOT_reorder(tmp_path, monkeypatch):
    # Ordering keys STRICTLY on pipeline_gate.prerequisites. A study carrying
    # only the legacy `parent_studies` edge must keep its historical flat
    # declared order — NOT be silently reordered (backward-compat guarantee).
    _mk(tmp_path, "inv", ["cfg", "parca"], {
        "cfg": {"parent_studies": ["parca"]},   # legacy edge only, no pipeline_gate
        "parca": {},
    })
    seq = _record(monkeypatch)
    pi.prepare_investigation(tmp_path, investigation="inv", render_only=True)
    assert seq == ["cfg", "parca"]  # declared order preserved, unchanged


def test_string_prerequisite_entry_is_honored(tmp_path, monkeypatch):
    # pipeline_gate.prerequisites may carry bare-string entries, not only dicts.
    _mk(tmp_path, "inv", ["cfg", "parca"], {
        "cfg": {"pipeline_gate": {"prerequisites": ["parca"]}},
        "parca": {},
    })
    seq = _record(monkeypatch)
    pi.prepare_investigation(tmp_path, investigation="inv", render_only=True)
    assert seq.index("parca") < seq.index("cfg")
