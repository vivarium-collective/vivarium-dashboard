"""`vivarium-workbench add-dashboard` scaffolds a robust dashboard publish."""
import yaml

from vivarium_workbench.cli import main


def _mk_ws(tmp_path):
    (tmp_path / "workspace.yaml").write_text("name: demo\n")
    return tmp_path


def test_add_dashboard_writes_valid_files(tmp_path):
    ws = _mk_ws(tmp_path)
    rc = main(["add-dashboard", "--workspace", str(ws),
               "--org", "vivarium-collective", "--repo", "viva-demo"])
    assert rc == 0
    wf = ws / ".github" / "workflows" / "publish-dashboard.yml"
    sh = ws / "scripts" / "publish_dashboard.sh"
    assert wf.is_file() and sh.is_file()

    # Workflow is valid YAML and carries the robust install + gh-pages auto-create.
    doc = yaml.safe_load(wf.read_text())
    assert "jobs" in doc and "publish" in doc["jobs"]
    body = wf.read_text()
    assert "--no-deps" in body, "install must not abort on unresolved workspace sim-deps"
    assert "vivarium-workbench.git@main" in body, "must install workbench from main"
    assert "--orphan gh-pages" in body, "must create gh-pages if absent"

    # Script carries the per-repo base-path + interactive-url.
    script = sh.read_text()
    assert 'BASE_PATH="/viva-demo/dashboard"' in script
    assert 'INTERACTIVE_URL="https://github.com/vivarium-collective/viva-demo"' in script


def test_add_dashboard_requires_workspace(tmp_path):
    # No workspace.yaml → refuses with a nonzero exit.
    rc = main(["add-dashboard", "--workspace", str(tmp_path), "--repo", "x"])
    assert rc != 0


def test_add_dashboard_no_clobber(tmp_path):
    ws = _mk_ws(tmp_path)
    assert main(["add-dashboard", "--workspace", str(ws), "--repo", "viva-demo",
                 "--org", "vivarium-collective"]) == 0
    # Second run without --force refuses rather than overwrite.
    assert main(["add-dashboard", "--workspace", str(ws), "--repo", "viva-demo",
                 "--org", "vivarium-collective"]) != 0
    # With --force it succeeds.
    assert main(["add-dashboard", "--workspace", str(ws), "--repo", "viva-demo",
                 "--org", "vivarium-collective", "--force"]) == 0
