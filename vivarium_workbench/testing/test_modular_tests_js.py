from pathlib import Path

JS = (Path(__file__).resolve().parent.parent / "static" / "study-detail.js").read_text(encoding="utf-8")


def test_loadteststab_fills_report_card_mounts():
    assert "_fillReportCardModules" in JS
    # De-duplicated: the Tests tab no longer re-mounts the full card (it lives on
    # the Report Cards tab); _fillReportCardModules now recolours each row's
    # verdict pill instead.
    assert "report-card-verdict" in JS
    assert "report_card_urls" in JS
    assert "viz-embed" in JS               # the Report Cards tab still embeds cards
    # verdict -> pill colour mapping present
    for v in ("within_tol", "drift", "mismatch"):
        assert v in JS
