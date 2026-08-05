"""Tests for vivarium_workbench.lib.generation (coordinated-generation model)."""
from datetime import datetime, timezone

import pytest

from vivarium_workbench.lib import generation as gen


def test_new_generation_id_shape_and_uniqueness():
    a = gen.new_generation_id()
    b = gen.new_generation_id()
    assert gen.is_generation_id(a)
    assert gen.is_generation_id(b)
    assert a != b  # the random suffix differs


def test_new_generation_id_is_sortable_by_time():
    early = gen.new_generation_id(datetime(2026, 5, 21, 8, 0, 0, tzinfo=timezone.utc))
    late = gen.new_generation_id(datetime(2026, 5, 21, 9, 0, 0, tzinfo=timezone.utc))
    assert early < late  # lexical sort == chronological sort


def test_is_generation_id_rejects_junk():
    assert not gen.is_generation_id("")
    assert not gen.is_generation_id("gen-bad")
    assert not gen.is_generation_id("20260521T080000Z-abc123")  # missing prefix


def test_compute_param_set_hash_dict_is_order_independent():
    h1 = gen.compute_param_set_hash({"a": 1, "b": 2})
    h2 = gen.compute_param_set_hash({"b": 2, "a": 1})
    assert h1 == h2
    assert len(h1) == 12


def test_compute_param_set_hash_distinguishes_values():
    assert gen.compute_param_set_hash({"te": 1}) != gen.compute_param_set_hash({"te": 20})


def test_compute_param_set_hash_str_and_bytes_and_path(tmp_path):
    text = "translation_efficiency: 1\n"
    h_str = gen.compute_param_set_hash(text)
    h_bytes = gen.compute_param_set_hash(text.encode())
    p = tmp_path / "params.yaml"
    p.write_text(text)
    h_path = gen.compute_param_set_hash(p)
    assert h_str == h_bytes == h_path


def test_start_generation_writes_manifest_and_current_pointer(tmp_path):
    g = gen.start_generation(
        tmp_path,
        git_sha_value="d146458",
        param_set={"translation_efficiency": 1},
        composite_versions={"v2ecoli.composites.baseline.baseline": "v1"},
        label="round-1 rerun",
    )
    assert gen.is_generation_id(g.generation_id)
    assert g.git_sha == "d146458"
    assert g.param_set_hash is not None
    assert g.label == "round-1 rerun"
    # Manifest + current pointer both written.
    assert (tmp_path / ".pbg" / "generations" / f"{g.generation_id}.json").is_file()
    assert gen.current_generation_id(tmp_path) == g.generation_id


def test_start_generation_make_current_false(tmp_path):
    g = gen.start_generation(tmp_path, make_current=False)
    assert gen.read_generation(tmp_path, g.generation_id) is not None
    assert gen.current_generation_id(tmp_path) is None


def test_read_generation_round_trips(tmp_path):
    g = gen.start_generation(tmp_path, git_sha_value="abc", label="x")
    loaded = gen.read_generation(tmp_path, g.generation_id)
    assert loaded is not None
    assert loaded.generation_id == g.generation_id
    assert loaded.git_sha == "abc"
    assert loaded.label == "x"


def test_read_generation_missing_returns_none(tmp_path):
    assert gen.read_generation(tmp_path, "gen-20260521T080000Z-aaaaaa") is None


def test_current_generation_id_none_when_absent(tmp_path):
    assert gen.current_generation_id(tmp_path) is None
    assert gen.current_generation(tmp_path) is None


def test_record_run_appends_and_is_idempotent(tmp_path):
    g = gen.start_generation(tmp_path)
    gen.record_run(tmp_path, g.generation_id, study="dnaa-00", run_id="r1", sim_name="baseline")
    gen.record_run(tmp_path, g.generation_id, study="dnaa-00", run_id="r2", sim_name="fast")
    # Re-recording r1 must not duplicate it.
    gen.record_run(tmp_path, g.generation_id, study="dnaa-00", run_id="r1", sim_name="baseline")
    reloaded = gen.read_generation(tmp_path, g.generation_id)
    run_ids = [r["run_id"] for r in reloaded.runs]
    assert run_ids == ["r1", "r2"]
    assert reloaded.runs[0] == {"study": "dnaa-00", "run_id": "r1", "sim_name": "baseline"}


def test_record_run_missing_manifest_returns_none(tmp_path):
    assert gen.record_run(tmp_path, "gen-20260521T080000Z-aaaaaa",
                          study="s", run_id="r") is None


def test_set_current_generation_switches_pointer(tmp_path):
    g1 = gen.start_generation(tmp_path)
    g2 = gen.start_generation(tmp_path, make_current=False)
    assert gen.current_generation_id(tmp_path) == g1.generation_id
    gen.set_current_generation(tmp_path, g2.generation_id)
    assert gen.current_generation_id(tmp_path) == g2.generation_id


def test_list_generations_newest_first(tmp_path):
    g1 = gen.start_generation(
        tmp_path, now=datetime(2026, 5, 21, 8, 0, 0, tzinfo=timezone.utc))
    g2 = gen.start_generation(
        tmp_path, now=datetime(2026, 5, 21, 9, 0, 0, tzinfo=timezone.utc))
    listed = [g.generation_id for g in gen.list_generations(tmp_path)]
    assert listed == [g2.generation_id, g1.generation_id]


def test_is_stale_logic():
    cur = "gen-20260521T090000Z-bbbbbb"
    old = "gen-20260521T080000Z-aaaaaa"
    # Same generation → fresh.
    assert gen.is_stale(cur, cur) is False
    # Older generation → stale.
    assert gen.is_stale(old, cur) is True
    # No generation on the run, but a current exists → stale (predates model).
    assert gen.is_stale(None, cur) is True
    # No current generation at all → concept N/A, nothing stale.
    assert gen.is_stale(old, None) is False
    assert gen.is_stale(None, None) is False
