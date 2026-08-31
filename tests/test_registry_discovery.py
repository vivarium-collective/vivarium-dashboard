"""A valid composite reference must resolve on a cold worker.

It did not. `resolve_composite_state` for a real `spatio_flux…` generator
returned `__not_registered__` (404 through viva-api), and the same request
succeeded after some unrelated call had been made — which read as call-order
dependence and sent two investigations looking for a caching bug.

There was no caching bug. Six call sites guarded the global scan with
`if not _REGISTRY: discover_generators()`, and `_import_workspace_package` runs
*first* and always registers the workspace's own generators. Measured in the
deployed image:

    fresh import                 0 generators
    after `import v2ecoli`      33   <- registry non-empty, so the guard is False
    after discover_generators() 53   <- spatio_flux's 19 appear only here

**A non-empty registry is not a complete registry.** The fix tracks the scan.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

import vivarium_workbench.env_worker as ew

_SOURCE = Path(ew.__file__).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset() -> Any:
    ew._DISCOVERED = False
    yield
    ew._DISCOVERED = False


# --- the guard must be gone everywhere --------------------------------------


def test_no_call_site_guards_the_scan_on_registry_emptiness() -> None:
    """The regression proper, and it must hold at EVERY site — the bug was that
    six of them shared one wrong idea, so fixing five would leave it live."""
    offenders = [
        line.strip()
        for line in _SOURCE.splitlines()
        if re.search(r"if not _REGISTRY\b", line) and not line.lstrip().startswith(("#", "*", '"'))
    ]
    assert not offenders, f"registry-emptiness guards remain: {offenders}"


def test_the_scan_is_reached_through_the_helper() -> None:
    """One place decides whether to scan, so this cannot drift apart again."""
    calls = _SOURCE.count("_ensure_generators_discovered()")
    assert calls >= 6, f"expected the helper at every former guard site, found {calls}"


# --- the helper's own behaviour ---------------------------------------------


def test_it_scans_once_and_then_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scan walks every installed distribution — cheap once, not per call."""
    calls: list[int] = []
    monkeypatch.setattr(
        "process_bigraph.composite_generator.discover_generators", lambda: calls.append(1)
    )
    for _ in range(5):
        ew._ensure_generators_discovered()
    assert calls == [1]


def test_the_decision_does_not_consult_the_registry_at_all() -> None:
    """THE BUG, stated directly.

    The old guard asked the registry whether to scan, and the registry cannot
    answer that — it records what has REGISTERED, not what has been SCANNED, and
    the workspace package always registers first. So the fix is not a better
    reading of `_REGISTRY`; it is not reading it. Asserted on the helper's own
    source, because "it happens to work today" is what the guard also did.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(ew._ensure_generators_discovered)))
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    # Drop the docstring — it QUOTES the old guard, and a source-text test that
    # reads its own prose proves nothing (learned the hard way on #996).
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    code = "\n".join(ast.unparse(node) for node in body)
    assert "_REGISTRY" not in code, "the scan decision is reading the registry again"
    assert "_DISCOVERED" in code, "it must track the scan itself"


def test_importing_the_workspace_package_does_not_suppress_the_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The behavioural half of the bug.

    `_list_generators` imports the workspace package and then scans. Under the
    old guard the import's own registrations made the guard False and the scan
    never ran. Whatever the import does, the scan must still happen.

    (The registry cannot be pre-populated from a test — there is no workspace
    configured here and `_REGISTRY` is a view, not a dict — so this pins the
    ORDER-INDEPENDENCE instead: an import beforehand changes nothing.)
    """
    scanned: list[int] = []
    monkeypatch.setattr(
        "process_bigraph.composite_generator.discover_generators", lambda: scanned.append(1)
    )
    monkeypatch.setattr(ew, "_import_workspace_package", lambda ws: scanned.append(0))
    ew._DISCOVERED = False
    ew._list_generators()
    assert scanned == [0, 1], (
        f"expected import-then-scan, got {scanned} — the scan is being skipped again"
    )


def test_a_failing_scan_does_not_break_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """One broken sibling package must not make the workspace's own generators
    unreachable — that would turn a third-party install problem into an outage."""

    def _boom() -> None:
        raise RuntimeError("a sibling package is broken")

    monkeypatch.setattr("process_bigraph.composite_generator.discover_generators", _boom)
    ew._ensure_generators_discovered()  # must not raise


def test_a_failing_scan_is_not_retried_every_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scan that raised will raise again. Retrying per call turns one broken
    install into a per-request cost on a path that is meant to be interactive."""
    attempts: list[int] = []

    def _boom() -> None:
        attempts.append(1)
        raise RuntimeError("still broken")

    monkeypatch.setattr("process_bigraph.composite_generator.discover_generators", _boom)
    for _ in range(4):
        ew._ensure_generators_discovered()
    assert attempts == [1]


def test_generators_listed_after_the_fix_include_installed_siblings() -> None:
    """End to end in this process: whatever `discover_generators` can see must be
    visible to `list_generators`, not just the workspace's own."""
    before = set(ew._list_generators()["generators"])
    ew._DISCOVERED = False
    after = set(ew._list_generators()["generators"])
    assert after >= before
