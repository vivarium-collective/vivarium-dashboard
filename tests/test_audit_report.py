"""HTML audit report generator + `vivarium-workbench audit` CLI."""
import yaml

from vivarium_workbench.cli import main
from vivarium_workbench.lib.audit_report import render_audit_html, get_or_build_report


def _ws(tmp_path):
    (tmp_path / "workspace.yaml").write_text("name: demo\n")
    d = tmp_path / "studies" / "a"
    d.mkdir(parents=True)
    (d / "study.yaml").write_text(yaml.safe_dump({"name": "a", "baseline": {"composite": "pkg.c"}}))
    return tmp_path


def test_render_audit_html_is_self_contained(tmp_path):
    ws = _ws(tmp_path)
    html = render_audit_html(ws, generated_at="2026-01-02 03:04")
    assert html.strip().startswith("<!doctype")
    assert "Reproducibility audit" in html
    assert 'class="badge"' in html            # a grade badge rendered
    assert "generated 2026-01-02 03:04" in html
    assert "http://" not in html.split("<style")[0]  # no external assets in <head>


def test_get_or_build_report_caches_and_reruns(tmp_path):
    ws = _ws(tmp_path)
    p1 = get_or_build_report(ws)
    cache = ws / ".pbg" / "audit" / "report.html"
    assert cache.is_file()
    assert "Re-run audit" in p1              # the page offers a re-run
    assert get_or_build_report(ws) == p1     # second call serves the cache verbatim
    # rerun regenerates (still a valid report; may differ only by timestamp)
    p3 = get_or_build_report(ws, rerun=True)
    assert p3.strip().startswith("<!doctype")
    assert (ws / ".pbg" / "audit" / "meta.json").is_file()


def test_audit_cli_html_and_json(tmp_path):
    ws = _ws(tmp_path)
    out = tmp_path / "report.html"
    assert main(["audit", "--workspace", str(ws), "--html", str(out)]) == 0
    assert out.is_file() and out.read_text().strip().startswith("<!doctype")
    assert main(["audit", "--workspace", str(ws), "--json"]) == 0
    # a bare workspace path with no workspace.yaml is refused
    assert main(["audit", "--workspace", str(tmp_path / "nope")]) != 0
