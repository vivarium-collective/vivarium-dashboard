"""A study condition can carry its reproducible run-config by reference to a
canonical file (``conditions.baseline.config_file``). ``load_spec`` folds that
file's contents into the condition's ``params`` (inline params win; ``_``-prefixed
comment keys dropped), so the merged config flows unchanged into BOTH the
Configure panel and the run path via the existing v4→legacy projection."""
import json

import yaml

from vivarium_workbench.lib import _root
from vivarium_workbench.lib.investigations import load_spec


def _mk_study(tmp_path, baseline, extra_files=None):
    (tmp_path / "workspace.yaml").write_text("name: t\n", encoding="utf-8")
    _root.set_workspace_root(tmp_path)
    for rel, doc in (extra_files or {}).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith((".yaml", ".yml")):
            p.write_text(yaml.safe_dump(doc), encoding="utf-8")
        else:
            p.write_text(json.dumps(doc), encoding="utf-8")
    sdir = tmp_path / "studies" / "s1"
    sdir.mkdir(parents=True)
    spec = {
        "schema_version": 4, "name": "s1", "question": "q",
        "assumptions": [{"text": "a"}], "tests": [{"name": "t1"}],
        "conditions": {"baseline": baseline},
    }
    (sdir / "study.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    return sdir / "study.yaml"


def test_config_file_folds_into_params(tmp_path):
    path = _mk_study(
        tmp_path,
        baseline={"composite": "pkg.mod.fn", "config_file": "configs/s1.json",
                  "params": {"n_generations": 3}},
        extra_files={"configs/s1.json": {
            "_note": "author comment — must NOT leak into params",
            "injected_processes": {"perm": {}}, "n_generations": 8,
            "max_duration": 9999, "experiment_id": "s1exp"}},
    )
    params = load_spec(path)["baseline"][0]["params"]
    assert params["injected_processes"] == {"perm": {}}   # rich field carried
    assert params["max_duration"] == 9999
    assert params["experiment_id"] == "s1exp"
    assert params["n_generations"] == 3                   # inline param wins over file
    assert "_note" not in params                          # comment key dropped


def test_config_file_yaml_supported(tmp_path):
    path = _mk_study(
        tmp_path,
        baseline={"composite": "pkg.mod.fn", "config_file": "run_config.yaml"},
        extra_files=None,
    )
    # co-located next to study.yaml (study-dir-relative resolution)
    (path.parent / "run_config.yaml").write_text(
        yaml.safe_dump({"seed": 7, "max_duration": 1200}), encoding="utf-8")
    params = load_spec(path)["baseline"][0]["params"]
    assert params == {"seed": 7, "max_duration": 1200}


def test_missing_config_file_is_noop(tmp_path):
    # a dangling reference never raises; params are left exactly as authored
    path = _mk_study(
        tmp_path,
        baseline={"composite": "pkg.mod.fn", "config_file": "configs/nope.json",
                  "params": {"seed": 1}},
    )
    params = load_spec(path)["baseline"][0]["params"]
    assert params == {"seed": 1}


def test_no_config_file_unchanged(tmp_path):
    path = _mk_study(
        tmp_path,
        baseline={"composite": "pkg.mod.fn", "params": {"seed": 2, "cache_dir": "out/cache"}},
    )
    params = load_spec(path)["baseline"][0]["params"]
    assert params == {"seed": 2, "cache_dir": "out/cache"}
