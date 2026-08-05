"""Tests for vivarium_workbench.lib.expert_search (Pass 10A findings helper).

The expert-PDF search powers the ``/viva-study findings`` walk's
"candidate quotes" step. These tests exercise:

  - workspace.yaml discovery of expert_docs[]
  - term ranking across pages (more hits = higher rank)
  - per-term max_hits cap
  - case-insensitive substring matching
  - in-memory page cache (parsed once per process)
  - graceful handling of a missing PDF on disk
  - graceful handling of a workspace with no expert_docs[]

PDFs are hard to author without a heavy dep, so we monkeypatch the
module's page-text cache directly to simulate parsed PDFs. The actual
pypdf path is exercised by integration in real workspaces.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vivarium_workbench.lib import expert_search


@pytest.fixture(autouse=True)
def _clear_cache():
    expert_search.clear_cache()
    yield
    expert_search.clear_cache()


def _make_workspace(tmp_path: Path, expert_docs: list[dict]) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    ws_yaml = {
        "schema_version": 2,
        "name": "test-ws",
        "created": "2026-05-17",
        "plugin_version": "0.9.0",
        "package_path": "pkg",
        "expert_docs": expert_docs,
    }
    (ws / "workspace.yaml").write_text(yaml.safe_dump(ws_yaml, sort_keys=False))
    return ws


def _prime_cache(ws_root: Path, doc_rel_path: str, pages: list[str]) -> Path:
    """Drop a fake parsed-PDF entry into the in-memory cache."""
    abs_path = (ws_root / doc_rel_path).resolve()
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    # Create a sentinel file so _load_pdf_pages's exists-check passes;
    # the cache short-circuits before pypdf is ever called.
    abs_path.write_bytes(b"%PDF-1.4\n%fake test sentinel\n")
    expert_search._PAGE_TEXT_CACHE[str(abs_path)] = pages
    return abs_path


# ---------------------------------------------------------------------------
# Empty / missing workspace
# ---------------------------------------------------------------------------


def test_returns_empty_when_no_workspace_yaml(tmp_path):
    bare = tmp_path / "no-ws"
    bare.mkdir()
    assert expert_search.search_expert_docs(bare, ["dnaa"]) == []


def test_returns_empty_when_no_expert_docs(tmp_path):
    ws = _make_workspace(tmp_path, [])
    assert expert_search.search_expert_docs(ws, ["dnaa"]) == []


def test_returns_empty_when_no_terms(tmp_path):
    ws = _make_workspace(
        tmp_path,
        [{"name": "doc-a", "path": "references/expert/doc-a.pdf"}],
    )
    _prime_cache(ws, "references/expert/doc-a.pdf", ["DnaA autoregulation"])
    assert expert_search.search_expert_docs(ws, []) == []
    assert expert_search.search_expert_docs(ws, [""]) == []


# ---------------------------------------------------------------------------
# Match and snippet
# ---------------------------------------------------------------------------


def test_basic_substring_match_returns_doc_page_snippet(tmp_path):
    ws = _make_workspace(
        tmp_path,
        [{"name": "doc-a", "path": "references/expert/doc-a.pdf"}],
    )
    _prime_cache(
        ws,
        "references/expert/doc-a.pdf",
        [
            "irrelevant page one with no hits",
            "DnaA binding at the dnaAp1 promoter represses dnaA transcription.",
        ],
    )
    hits = expert_search.search_expert_docs(ws, ["dnaA"])
    assert len(hits) == 1
    h = hits[0]
    assert h["doc"] == "doc-a"
    assert h["page"] == 2  # 1-indexed
    assert h["term"] == "dnaA"
    assert "DnaA" in h["snippet"] or "dnaA" in h["snippet"]
    assert "promoter" in h["snippet"]


def test_match_is_case_insensitive(tmp_path):
    ws = _make_workspace(
        tmp_path,
        [{"name": "doc", "path": "references/expert/d.pdf"}],
    )
    _prime_cache(ws, "references/expert/d.pdf", ["DNAA ATP CYCLE"])
    hits = expert_search.search_expert_docs(ws, ["dnaa atp"])
    assert len(hits) == 1
    assert hits[0]["doc"] == "doc"


# ---------------------------------------------------------------------------
# Ranking: per-page hit count drives rank
# ---------------------------------------------------------------------------


def test_pages_with_more_hits_rank_higher(tmp_path):
    ws = _make_workspace(
        tmp_path,
        [{"name": "doc-a", "path": "references/expert/doc-a.pdf"}],
    )
    _prime_cache(
        ws,
        "references/expert/doc-a.pdf",
        [
            # page 1: 1 hit
            "DnaA appears once on this page.",
            # page 2: 3 hits
            "DnaA boxes, DnaA-ATP, DnaA-ADP all discussed extensively here.",
            # page 3: 0 hits
            "Nothing matching here.",
        ],
    )
    hits = expert_search.search_expert_docs(ws, ["dnaa"])
    # 2 pages produce hits; page 2 ranks first because it has more hits.
    assert [h["page"] for h in hits] == [2, 1]


def test_max_hits_caps_per_term(tmp_path):
    ws = _make_workspace(
        tmp_path,
        [{"name": "doc-a", "path": "references/expert/doc-a.pdf"}],
    )
    _prime_cache(
        ws,
        "references/expert/doc-a.pdf",
        ["DnaA on page one.", "DnaA on page two.", "DnaA on page three.", "DnaA on page four."],
    )
    hits = expert_search.search_expert_docs(ws, ["dnaa"], max_hits=2)
    assert len(hits) == 2


# ---------------------------------------------------------------------------
# Multiple terms / multiple docs
# ---------------------------------------------------------------------------


def test_multiple_terms_each_get_their_block(tmp_path):
    ws = _make_workspace(
        tmp_path,
        [{"name": "doc-a", "path": "references/expert/doc-a.pdf"}],
    )
    _prime_cache(
        ws,
        "references/expert/doc-a.pdf",
        [
            "DnaA discussion on page one.",
            "Autorepression mechanism on page two.",
        ],
    )
    hits = expert_search.search_expert_docs(ws, ["dnaa", "autorepression"])
    # Each term yields one hit; outer order = input term order.
    assert [h["term"] for h in hits] == ["dnaa", "autorepression"]


def test_multiple_docs_each_searched(tmp_path):
    ws = _make_workspace(
        tmp_path,
        [
            {"name": "doc-a", "path": "references/expert/doc-a.pdf"},
            {"name": "doc-b", "path": "references/expert/doc-b.pdf"},
        ],
    )
    _prime_cache(ws, "references/expert/doc-a.pdf", ["DnaA on a"])
    _prime_cache(ws, "references/expert/doc-b.pdf", ["DnaA on b"])
    hits = expert_search.search_expert_docs(ws, ["dnaa"])
    docs = sorted({h["doc"] for h in hits})
    assert docs == ["doc-a", "doc-b"]


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


def test_cache_avoids_re_parsing_on_repeat_calls(tmp_path, monkeypatch):
    """Two calls with the same workspace must hit the page-text cache."""
    ws = _make_workspace(
        tmp_path,
        [{"name": "doc-a", "path": "references/expert/doc-a.pdf"}],
    )
    _prime_cache(ws, "references/expert/doc-a.pdf", ["DnaA page"])

    # Spy: force any call into pypdf to fail loudly. Cache hits don't touch pypdf.
    sentinel: list[int] = []

    def boom(*a, **k):
        sentinel.append(1)
        raise RuntimeError("cache miss — pypdf should not have been called")

    monkeypatch.setattr("pypdf.PdfReader", boom)

    a = expert_search.search_expert_docs(ws, ["dnaa"])
    b = expert_search.search_expert_docs(ws, ["dnaa"])
    assert a and b
    assert sentinel == []


# ---------------------------------------------------------------------------
# Graceful failure: missing PDF on disk
# ---------------------------------------------------------------------------


def test_missing_pdf_does_not_crash_and_yields_no_hits(tmp_path):
    ws = _make_workspace(
        tmp_path,
        [{"name": "missing-doc", "path": "references/expert/does-not-exist.pdf"}],
    )
    # No sentinel file — _load_pdf_pages should warn and return [].
    hits = expert_search.search_expert_docs(ws, ["dnaa"])
    assert hits == []


def test_one_missing_one_present_still_returns_present_hits(tmp_path):
    ws = _make_workspace(
        tmp_path,
        [
            {"name": "missing", "path": "references/expert/missing.pdf"},
            {"name": "doc-a", "path": "references/expert/doc-a.pdf"},
        ],
    )
    _prime_cache(ws, "references/expert/doc-a.pdf", ["DnaA on page"])
    hits = expert_search.search_expert_docs(ws, ["dnaa"])
    assert len(hits) == 1
    assert hits[0]["doc"] == "doc-a"
