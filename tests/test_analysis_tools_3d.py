from vivarium_workbench.lib import analysis_tools_3d as a3


def test_studies_with_3d_pack_from_disk(monkeypatch):
    monkeypatch.setattr(a3, "build_saved_visualizations", lambda ws: {
        "saved": [
            {"study": "ecoli-3d", "name": "initial",
             "pack_url": "/files/studies/ecoli-3d/viz/3d/initial.pack.json"},
            {"study": "ecoli-3d", "name": "division",
             "pack_url": "/files/studies/ecoli-3d/viz/3d/division.pack.json"},
        ]})
    monkeypatch.setattr(a3, "_hosted_viewer_urls", lambda ws: {})
    studies = a3.studies_with_3d_pack("/ws")
    s = {x["study"]: x for x in studies}["ecoli-3d"]
    assert [p["name"] for p in s["packs"]] == ["initial", "division"]


def test_manifest_default_initial_first(monkeypatch):
    monkeypatch.setattr(a3, "studies_with_3d_pack", lambda ws: [
        {"study": "ecoli-3d", "packs": [
            {"name": "division", "file": "/a/division.pack.json"},
            {"name": "initial", "file": "/a/initial.pack.json"}]}])
    manifest = a3.study_models_manifest("/ws", "ecoli-3d")
    # 'initial' snapshot is ordered first when present
    assert manifest[0]["name"] == "initial"


def test_hosted_viewer_url_attaches(monkeypatch):
    monkeypatch.setattr(a3, "build_saved_visualizations", lambda ws: {"saved": []})
    monkeypatch.setattr(a3, "_hosted_viewer_urls",
        lambda ws: {"ecoli-3d": "https://r2/viewer?models=..."})
    studies = {x["study"]: x for x in a3.studies_with_3d_pack("/ws")}
    assert studies["ecoli-3d"]["viewer_url"].startswith("https://r2")


def test_hosted_key_by_pack_name_does_not_duplicate_study(monkeypatch):
    # ui.viz_viewer_urls keyed by PACK NAME (ecoli_3d) for a disk pack owned by
    # study slug ecoli-3d must produce ONE card with the hosted URL attached,
    # not a phantom duplicate keyed by the pack name.
    monkeypatch.setattr(a3, "build_saved_visualizations", lambda ws: {
        "saved": [
            {"study": "ecoli-3d", "name": "ecoli_3d",
             "pack_url": "/files/studies/ecoli-3d/viz/3d/ecoli_3d.pack.json"},
        ]})
    monkeypatch.setattr(a3, "_hosted_viewer_urls",
        lambda ws: {"ecoli_3d": "https://r2/viewer?models=..."})
    studies = a3.studies_with_3d_pack("/ws")
    assert [s["study"] for s in studies] == ["ecoli-3d"]  # exactly one, no phantom
    assert studies[0]["viewer_url"].startswith("https://r2")
    assert [p["name"] for p in studies[0]["packs"]] == ["ecoli_3d"]
