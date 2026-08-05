"""Tests for vivarium_workbench.lib.citation_gaps — investigation references x uncited bands."""
from pathlib import Path

import pytest
import yaml

import json

from vivarium_workbench.lib.citation_gaps import investigation_citation_gaps, main


# --------------------------------------------------------------------------- #
# Fixtures: build a minimal nested workspace on disk.
# --------------------------------------------------------------------------- #
def _make_ws(tmp_path: Path, *, studies: dict, references: list[str], study_slugs=None):
    """Create a workspace with one investigation `the-inv` and member studies.

    `studies` maps study_slug -> study.yaml spec dict.
    `study_slugs` overrides the investigation.yaml `studies:` membership list
    (defaults to the keys of `studies`).
    """
    (tmp_path / "workspace.yaml").write_text("name: demo\n", encoding="utf-8")
    inv = tmp_path / "investigations" / "the-inv"
    inv.mkdir(parents=True)
    members = list(studies) if study_slugs is None else list(study_slugs)
    inv_spec = {
        "name": "the-inv",
        "studies": members,
        "inputs": {"references": list(references)},
    }
    (inv / "investigation.yaml").write_text(yaml.safe_dump(inv_spec), encoding="utf-8")
    sroot = inv / "studies"
    for slug, spec in studies.items():
        sd = sroot / slug
        sd.mkdir(parents=True)
        (sd / "study.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    return tmp_path


def _band_test(name, *, cites=None):
    t = {"name": name, "pass_if": {"low": 300, "high": 800}}
    if cites is not None:
        t["cites"] = cites
    return t


def test_gaps_surfaces_uncited_bands_x_investigation_refs(tmp_path):
    ws = _make_ws(
        tmp_path,
        studies={
            "the-study": {
                "behavior_tests": [_band_test("the-uncited-band")],
            }
        },
        references=["ref-a", "ref-b"],
    )
    gaps = investigation_citation_gaps(ws, "the-inv")
    assert "the-study" in gaps
    g = gaps["the-study"]
    assert any(b["test"] == "the-uncited-band" for b in g["uncited_bands"])
    assert set(g["available_references"]) == {"ref-a", "ref-b"}


def test_no_gaps_when_all_bands_cited(tmp_path):
    ws = _make_ws(
        tmp_path,
        studies={
            "the-study": {
                "behavior_tests": [_band_test("cited-band", cites=["ref-a"])],
            }
        },
        references=["ref-a"],
    )
    gaps = investigation_citation_gaps(ws, "the-inv")
    assert all(not g["uncited_bands"] for g in gaps.values())


def test_empty_when_no_member_studies(tmp_path):
    (tmp_path / "workspace.yaml").write_text("name: demo\n", encoding="utf-8")
    inv = tmp_path / "investigations" / "the-inv"
    inv.mkdir(parents=True)
    (inv / "investigation.yaml").write_text(
        yaml.safe_dump({"name": "the-inv", "studies": [], "inputs": {"references": ["r"]}}),
        encoding="utf-8",
    )
    assert investigation_citation_gaps(tmp_path, "the-inv") == {}


def test_best_effort_skips_bad_study_yaml(tmp_path):
    ws = _make_ws(
        tmp_path,
        studies={"good": {"behavior_tests": [_band_test("b1")]}},
        references=["ref-a"],
        study_slugs=["good", "missing-on-disk"],
    )
    # `missing-on-disk` is listed in the investigation but has no study.yaml.
    gaps = investigation_citation_gaps(ws, "the-inv")
    assert "good" in gaps
    assert "missing-on-disk" not in gaps


def test_main_prints_json_gaps(tmp_path, capsys):
    ws = _make_ws(
        tmp_path,
        studies={"the-study": {"behavior_tests": [_band_test("the-uncited-band")]}},
        references=["ref-a", "ref-b"],
    )
    rc = main(["--workspace", str(ws), "--investigation", "the-inv"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "the-study" in out
    assert set(out["the-study"]["available_references"]) == {"ref-a", "ref-b"}
    assert any(b["test"] == "the-uncited-band" for b in out["the-study"]["uncited_bands"])


V2E_INVEST = Path("/Users/eranagmon/code/v2e-invest")


@pytest.mark.skipif(not V2E_INVEST.is_dir(), reason="v2e-invest workspace absent")
def test_golden_v2e_invest_dnaa_replication():
    """READ-ONLY golden against the real dnaa-replication investigation."""
    inv_dir = V2E_INVEST / "workspace" / "investigations" / "dnaa-replication"
    study_yamls = list((inv_dir / "studies").glob("*/study.yaml"))
    before = {p: p.read_bytes() for p in study_yamls}

    gaps = investigation_citation_gaps(V2E_INVEST, "dnaa-replication")

    # Dict keyed by real member studies.
    assert isinstance(gaps, dict) and gaps
    assert "dnaa-1-expression" in gaps

    # available_references include the investigation's real bib_keys.
    refs = gaps["dnaa-1-expression"]["available_references"]
    assert "dnaa-abundance-jb-1991" in refs

    # Valid structure throughout.
    for slug, g in gaps.items():
        assert isinstance(slug, str)
        assert set(g) == {"uncited_bands", "available_references"}
        assert isinstance(g["available_references"], list)
        for band in g["uncited_bands"]:
            assert "test" in band and isinstance(band["test"], str)

    # No writes to v2e-invest.
    after = {p: p.read_bytes() for p in study_yamls}
    assert after == before


def test_pure_read_writes_nothing(tmp_path):
    ws = _make_ws(
        tmp_path,
        studies={"the-study": {"behavior_tests": [_band_test("the-uncited-band")]}},
        references=["ref-a"],
    )
    sy = ws / "investigations" / "the-inv" / "studies" / "the-study" / "study.yaml"
    before = sy.read_bytes()
    investigation_citation_gaps(ws, "the-inv")
    assert sy.read_bytes() == before
