"""Fable A #1b: the study scaffold documents ``runtime.default_emitter``
(``lib/scaffold_yaml.py:112-115,443-447``), but the study-run path
(``lib/study_runs.py`` baseline/variant launch sites) historically only read
``runtime.emitter`` — silently ignoring a scaffolded study's setting and
falling through to the workspace default. ``_study_runtime_emitter`` is the
tiny pure helper both read sites now delegate to; these tests pin its
resolution order directly, without needing a full study-run fixture.
"""

from vivarium_workbench.lib.study_runs import _study_runtime_emitter


def test_default_emitter_key_alone_resolves():
    """Scaffold key with no ``emitter`` set must still resolve (the bug)."""
    assert _study_runtime_emitter({"default_emitter": "sqlite"}) == "sqlite"


def test_emitter_key_alone_still_works():
    """Pre-existing key keeps working unchanged."""
    assert _study_runtime_emitter({"emitter": "parquet"}) == "parquet"


def test_emitter_wins_when_both_set():
    """More specific/explicit ``emitter`` takes precedence over the scaffold
    key when a study runtime block somehow sets both."""
    assert _study_runtime_emitter({"emitter": "parquet", "default_emitter": "sqlite"}) == "parquet"


def test_neither_key_falls_through_to_none():
    """Neither key set → None, preserving the existing fallback to
    investigation/workspace-default resolution (unchanged behavior)."""
    assert _study_runtime_emitter({}) is None
    assert _study_runtime_emitter(None) is None
