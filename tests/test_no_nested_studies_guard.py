"""Guard: no study.yaml nested under investigations/.

The dual layout (top-level `studies/` + nested `investigations/<inv>/studies/`)
was a source of nested-study bugs — e.g. a study's figures not publishing, or
workspace migrations inconsistently handling both locations. The fix is
registry-only layout: all studies live at top-level `studies/<slug>/`, and
`investigations/` are purely references to those studies (metadata, figures,
links, test gates — not study definitions).

This guard forbids reintroduction of the nested-study anti-pattern. It is the
acceptance gate for Study Pipeline Spec 1 migration: Task 7 (this guard) must
pass green on fixture workspaces, and Task 8's integration test + manual
v2ecoli migration will call it against purpose-built workspaces to prove the
migration succeeded.
"""
from __future__ import annotations

from pathlib import Path
import tempfile


def find_nested_studies(ws_root: Path) -> list[Path]:
    """Return paths of every study.yaml living UNDER an investigations/ tree
    (the forbidden nested layout). Empty list == clean (registry-only).

    Uses literal 'investigations' string — fixture workspaces use the default
    layout. Does not depend on WorkspacePaths to keep the guard trivially
    importable (mirroring how the symlink guard shells to git directly).
    """
    inv_root = ws_root / "investigations"
    if not inv_root.is_dir():
        return []
    return sorted(inv_root.rglob("study.yaml"))


def test_no_nested_studies_in_fixture_workspaces():
    """Scan every fixture workspace; assert no study.yaml under investigations/.

    Fixture workspaces are identified by either:
    - Containing a workspace.yaml file, OR
    - Being a direct subdirectory of tests/_fixtures/ with an investigations/ subdir
    """
    fixtures = Path(__file__).resolve().parent / "_fixtures"
    workspaces = set()

    # Find all workspace.yaml files and use their parent as a workspace
    for wsyaml in fixtures.rglob("workspace.yaml"):
        workspaces.add(wsyaml.parent)

    # Belt-and-braces: also check direct children of fixtures with investigations/
    for child in fixtures.iterdir():
        if child.is_dir() and (child / "investigations").is_dir():
            workspaces.add(child)

    offenders = {}
    for ws in sorted(workspaces):
        nested = find_nested_studies(ws)
        if nested:
            offenders[str(ws)] = [str(p) for p in nested]

    assert not offenders, (
        "Nested study.yaml found under investigations/ — studies must live at "
        f"top-level studies/<slug>/. Run `vivarium-workbench migrate-studies`. "
        f"Offenders: {offenders}"
    )


def test_guard_detects_nested_studies():
    """Verify the guard actually detects the anti-pattern (non-vacuous test).

    Build a temporary workspace with investigations/A/studies/x/study.yaml
    and assert find_nested_studies() finds it. This proves the guard would
    catch a real regression, not just pass because the scan is broken.
    """
    with tempfile.TemporaryDirectory() as tmp_root:
        tmp_path = Path(tmp_root)

        # Create a nested study structure
        nested_study_path = tmp_path / "investigations" / "A" / "studies" / "x"
        nested_study_path.mkdir(parents=True, exist_ok=True)
        (nested_study_path / "study.yaml").write_text("name: test\n")

        # Assert the guard finds it
        found = find_nested_studies(tmp_path)
        assert len(found) == 1
        assert found[0] == nested_study_path / "study.yaml"
