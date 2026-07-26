import sqlite3

import pytest
import yaml

from vivarium_workbench.lib.artifacts.pipeline import resolve_study


def make_stub():
    calls = []

    def stub(ws_root, slug, *, artifact_id, composite, config, input_ids, out_dir):
        calls.append(slug)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "out.bin"
        p.write_bytes(b"fake:" + slug.encode())
        return p

    return stub, calls


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "studies" / "parca").mkdir(parents=True)
    (tmp_path / "studies" / "ko").mkdir(parents=True)
    (tmp_path / "studies" / "parca" / "study.yaml").write_text(yaml.safe_dump({
        "name": "parca",
        "composite": "parca_builder",
        "config": {},
        "outputs": ["sim_data"],
    }))
    (tmp_path / "studies" / "ko" / "study.yaml").write_text(yaml.safe_dump({
        "name": "ko",
        "composite": "baseline",
        "config": {"seed": 0},
        "inputs": [{"artifact": "sim_data", "from": "parca"}],
        "outputs": ["run_zarr"],
    }))
    return tmp_path


def _write_ko_config(ws, config):
    (ws / "studies" / "ko" / "study.yaml").write_text(yaml.safe_dump({
        "name": "ko",
        "composite": "baseline",
        "config": config,
        "inputs": [{"artifact": "sim_data", "from": "parca"}],
        "outputs": ["run_zarr"],
    }))


def test_resolves_producer_first_and_computes_once(ws):
    stub, calls = make_stub()
    r = resolve_study(ws, "ko", compute_fn=stub)
    assert calls == ["parca", "ko"]
    assert r["cached"] is False
    assert set(r["inputs"].keys()) == {"parca"}


def test_second_resolve_is_all_store_hits(ws):
    stub, calls = make_stub()
    r = resolve_study(ws, "ko", compute_fn=stub)

    stub2, calls2 = make_stub()
    r2 = resolve_study(ws, "ko", compute_fn=stub2)
    assert calls2 == []
    assert r2["cached"] is True
    assert r2["inputs"]["parca"] == r["inputs"]["parca"]


def test_config_change_reruns_only_that_study(ws):
    stub, calls = make_stub()
    resolve_study(ws, "ko", compute_fn=stub)

    _write_ko_config(ws, {"seed": 1})

    stub3, calls3 = make_stub()
    resolve_study(ws, "ko", compute_fn=stub3)
    assert calls3 == ["ko"]


def test_runs_db_pointer_recorded(ws):
    stub, calls = make_stub()
    r = resolve_study(ws, "ko", compute_fn=stub)

    conn = sqlite3.connect(str(ws / "studies" / "ko" / "runs.db"))
    try:
        row = conn.execute(
            "SELECT stage, artifact_id FROM artifact_pointers WHERE stage = ?",
            ("run_zarr",),
        ).fetchone()
    finally:
        conn.close()
    assert row == ("run_zarr", r["artifact_id"])


def test_producer_output_id_is_stable(ws):
    stub, calls = make_stub()
    r = resolve_study(ws, "ko", compute_fn=stub)

    stub_parca, _ = make_stub()
    r_parca = resolve_study(ws, "parca", compute_fn=stub_parca)
    assert r_parca["artifact_id"] == r["inputs"]["parca"]
