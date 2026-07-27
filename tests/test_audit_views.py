"""Tests for the read-only L0-L5 audit view (`lib/audit_views.build_audit`).

The FastAPI app import hits a pre-existing, unrelated
``process_bigraph.composite_spec`` ModuleNotFoundError in this environment, so
the endpoint cannot be exercised via the ``dashboard_client`` fixture here. We
therefore test the library function directly (the route is a thin
``JSONResponse(build_audit(ws))`` passthrough, mirroring
``/api/investigation-graph``) and gate the route test behind an importability
check that skips with a clear reason when the app cannot import.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vivarium_workbench.lib.audit_views import build_audit


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _make_workspace(root: Path) -> Path:
    """A minimal but canonical workspace: workspace.yaml + one study.yaml."""
    _write(root / "workspace.yaml", "name: probe-ws\n")
    _write(
        root / "studies" / "s1" / "study.yaml",
        "name: s1\n"
        "conditions:\n"
        "  baseline:\n"
        "    composite: some.composite\n",
    )
    return root


def test_build_audit_returns_dict_and_200(tmp_path):
    ws = _make_workspace(tmp_path / "ws")
    body, status = build_audit(ws)

    assert status == 200
    assert isinstance(body, dict)
    # `studies` is always a list.
    assert isinstance(body["studies"], list)
    assert len(body["studies"]) == 1
    assert body["studies"][0]["slug"] == "s1"
    # summary carries the hard-failures count.
    assert "summary" in body
    assert "hard_failures" in body["summary"]
    # Fully JSON-serializable (the endpoint hands this straight to JSONResponse).
    assert json.loads(json.dumps(body)) == body


def test_build_audit_empty_workspace_is_200_with_empty_studies(tmp_path):
    ws = tmp_path / "empty"
    _write(ws / "workspace.yaml", "name: empty\n")

    body, status = build_audit(ws)

    assert status == 200
    assert body["studies"] == []
    assert isinstance(body.get("investigations"), list)


def test_build_audit_is_tolerant_of_a_bad_path(tmp_path):
    """A non-existent / unreadable workspace must degrade to (dict, 200) with an
    empty studies list, never raise or 500."""
    body, status = build_audit(tmp_path / "does-not-exist")

    assert status == 200
    assert isinstance(body, dict)
    assert body.get("studies") == []


def _app_imports() -> bool:
    try:
        from vivarium_workbench.api.app import create_app  # noqa: F401
    except Exception:
        return False
    return True


@pytest.mark.skipif(
    not _app_imports(),
    reason="FastAPI app import hits the pre-existing process_bigraph.composite_spec "
    "ModuleNotFoundError (unrelated to this view); route covered by the lib test.",
)
def test_api_audit_route(dashboard_client, tmp_path):
    ws = _make_workspace(tmp_path / "ws")
    client = dashboard_client(ws)
    r = client.get("/api/audit")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("studies"), list)


def test_publish_writes_parseable_audit_json(tmp_path):
    """Mirror the publish step: build_audit's body, written through publish's
    strict (`allow_nan=False`) JSON writer, must land on disk and parse back."""
    from vivarium_workbench.publish import _write_json

    ws = _make_workspace(tmp_path / "ws")
    body, status = build_audit(ws)
    assert status == 200

    out = tmp_path / "bundle" / "api" / "audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_json(out, body)

    assert out.is_file()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(parsed.get("studies"), list)
    assert "summary" in parsed
