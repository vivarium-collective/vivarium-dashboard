from pathlib import Path
from vivarium_workbench.lib.artifacts.store import ArtifactStore


def _mk(tmp_path, data, name="src.bin"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_put_get_has_and_idempotent(tmp_path):
    src = tmp_path / "sim_data.bin"; src.write_bytes(b"PARCA")
    st = ArtifactStore(tmp_path)
    assert not st.has("aaaa000000000000")
    p = st.put("aaaa000000000000", src, {"producer_study": "parca", "kind": "sim_data"})
    assert st.has("aaaa000000000000")
    assert p.read_bytes() == b"PARCA"
    assert st.meta("aaaa000000000000")["producer_study"] == "parca"
    # second put is a store hit (no overwrite, no error)
    src.write_bytes(b"DIFFERENT")
    st.put("aaaa000000000000", src, {"producer_study": "parca"})
    assert st.path("aaaa000000000000").read_bytes() == b"PARCA"

def test_store_lives_under_pbg_artifacts(tmp_path):
    st = ArtifactStore(tmp_path)
    st.put("bbbb000000000000", _mk(tmp_path, b"x", name="other.bin"), {})
    assert (tmp_path / ".pbg" / "artifacts" / "bbbb000000000000").is_dir()

def test_directory_payload_roundtrip_and_idempotent(tmp_path):
    src = tmp_path / "sim_data_cache"
    src.mkdir()
    (src / "a.txt").write_text("A")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_text("B")
    st = ArtifactStore(tmp_path)
    p = st.put("cccc000000000000", src, {"kind": "sim_data"})
    assert st.has("cccc000000000000")
    assert p.is_dir()
    assert (p / "a.txt").read_text() == "A"
    assert (p / "sub" / "b.txt").read_text() == "B"
    # store hit: second put with mutated src does not overwrite
    (src / "a.txt").write_text("CHANGED")
    st.put("cccc000000000000", src, {"kind": "sim_data"})
    assert (st.path("cccc000000000000") / "a.txt").read_text() == "A"
