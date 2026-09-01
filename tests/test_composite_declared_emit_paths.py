"""When a study declares no observables, the run's emit paths fall back to the
baseline composite's own ``emitters: [{paths: [...]}]`` declaration — so a
composite that states what it emits is honored without the study restating it."""
from __future__ import annotations

from pathlib import Path

import yaml

from vivarium_workbench.lib.study_runs import _composite_declared_emit_paths


def _study(tmp_path: Path, emitters=None) -> Path:
    sd = tmp_path / "study"
    (sd / "composites").mkdir(parents=True)
    doc = {
        "name": "c",
        "state": {"proc": {"_type": "process", "address": "local:P",
                            "outputs": {"x": ["x"]}}, "x": {}},
    }
    if emitters is not None:
        doc["emitters"] = emitters
    (sd / "composites" / "c.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    return sd


def test_reads_composite_emitter_paths(tmp_path):
    sd = _study(tmp_path, emitters=[
        {"address": "local:ParquetEmitter",
         "paths": ["molecule_counts", "molecule_positions", "time"]}])
    spec = {"baseline": [{"name": "c"}]}   # note: no document path (v2->v3 drops it)
    assert _composite_declared_emit_paths(sd, spec) == [
        "molecule_counts", "molecule_positions", "time"]


def test_empty_when_no_emitter_declared(tmp_path):
    sd = _study(tmp_path, emitters=None)
    assert _composite_declared_emit_paths(sd, {"baseline": [{"name": "c"}]}) == []


def test_no_composites_dir(tmp_path):
    (tmp_path / "study").mkdir()
    assert _composite_declared_emit_paths(tmp_path / "study", {}) == []
