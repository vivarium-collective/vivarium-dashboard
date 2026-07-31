"""The store re-key after process-bigraph 1.7.0's whole-float fix.

The fix is narrow by construction — a config with no whole-valued float keeps
its address — so these tests care about the three things that are NOT obvious:
that a float-spelled artifact actually moves onto its int-spelled twin's
address, that an artifact nothing can explain is *logged* rather than deleted,
and that re-running changes nothing.
"""

from __future__ import annotations

import json

import pytest
import yaml

from process_bigraph.artifacts import artifact_id, legacy_artifact_id
from vivarium_workbench.lib.artifacts.migrate import migrate_artifacts
from vivarium_workbench.lib.artifacts.store import ArtifactStore


def _workspace(tmp_path, studies: dict, inputs: dict | None = None) -> "object":
    """A workspace declaring ``{slug: config}`` studies, no git.

    ``inputs`` optionally wires ``{slug: [producer_slug, ...]}``.
    """
    ws = tmp_path / "ws"
    (ws / "studies").mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: t\n")
    for slug, config in studies.items():
        d = ws / "studies" / slug
        d.mkdir()
        spec = {
            "name": slug,
            "composite": f"{slug}_composite",
            "config": config,
            "outputs": ["results"],
        }
        producers = (inputs or {}).get(slug) or []
        if producers:
            spec["inputs"] = [
                {"artifact": f"a{n}", "from": p}
                for n, p in enumerate(producers)]
        (d / "study.yaml").write_text(yaml.safe_dump(spec))
    return ws


def _seed(store: ArtifactStore, artifact: str, payload: str,
          meta: dict) -> None:
    """Put an artifact at a literal address, bypassing the pipeline."""
    src = store.base.parent / f"_src_{artifact}"
    src.mkdir(parents=True, exist_ok=True)
    (src / "data.txt").write_text(payload)
    store.put(artifact, src, meta)


# --- the moving case --------------------------------------------------------

def test_a_float_spelled_artifact_moves_onto_its_int_twins_address(tmp_path):
    """The whole point: after migrating, the address the code now computes
    resolves to the bytes that were stored under the old one."""
    config = {"seed": 1.0, "rate": 0.5}
    ws = _workspace(tmp_path, {"alpha": config})
    store = ArtifactStore(ws)

    inputs = {"composite_id": "alpha_composite", "config": config,
              "input_ids": [], "commit": ""}
    old_id = legacy_artifact_id(**inputs)
    new_id = artifact_id(**inputs)
    assert old_id != new_id, "fixture must exercise a config that moves"

    _seed(store, old_id, "the payload", {"slug": "alpha", "stage": "results"})

    report = migrate_artifacts(ws)

    assert report.moved == [(old_id, new_id)]
    assert not report.orphaned
    assert store.has(new_id) and not store.has(old_id)
    assert (store.path(new_id) / "data.txt").read_text() == "the payload"


def test_an_int_spelled_artifact_does_not_move(tmp_path):
    """Six of the eight golden vectors are unchanged for a reason — most of
    the store is untouched, and the migration must not churn it."""
    config = {"seed": 1, "rate": 0.5}
    ws = _workspace(tmp_path, {"alpha": config})
    store = ArtifactStore(ws)

    address = artifact_id(composite_id="alpha_composite", config=config,
                          input_ids=[], commit="")
    _seed(store, address, "x", {"slug": "alpha", "stage": "results"})

    report = migrate_artifacts(ws)

    assert report.unchanged == [address]
    assert report.moved == []
    assert store.has(address)


# --- where the old address comes from ---------------------------------------

def test_recorded_address_inputs_are_used_when_present(tmp_path):
    """`meta.json`'s `address_inputs` re-keys an artifact the workspace can
    no longer explain — a study that was deleted, or one produced at an
    older commit. That is why the store now records them."""
    config = {"seed": 2.0}
    ws = _workspace(tmp_path, {})           # workspace declares NO studies
    store = ArtifactStore(ws)

    inputs = {"composite_id": "ghost_composite", "config": config,
              "input_ids": [], "commit": "deadbeef"}
    old_id = legacy_artifact_id(**inputs)
    _seed(store, old_id, "y",
          {"slug": "ghost", "stage": "results", "address_inputs": inputs})

    report = migrate_artifacts(ws)

    assert report.moved == [(old_id, artifact_id(**inputs))]
    assert not report.orphaned


def test_an_unexplainable_artifact_is_logged_not_deleted(tmp_path):
    """No recorded inputs and no study that explains it.

    It is left exactly where it is. An orphan costs a recompute on next use;
    deleting one that was still reachable costs the data — the asymmetry
    decides it.
    """
    ws = _workspace(tmp_path, {})
    store = ArtifactStore(ws)
    _seed(store, "0" * 16, "precious", {"slug": "who-knows"})

    report = migrate_artifacts(ws)

    assert report.orphaned == ["0" * 16]
    assert report.moved == []
    assert store.has("0" * 16)
    assert (store.path("0" * 16) / "data.txt").read_text() == "precious"


# --- safety properties ------------------------------------------------------

def test_migration_is_idempotent(tmp_path):
    config = {"seed": 1.0}
    ws = _workspace(tmp_path, {"alpha": config})
    store = ArtifactStore(ws)
    inputs = {"composite_id": "alpha_composite", "config": config,
              "input_ids": [], "commit": ""}
    _seed(store, legacy_artifact_id(**inputs), "z", {"slug": "alpha"})

    first = migrate_artifacts(ws)
    second = migrate_artifacts(ws)

    assert len(first.moved) == 1
    assert second.moved == []
    assert second.unchanged == [artifact_id(**inputs)]
    assert store.has(artifact_id(**inputs))


def test_dry_run_touches_nothing(tmp_path):
    config = {"seed": 1.0}
    ws = _workspace(tmp_path, {"alpha": config})
    store = ArtifactStore(ws)
    inputs = {"composite_id": "alpha_composite", "config": config,
              "input_ids": [], "commit": ""}
    old_id = legacy_artifact_id(**inputs)
    _seed(store, old_id, "z", {"slug": "alpha"})

    report = migrate_artifacts(ws, dry_run=True)

    assert report.moved == [(old_id, artifact_id(**inputs))]
    assert store.has(old_id), "dry run must not move anything"
    assert not store.has(artifact_id(**inputs))


def test_an_artifact_already_at_the_new_address_is_not_clobbered(tmp_path):
    """Both spellings were computed at some point, so both dirs exist. The
    new address already resolves, which is the outcome the migration wants —
    the old entry is reported, never silently overwritten or dropped."""
    config = {"seed": 1.0}
    ws = _workspace(tmp_path, {"alpha": config})
    store = ArtifactStore(ws)
    inputs = {"composite_id": "alpha_composite", "config": config,
              "input_ids": [], "commit": ""}
    old_id, new_id = legacy_artifact_id(**inputs), artifact_id(**inputs)

    _seed(store, old_id, "stale", {"slug": "alpha"})
    _seed(store, new_id, "current", {"slug": "alpha"})

    report = migrate_artifacts(ws)

    assert report.already_migrated == [old_id]
    assert report.moved == []
    assert (store.path(new_id) / "data.txt").read_text() == "current"
    assert store.has(old_id), "the old entry is reported, not destroyed"


def test_report_summary_names_the_orphans(tmp_path):
    ws = _workspace(tmp_path, {})
    store = ArtifactStore(ws)
    _seed(store, "a" * 16, "p", {"slug": "x"})

    text = migrate_artifacts(ws, dry_run=True).summary()

    assert "a" * 16 in text
    assert "orphaned" in text
    assert "recomputed on next use" in text


def test_store_ids_ignores_partial_entries(tmp_path):
    ws = _workspace(tmp_path, {})
    store = ArtifactStore(ws)
    _seed(store, "b" * 16, "p", {"slug": "x"})
    (store.base / ("c" * 16)).mkdir(parents=True)   # no meta.json

    assert store.ids() == ["b" * 16]


def test_rekey_is_a_no_op_when_there_is_nothing_to_move(tmp_path):
    ws = _workspace(tmp_path, {})
    store = ArtifactStore(ws)

    assert store.rekey("d" * 16, "e" * 16) is False
    assert store.rekey("f" * 16, "f" * 16) is False


def test_a_moving_producer_moves_its_consumer_too(tmp_path):
    """An address folds in its inputs' addresses.

    `up`'s config spells a whole number as a float, so `up` moves — and
    `down`'s address is a function of `up`'s, so `down` must move as well,
    onto an address computed from `up`'s NEW id. Mixing the new formula with
    legacy input ids would land it somewhere nothing ever looks.
    """
    ws = _workspace(
        tmp_path,
        {"up": {"seed": 1.0}, "down": {"rate": 0.5}},
        inputs={"down": ["up"]})
    store = ArtifactStore(ws)

    up_inputs = {"composite_id": "up_composite", "config": {"seed": 1.0},
                 "input_ids": [], "commit": ""}
    up_old, up_new = legacy_artifact_id(**up_inputs), artifact_id(**up_inputs)
    assert up_old != up_new

    down_old = legacy_artifact_id(
        composite_id="down_composite", config={"rate": 0.5},
        input_ids=[up_old], commit="")
    down_new = artifact_id(
        composite_id="down_composite", config={"rate": 0.5},
        input_ids=[up_new], commit="")

    _seed(store, up_old, "u", {"slug": "up"})
    _seed(store, down_old, "d", {"slug": "down"})

    report = migrate_artifacts(ws)

    assert sorted(report.moved) == sorted([(up_old, up_new),
                                           (down_old, down_new)])
    assert not report.orphaned
    assert store.has(up_new) and store.has(down_new)
    assert (store.path(down_new) / "data.txt").read_text() == "d"


def test_recorded_input_ids_are_remapped_through_the_move(tmp_path):
    """A consumer re-keyed from its own `meta.json` still has to follow its
    producer: the ids it recorded are the producer's *pre-migration*
    addresses."""
    ws = _workspace(tmp_path, {"up": {"seed": 1.0}})
    store = ArtifactStore(ws)

    up_inputs = {"composite_id": "up_composite", "config": {"seed": 1.0},
                 "input_ids": [], "commit": ""}
    up_old, up_new = legacy_artifact_id(**up_inputs), artifact_id(**up_inputs)
    _seed(store, up_old, "u", {"slug": "up"})

    # a consumer the workspace no longer declares, but which recorded itself
    recorded = {"composite_id": "gone_composite", "config": {},
                "input_ids": [up_old], "commit": ""}
    down_old = legacy_artifact_id(**recorded)
    _seed(store, down_old, "d",
          {"slug": "gone", "address_inputs": recorded})

    report = migrate_artifacts(ws)

    expected = artifact_id(**{**recorded, "input_ids": [up_new]})
    assert (down_old, expected) in report.moved
    assert not report.orphaned
