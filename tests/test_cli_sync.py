import json
import subprocess
from pathlib import Path

from vivarium_workbench import cli


def _make_origin(path: Path) -> tuple[str, str]:
    path.mkdir(parents=True, exist_ok=True)
    (path / "workspace.yaml").write_text("name: demo\npackage: demo\n")
    (path / "uv.lock").write_text("lock-contents-v1\n")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)
    for a in (["add", "-A"], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", "-C", str(path), *a], check=True, env=env, capture_output=True)
    sha = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                         check=True, capture_output=True, text=True).stdout.strip()
    return f"file://{path}", sha


def test_cmd_sync_from_manifest_file(tmp_path, monkeypatch):
    url, sha = _make_origin(tmp_path / "origin")
    from vivarium_workbench.lib.provenance_manifest import lockfile_hash
    manifest = {"repo": url, "commit": sha, "branch": "main", "workspace": "demo",
                "lockfile": lockfile_hash(tmp_path / "origin"), "results": {"runs": []}}
    mfile = tmp_path / "manifest.json"
    mfile.write_text(json.dumps(manifest))
    # avoid a real uv sync + real catalog write
    import vivarium_workbench.lib.sync_workspace as sw
    monkeypatch.setattr(sw.sync_materialize, "run_uv_sync", lambda ws, **k: ({"ok": True}, 200))
    monkeypatch.setattr(sw, "_catalog_add", lambda p, name=None, package=None: {"path": str(p)})

    dest = tmp_path / "local"
    rc = cli.main(["sync", str(mfile), "--dest", str(dest)])
    assert rc == 0
    head = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head == sha


def test_parse_repo_at_commit_forms():
    """`<repo>@<ref>` specs parse (and normalize to clone URLs); manifest
    URLs / file paths fall through to None."""
    assert cli._parse_repo_at_commit("github.com/org/repo@1a2b3c4") == \
        ("https://github.com/org/repo", "1a2b3c4")
    assert cli._parse_repo_at_commit("org/repo@main") == \
        ("https://github.com/org/repo", "main")
    assert cli._parse_repo_at_commit("https://github.com/org/repo@deadbeef") == \
        ("https://github.com/org/repo", "deadbeef")
    # ssh keeps its user@host, only the trailing @ref is the commit
    assert cli._parse_repo_at_commit("git@github.com:org/repo@abc123") == \
        ("git@github.com:org/repo", "abc123")
    # not repo@commit specs
    for src in ("https://x.github.io/v2ecoli/dashboard",
                "/tmp/manifest.json", "file:///tmp/m.json", "org/repo"):
        assert cli._parse_repo_at_commit(src) is None, src


def test_synthesize_manifest_skips_lockfile_gate():
    m = cli._synthesize_manifest("https://github.com/vivarium-collective/v2ecoli", "05df498")
    assert m == {"repo": "https://github.com/vivarium-collective/v2ecoli",
                 "commit": "05df498", "lockfile": None, "workspace": "v2ecoli"}


def test_cmd_sync_repo_at_commit_reproduces_any_commit(tmp_path, monkeypatch):
    """`sync <repo>@<ref>` materializes an arbitrary commit with no published
    bundle — the manifest is synthesized and the (moot) lockfile gate skipped."""
    url, sha = _make_origin(tmp_path / "origin")
    import vivarium_workbench.lib.sync_workspace as sw
    monkeypatch.setattr(sw.sync_materialize, "run_uv_sync", lambda ws, **k: ({"ok": True}, 200))
    monkeypatch.setattr(sw, "_catalog_add", lambda p, name=None, package=None: {"path": str(p)})
    dest = tmp_path / "local"
    rc = cli.main(["sync", f"{url}@{sha}", "--dest", str(dest)])
    assert rc == 0
    head = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head == sha


def test_cmd_sync_reports_failure_rc(tmp_path, monkeypatch):
    url, sha = _make_origin(tmp_path / "origin")
    manifest = {"repo": url, "commit": sha, "branch": "main", "workspace": "demo",
                "lockfile": "uv.lock@deadbeefcafe", "results": {"runs": []}}
    mfile = tmp_path / "m.json"
    mfile.write_text(json.dumps(manifest))
    rc = cli.main(["sync", str(mfile), "--dest", str(tmp_path / "local")])
    assert rc == 1  # lockfile mismatch -> non-zero exit
