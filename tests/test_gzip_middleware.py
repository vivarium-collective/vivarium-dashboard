"""Tests for the GZip compression middleware (perf).

The SPA ships a ~1.2MB JS bundle, ~227KB CSS, and study/investigation JSON
payloads up to ~1.4MB raw with no compression. `create_app()` now registers
`starlette.middleware.gzip.GZipMiddleware(minimum_size=1000)` as the
INNERMOST middleware (added first, right after `FastAPI(...)` in
api/app.py) — it must sit closer to the router than the
`@app.middleware("http")` (BaseHTTPMiddleware-based) CSRF/session/logging
layers, or its `minimum_size` check gets defeated by their response
streaming and it ends up compressing everything unconditionally.

Uses the auto-generated `/openapi.json` (hundreds of KB, always available,
no workspace fixture needed) as a large payload and `/health` as a small one.
"""
from fastapi.testclient import TestClient

from vivarium_workbench.api.app import create_app


def test_large_response_is_gzip_encoded_when_accepted():
    client = TestClient(create_app())
    r = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert len(r.content) > 1000
    assert r.json()["info"]["title"] == "vivarium-workbench API"


def test_small_response_is_not_gzip_encoded():
    client = TestClient(create_app())
    r = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") != "gzip"
    assert r.json() == {"status": "ok"}


def test_no_accept_encoding_header_gets_uncompressed_response():
    client = TestClient(create_app())
    r = client.get("/openapi.json", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") != "gzip"


def test_health_endpoint_still_works_with_gzip_enabled():
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
