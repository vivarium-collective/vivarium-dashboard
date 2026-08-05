"""Expert-PDF search helper (Pass 10A of the findings protocol).

The findings walk (``/viva-study findings``) needs to surface candidate
quotes from a workspace's expert PDFs so the curator can attach
``expert_reference.quote`` entries without re-reading each PDF by hand.

This module owns the search side of that flow:

- ``search_expert_docs(ws_root, terms, max_hits=5)`` — case-insensitive
  substring search across every expert PDF declared in
  ``workspace.yaml.expert_docs[]``. Returns a list of
  ``{doc, page, snippet}`` dicts ranked by per-page hit count.

Implementation notes:

- PDFs are read with ``pypdf.PdfReader(...).pages[i].extract_text()``.
- The per-PDF page-text dict is cached *in-memory only* keyed by absolute
  path. The cache lives in module-global state, so a process that runs
  the findings walk many times in a row doesn't re-parse PDFs per term.
  We do NOT pickle the cache to disk — PDF parses are fast enough that
  the in-process cache is the right scope.
- Missing PDFs (path on disk not found, or pypdf raises) are logged as
  warnings and quietly produce no hits — never crash a findings walk.
- Snippet shape: ±100 chars around the match, with the match boundary
  kept verbatim. Newlines inside the snippet are normalized to spaces
  so a row in the dashboard's "candidate quotes" list renders on one line.

Ranking heuristic (rationale):

  Within each query term, results are first sorted by hits_on_page
  (descending) and then by (doc_name, page) (ascending) so the output is
  deterministic. Pages with more occurrences of the term are more likely
  to be a substantive discussion of the concept rather than a passing
  mention. Across terms, hits are returned in input-term order so the
  caller can attribute each block back to the term that produced it.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

import yaml


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory PDF page-text cache
# ---------------------------------------------------------------------------

# {abs-path-str: [page0_text, page1_text, ...]}
_PAGE_TEXT_CACHE: dict[str, list[str]] = {}


def _load_pdf_pages(path: Path) -> list[str]:
    """Return per-page text for ``path``, using the in-memory cache.

    Returns ``[]`` if the PDF can't be opened (missing file, parse error).
    """
    key = str(path.resolve())
    cached = _PAGE_TEXT_CACHE.get(key)
    if cached is not None:
        return cached
    if not path.is_file():
        _log.warning("expert_search: PDF not found: %s", path)
        _PAGE_TEXT_CACHE[key] = []
        return []
    try:
        import pypdf
    except ImportError as e:
        _log.warning("expert_search: pypdf not installed (%s); search disabled", e)
        _PAGE_TEXT_CACHE[key] = []
        return []
    try:
        reader = pypdf.PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages]
    except Exception as e:  # noqa: BLE001 — any pypdf failure should not crash the walk
        _log.warning("expert_search: failed to parse %s (%s)", path, e)
        pages = []
    _PAGE_TEXT_CACHE[key] = pages
    return pages


def clear_cache() -> None:
    """Drop the in-process PDF cache. Mainly for tests."""
    _PAGE_TEXT_CACHE.clear()


# ---------------------------------------------------------------------------
# Workspace expert_docs discovery
# ---------------------------------------------------------------------------


def _load_expert_docs(ws_root: Path) -> list[dict]:
    """Return ``workspace.yaml.expert_docs[]`` or [] if absent / malformed."""
    ws_yaml = ws_root / "workspace.yaml"
    if not ws_yaml.is_file():
        return []
    try:
        data = yaml.safe_load(ws_yaml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        _log.warning("expert_search: workspace.yaml parse error (%s)", e)
        return []
    docs = data.get("expert_docs") or []
    if not isinstance(docs, list):
        return []
    out: list[dict] = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        name = d.get("name")
        path = d.get("path")
        if not (isinstance(name, str) and isinstance(path, str)):
            continue
        out.append({"name": name, "path": path, "bib_key": d.get("bib_key")})
    return out


# ---------------------------------------------------------------------------
# Snippet construction
# ---------------------------------------------------------------------------


_SNIPPET_CONTEXT = 100  # chars on each side of the match


def _make_snippet(page_text: str, match_start: int, match_end: int) -> str:
    lo = max(0, match_start - _SNIPPET_CONTEXT)
    hi = min(len(page_text), match_end + _SNIPPET_CONTEXT)
    raw = page_text[lo:hi]
    # Collapse internal whitespace to single spaces for one-line rendering.
    snippet = re.sub(r"\s+", " ", raw).strip()
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(page_text) else ""
    return f"{prefix}{snippet}{suffix}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_expert_docs(
    ws_root: Path,
    terms: Iterable[str],
    *,
    max_hits: int = 5,
) -> list[dict]:
    """Search every expert PDF for any term in ``terms``.

    Args:
        ws_root: Workspace root (the directory holding ``workspace.yaml``).
        terms:   Iterable of search terms (case-insensitive substring match).
        max_hits: Maximum number of hits returned PER term.

    Returns:
        Flat list of hit dicts shaped::

            {"doc": "<expert_doc.name>",
             "page": 12,                  # 1-indexed
             "snippet": "…match snippet…",
             "term": "<the matching term>"}

        Hits are ordered: outer = input term order; inner = hits_on_page
        (descending) then doc.name, page (ascending) for determinism.
    """
    ws_root = Path(ws_root)
    docs = _load_expert_docs(ws_root)
    if not docs:
        return []

    term_list = [t for t in (terms or []) if t]
    if not term_list:
        return []

    out: list[dict] = []
    for term in term_list:
        per_term: list[tuple[int, str, int, str]] = []  # (hits, doc_name, page_1idx, snippet)
        pat = re.compile(re.escape(term), re.IGNORECASE)
        for doc in docs:
            doc_name = doc["name"]
            doc_path = (ws_root / doc["path"]).resolve()
            pages = _load_pdf_pages(doc_path)
            for page_idx, page_text in enumerate(pages):
                if not page_text:
                    continue
                matches = list(pat.finditer(page_text))
                if not matches:
                    continue
                # One representative snippet per page (around the first hit);
                # the per-page hit-count is what drives ranking.
                first = matches[0]
                snippet = _make_snippet(page_text, first.start(), first.end())
                per_term.append((len(matches), doc_name, page_idx + 1, snippet))
        # Rank: higher hit-count first, then doc/page ascending for stability.
        per_term.sort(key=lambda row: (-row[0], row[1], row[2]))
        for _hits, doc_name, page, snippet in per_term[:max_hits]:
            out.append({
                "doc": doc_name,
                "page": page,
                "snippet": snippet,
                "term": term,
            })

    return out
