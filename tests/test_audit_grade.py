"""L0-L5 reproducibility grade + its wiring into the audit report."""
import yaml

from vivarium_workbench.lib.audit_grade import grade_workspace
from vivarium_workbench.lib.audit_views import build_audit


def _ws(tmp_path):
    (tmp_path / "workspace.yaml").write_text("name: demo\n")
    return tmp_path


def _study(ws, slug, composite="pkg.composites.c", inputs=None):
    d = ws / "studies" / slug
    d.mkdir(parents=True)
    spec = {"name": slug, "baseline": {"composite": composite}}
    if inputs is not None:
        spec["inputs"] = inputs
    (d / "study.yaml").write_text(yaml.safe_dump(spec))


def test_declared_study_grades_at_least_L0(tmp_path):
    ws = _ws(tmp_path)
    _study(ws, "a")
    g = grade_workspace(ws)
    ga = g["studies"]["a"]
    assert ga["level"] >= 0
    assert ga["label"] == f"L{ga['level']}"
    # The L0 "Declared" check passes because a composite is declared.
    assert ga["checks"][0]["level"] == "L0"
    assert ga["checks"][0]["status"] == "pass"
    # No stored artifacts / runs in a bare workspace → blocked before L3.
    assert ga["level"] < 3
    assert ga["blocked_by"] is not None
    assert g["distribution"]  # non-empty histogram


def test_undeclared_study_is_ungraded(tmp_path):
    ws = _ws(tmp_path)
    _study(ws, "b", composite="")  # no composite → L0 fails
    ga = grade_workspace(ws)["studies"]["b"]
    assert ga["level"] == -1
    assert ga["label"] == "—"
    assert ga["blocked_by"]["level"] == "L0"


def test_dangling_input_blocks_keyable(tmp_path):
    ws = _ws(tmp_path)
    # 'c' declares an input from a study that doesn't exist → L1 (keyable) fails.
    _study(ws, "c", inputs=[{"artifact": "x", "from": "ghost-study"}])
    ga = grade_workspace(ws)["studies"]["c"]
    # L0 passes (composite), L1 fails (dangling producer).
    assert ga["checks"][0]["status"] == "pass"
    assert ga["level"] == 0


def test_build_audit_attaches_grade_and_distribution(tmp_path):
    ws = _ws(tmp_path)
    _study(ws, "a")
    report, status = build_audit(ws)
    assert status == 200
    by_slug = {s["slug"]: s for s in report["studies"]}
    assert "a" in by_slug and by_slug["a"].get("grade")
    assert by_slug["a"]["grade"]["label"].startswith("L") or by_slug["a"]["grade"]["label"] == "—"
    assert "grade_distribution" in report["summary"]
