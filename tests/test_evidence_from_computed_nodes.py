"""Phase 2d: evidence chain sourced from computed report-card verdicts."""
import json

from vivarium_workbench.lib.chain_derivation import lift_report_card_findings


# --- unit: the pure lifter ---------------------------------------------------

def test_lift_report_card_findings_full_chain():
    findings = [{"id": "report-card-standard",
                 "statement": "cell mass: within tolerance",
                 "status": "confirms", "evidence": {"observed": "5 ✓"}}]
    nodes = lift_report_card_findings(findings, "s1")
    assert set(nodes) == {"finding/derived-s1-rc0", "evidence/derived-s1-rc0",
                          "decision/derived-s1-rc0", "conclusion/derived-s1-rc0"}
    f = nodes["finding/derived-s1-rc0"]
    assert f["statement"] == "cell mass: within tolerance"
    assert f["runs"] == ["run/s1"]
    assert nodes["evidence/derived-s1-rc0"]["lifecycle_state"] == "accepted"
    assert nodes["evidence/derived-s1-rc0"]["statement"] == "5 ✓"
    assert nodes["decision/derived-s1-rc0"]["outcome"] == "accept"
    assert f["provenance"]["tool"] == "2d/report-card-evidence"


def test_lift_report_card_findings_ungraded_is_finding_only():
    # ungraded -> status "novel" -> no verdict -> Finding + Evidence only
    findings = [{"id": "report-card-x", "statement": "x", "status": "novel",
                 "evidence": {"summary": "s"}}]
    nodes = lift_report_card_findings(findings, "s1")
    assert set(nodes) == {"finding/derived-s1-rc0", "evidence/derived-s1-rc0"}
    assert nodes["evidence/derived-s1-rc0"]["lifecycle_state"] == "proposed"


def test_lift_report_card_findings_non_list():
    assert lift_report_card_findings(None, "s1") == {}
    assert lift_report_card_findings([], "s1") == {}


# --- end-to-end: precedence in the investigation graph -----------------------

def _ws(tmp_path, study_yaml):
    (tmp_path / "workspace.yaml").write_text("name: test_ws\n", encoding="utf-8")
    inv = tmp_path / "investigations" / "inv1"
    inv.mkdir(parents=True)
    (inv / "investigation.yaml").write_text("members: [s1]\n", encoding="utf-8")
    sd = tmp_path / "studies" / "s1"
    (sd / "viz" / "report_card").mkdir(parents=True)
    (sd / "study.yaml").write_text(study_yaml, encoding="utf-8")
    return sd


def _chain_ids(chain):
    return {n["id"] for n in chain["nodes"]}


def test_graph_uses_computed_report_card_when_no_authored(tmp_path):
    from vivarium_workbench.lib.investigation_graph_views import build_investigation_graph
    sd = _ws(tmp_path, "name: s1\nquestion: does it hold?\n")   # NO findings/conclusion_verdicts
    rc = sd / "viz" / "report_card"
    rc.joinpath("standard.html").write_text("<div>card</div>" * 10, encoding="utf-8")
    rc.joinpath("standard.verdict.json").write_text(
        json.dumps({"overall": "within_tol"}), encoding="utf-8")

    result, code = build_investigation_graph(tmp_path, "inv1")
    assert code == 200
    chain = result["chains"]["s1"]
    assert chain["derived"] is True
    ids = _chain_ids(chain)
    assert "finding/derived-s1-rc0" in ids       # computed report-card evidence
    assert "evidence/derived-s1-rc0" in ids
    assert chain["violations"] == []             # a sound chain (validate_chain)


def test_authored_findings_win_over_computed(tmp_path):
    from vivarium_workbench.lib.investigation_graph_views import build_investigation_graph
    # authored v4 findings list present -> derive_chain_nodes wins; no -rc nodes
    sd = _ws(
        tmp_path,
        "name: s1\nfindings:\n"
        "- statement: authored claim\n  status: confirms\n"
        "  evidence:\n    observed: authored basis\n",
    )
    rc = sd / "viz" / "report_card"
    rc.joinpath("standard.html").write_text("<div>card</div>" * 10, encoding="utf-8")
    rc.joinpath("standard.verdict.json").write_text(
        json.dumps({"overall": "mismatch"}), encoding="utf-8")

    result, code = build_investigation_graph(tmp_path, "inv1")
    assert code == 200
    ids = _chain_ids(result["chains"]["s1"])
    assert "finding/derived-s1-fl0" in ids       # authored path used
    assert not any(i.endswith("-rc0") for i in ids)   # computed NOT mixed in
