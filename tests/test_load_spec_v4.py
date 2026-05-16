import yaml
import pathlib
from vivarium_dashboard.lib.investigations import load_spec


def test_load_spec_v3_yaml_returns_v4_in_memory(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "test-study",
        "baseline": [{"name": "b", "composite": "pkg.c", "params": {}}],
        "variants": [],
        "interventions": [],
        "runs": [],
        "visualizations": [],
        "conclusion": "",
        "objective": "",
        "parent_studies": [],
    }))
    spec = load_spec(spec_path)
    assert spec["schema_version"] == 4
    assert spec["tests"]["auto_discover"] is True
    assert spec["tests"]["data_source"] == "latest_run"
    assert spec["references"] == []
    assert spec["implementation_tasks"] == ""


def test_load_spec_v4_yaml_passes_through(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump({
        "schema_version": 4,
        "name": "test-study",
        "baseline": [{"name": "b", "composite": "pkg.c", "params": {}}],
        "variants": [],
        "interventions": [],
        "runs": [],
        "visualizations": [],
        "conclusion": "",
        "objective": "",
        "parent_studies": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [], "last_results": None},
        "references": [],
        "implementation_tasks": "",
    }))
    spec = load_spec(spec_path)
    assert spec["schema_version"] == 4
