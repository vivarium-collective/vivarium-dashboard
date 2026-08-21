"""Tests for vivarium_workbench.lib.secrets_store (item 72 Phase 2 —
generalized named per-workspace secrets, extending github_auth.py's existing
keyring mechanism per ecosystem/docs/plan-colab-design-clone.md Part 5).

No real network calls; no real keyring writes for most tests — keyring is
faked via monkeypatching the shared _secrets_backend module's functions, same
isolation discipline as tests/test_github_auth.py. A couple of tests (masking
on backend failure) instead fake the lower-level `keyring` package itself, so
the real secrets_store + _secrets_backend logic runs end-to-end.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types

import pytest

from vivarium_workbench.lib import secrets_store as store


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Redirect the config dir under tmp_path and reset in-memory state."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    with store._MEM_LOCK:
        store._MEM_STORE.clear()
    yield
    with store._MEM_LOCK:
        store._MEM_STORE.clear()


def _fake_keyring_available(monkeypatch, available: bool = True) -> dict:
    """Patch secrets_store's view of the shared backend to a controllable
    in-memory fake (available=True) or a hard "no keyring" degrade
    (available=False)."""
    fake_store: dict[tuple[str, str], str] = {}
    if not available:
        monkeypatch.setattr(store._backend, "keyring_available", lambda: False)
        monkeypatch.setattr(store._backend, "keyring_get", lambda service, key: None)
        monkeypatch.setattr(store._backend, "keyring_set", lambda service, key, value: False)
        monkeypatch.setattr(store._backend, "keyring_delete", lambda service, key: None)
        return fake_store

    monkeypatch.setattr(store._backend, "keyring_available", lambda: True)
    monkeypatch.setattr(store._backend, "keyring_get",
                        lambda service, key: fake_store.get((service, key)))

    def _set(service, key, value):
        fake_store[(service, key)] = value
        return True

    def _delete(service, key):
        fake_store.pop((service, key), None)

    monkeypatch.setattr(store._backend, "keyring_set", _set)
    monkeypatch.setattr(store._backend, "keyring_delete", _delete)
    return fake_store


# ---------------------------------------------------------------------------
# list / set / delete
# ---------------------------------------------------------------------------


def test_list_secret_names_empty_for_fresh_workspace(tmp_path):
    ws = tmp_path / "ws1"
    ws.mkdir()
    assert store.list_secret_names(ws) == []


def test_set_then_list_reflects_name(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch)
    ws = tmp_path / "ws1"
    ws.mkdir()
    persisted = store.set_secret(ws, "ptools_api_key", "sekrit-value")
    assert persisted is True
    assert store.list_secret_names(ws) == ["ptools_api_key"]


def test_set_multiple_names_sorted(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch)
    ws = tmp_path / "ws1"
    ws.mkdir()
    store.set_secret(ws, "zeta", "v1")
    store.set_secret(ws, "alpha", "v2")
    assert store.list_secret_names(ws) == ["alpha", "zeta"]


def test_set_secret_invalid_name_raises(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch)
    ws = tmp_path / "ws1"
    ws.mkdir()
    with pytest.raises(ValueError):
        store.set_secret(ws, "bad name with spaces", "v")
    with pytest.raises(ValueError):
        store.set_secret(ws, "", "v")


def test_set_secret_empty_value_raises(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch)
    ws = tmp_path / "ws1"
    ws.mkdir()
    with pytest.raises(ValueError):
        store.set_secret(ws, "name", "")


def test_delete_secret_removes_name_and_value(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch)
    ws = tmp_path / "ws1"
    ws.mkdir()
    store.set_secret(ws, "name", "v")
    assert store.list_secret_names(ws) == ["name"]
    store.delete_secret(ws, "name")
    assert store.list_secret_names(ws) == []
    assert store.current_secret_env(ws, "name", "NAME_ENV") == {}


def test_delete_secret_absent_name_is_noop(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch)
    ws = tmp_path / "ws1"
    ws.mkdir()
    store.delete_secret(ws, "never-set")  # must not raise
    assert store.list_secret_names(ws) == []


# ---------------------------------------------------------------------------
# Per-workspace isolation
# ---------------------------------------------------------------------------


def test_two_workspaces_do_not_collide(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch)
    ws_a = tmp_path / "ws_a"
    ws_b = tmp_path / "ws_b"
    ws_a.mkdir()
    ws_b.mkdir()
    store.set_secret(ws_a, "shared_name", "value-a")
    store.set_secret(ws_b, "shared_name", "value-b")

    assert store.list_secret_names(ws_a) == ["shared_name"]
    assert store.list_secret_names(ws_b) == ["shared_name"]
    assert store.current_secret_env(ws_a, "shared_name", "X") == {"X": "value-a"}
    assert store.current_secret_env(ws_b, "shared_name", "X") == {"X": "value-b"}


def test_workspace_id_stable_and_distinct(tmp_path):
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    assert store._workspace_id(ws_a) == store._workspace_id(ws_a)
    assert store._workspace_id(ws_a) != store._workspace_id(ws_b)


# ---------------------------------------------------------------------------
# current_secret_env
# ---------------------------------------------------------------------------


def test_current_secret_env_empty_when_unset(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch)
    ws = tmp_path / "ws1"
    ws.mkdir()
    assert store.current_secret_env(ws, "nope", "NOPE_ENV") == {}


def test_current_secret_env_returns_value_under_requested_var(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch)
    ws = tmp_path / "ws1"
    ws.mkdir()
    store.set_secret(ws, "ptools_api_key", "abc123")
    env = store.current_secret_env(ws, "ptools_api_key", "PTOOLS_API_KEY")
    assert env == {"PTOOLS_API_KEY": "abc123"}


# ---------------------------------------------------------------------------
# In-memory degrade when keyring is unavailable (mirrors github_auth.py's own
# documented in-memory-only degrade story for the current process lifetime)
# ---------------------------------------------------------------------------


def test_degrades_to_in_memory_when_keyring_unavailable(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch, available=False)
    ws = tmp_path / "ws1"
    ws.mkdir()

    persisted = store.set_secret(ws, "name", "v")
    assert persisted is False  # not durably persisted...

    # ...but still resolvable within this process's lifetime, and still listed.
    assert store.list_secret_names(ws) == ["name"]
    assert store.current_secret_env(ws, "name", "NAME") == {"NAME": "v"}


def test_in_memory_fallback_is_per_workspace(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch, available=False)
    ws_a = tmp_path / "ws_a"
    ws_b = tmp_path / "ws_b"
    ws_a.mkdir()
    ws_b.mkdir()
    store.set_secret(ws_a, "name", "value-a")
    assert store.current_secret_env(ws_b, "name", "NAME") == {}
    assert store.current_secret_env(ws_a, "name", "NAME") == {"NAME": "value-a"}


def test_list_names_survives_memory_cache_clear_when_keyring_available(monkeypatch, tmp_path):
    """The name index is disk-backed (source of truth for names); the value
    is keyring-backed. Clearing the in-memory fallback cache must not lose
    either when a real keyring is available."""
    _fake_keyring_available(monkeypatch, available=True)
    ws = tmp_path / "ws1"
    ws.mkdir()
    store.set_secret(ws, "name", "v")

    with store._MEM_LOCK:
        store._MEM_STORE.clear()

    assert store.list_secret_names(ws) == ["name"]
    assert store.current_secret_env(ws, "name", "NAME") == {"NAME": "v"}


def test_list_secret_names_recovers_from_corrupt_index(tmp_path):
    ws = tmp_path / "ws1"
    ws.mkdir()
    idx_path = store._index_path(ws)
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.write_text("not valid json {{{", encoding="utf-8")
    assert store.list_secret_names(ws) == []


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


def test_mask_secret_redacts_known_value():
    out = store.mask_secret("token=abc123 in the clear", "abc123")
    assert "abc123" not in out
    assert "<redacted>" in out


def test_set_secret_masks_value_in_log_on_backend_failure(monkeypatch, tmp_path, caplog):
    """End-to-end: a real keyring backend failure during set_secret must not
    leak the raw value into log output. Only the external `keyring` package
    itself is faked (to make set_password raise) — secrets_store.set_secret
    and the real _secrets_backend.keyring_set both run unmodified."""
    ws = tmp_path / "ws1"
    ws.mkdir()

    fake = types.ModuleType("keyring")
    fake.get_password = lambda *a, **k: None
    fake.delete_password = lambda *a, **k: None

    def _boom(service, key, value):
        raise RuntimeError(f"backend rejected {value!r}")

    fake.set_password = _boom
    monkeypatch.setitem(sys.modules, "keyring", fake)

    with caplog.at_level("WARNING"):
        persisted = store.set_secret(ws, "name", "must-not-appear-in-logs")

    assert persisted is False
    assert "must-not-appear-in-logs" not in caplog.text
    assert "<redacted>" in caplog.text
    # Still usable for the rest of this process's lifetime via the in-memory
    # fallback, exactly like the degrade-story tests above.
    assert store.current_secret_env(ws, "name", "NAME") == {"NAME": "must-not-appear-in-logs"}


# ---------------------------------------------------------------------------
# Subprocess env injection (mirrors tests/test_github_auth_env_injection.py)
# ---------------------------------------------------------------------------


def test_subprocess_inherits_injected_secret(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch)
    ws = tmp_path / "ws1"
    ws.mkdir()
    store.set_secret(ws, "ptools_api_key", "subprocess-secret-xyz")

    env = os.environ.copy()
    env.update(store.current_secret_env(ws, "ptools_api_key", "PTOOLS_API_KEY"))

    script = "import os; print(os.environ.get('PTOOLS_API_KEY', 'MISSING'), end='')"
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout == "subprocess-secret-xyz"


def test_subprocess_without_env_injection_does_not_see_secret(monkeypatch, tmp_path):
    _fake_keyring_available(monkeypatch)
    ws = tmp_path / "ws1"
    ws.mkdir()
    store.set_secret(ws, "ptools_api_key", "should-not-leak")

    env = os.environ.copy()
    # Deliberately NOT calling current_secret_env().

    script = "import os; print(os.environ.get('PTOOLS_API_KEY', 'MISSING'), end='')"
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout == "MISSING"
