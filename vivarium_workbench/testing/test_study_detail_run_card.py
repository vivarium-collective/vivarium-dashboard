from pathlib import Path

_PKG = Path(__file__).parent.parent
JS = (_PKG / "static" / "study-detail.js").read_text()
HTML = (_PKG / "templates" / "study-detail.html").read_text()


def test_run_card_wired():
    """Task 8 (Simulations declutter): the Simulate-tab #reproduce-card /
    _renderReproduceCard run_commands-driven CLI-copy-chip UI was removed by
    design. Reproduce still exists — relocated to the header #study-reproduce
    button, which replays the study's latest run via POST
    /api/study-reproduce (not the old run_commands chips)."""
    assert 'id="reproduce-card"' not in HTML
    assert "_renderReproduceCard" not in JS
    assert "run_commands" not in JS
    assert 'id="study-reproduce"' in HTML
    assert "/api/study-reproduce" in JS
