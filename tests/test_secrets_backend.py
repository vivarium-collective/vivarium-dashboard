"""Unit tests for vivarium_workbench.lib._secrets_backend (item 72 Phase 2).

Unlike tests/test_github_auth.py (which monkeypatches the keyring wrapper
functions away entirely), these tests exercise the REAL keyring_get/set/
delete/available implementations by injecting a fake ``keyring`` module into
``sys.modules`` — this is the layer that now actually needs coverage, since
github_auth.py's own wrappers just delegate here. No real network calls; no
real keyring writes; nothing touches the actual OS keychain.
"""
from __future__ import annotations

import os
import re
import sys
import types
from pathlib import Path

from vivarium_workbench.lib import _secrets_backend as backend


# ---------------------------------------------------------------------------
# Fake `keyring` backend injection helpers
# ---------------------------------------------------------------------------


def _install_fake_keyring(monkeypatch) -> dict:
    """Install a working fake `keyring` module backed by an in-memory dict."""
    store: dict[tuple[str, str], str] = {}
    fake = types.ModuleType("keyring")

    def get_password(service, key):
        return store.get((service, key))

    def set_password(service, key, value):
        store[(service, key)] = value

    def delete_password(service, key):
        if (service, key) not in store:
            raise LookupError("not found")
        del store[(service, key)]

    fake.get_password = get_password
    fake.set_password = set_password
    fake.delete_password = delete_password
    monkeypatch.setitem(sys.modules, "keyring", fake)
    return store


def _install_missing_keyring(monkeypatch) -> None:
    """Simulate `keyring` not being installed: `import keyring` raises ImportError."""
    monkeypatch.setitem(sys.modules, "keyring", None)


def _install_broken_keyring(monkeypatch) -> None:
    """Simulate an installed-but-broken keyring backend (every call raises)."""
    fake = types.ModuleType("keyring")

    def _boom(*_a, **_k):
        raise RuntimeError("backend unavailable")

    fake.get_password = _boom
    fake.set_password = _boom
    fake.delete_password = _boom
    monkeypatch.setitem(sys.modules, "keyring", fake)


# ---------------------------------------------------------------------------
# keyring_available / keyring_get / keyring_set / keyring_delete
# ---------------------------------------------------------------------------


def test_keyring_available_true_when_importable(monkeypatch):
    _install_fake_keyring(monkeypatch)
    assert backend.keyring_available() is True


def test_keyring_available_false_when_not_installed(monkeypatch):
    _install_missing_keyring(monkeypatch)
    assert backend.keyring_available() is False


def test_keyring_roundtrip_get_set_delete(monkeypatch):
    _install_fake_keyring(monkeypatch)
    assert backend.keyring_get("svc", "k1") is None
    assert backend.keyring_set("svc", "k1", "secret-value") is True
    assert backend.keyring_get("svc", "k1") == "secret-value"
    backend.keyring_delete("svc", "k1")
    assert backend.keyring_get("svc", "k1") is None


def test_keyring_get_returns_none_when_unavailable(monkeypatch):
    _install_missing_keyring(monkeypatch)
    assert backend.keyring_get("svc", "k1") is None


def test_keyring_set_returns_false_when_unavailable(monkeypatch):
    _install_missing_keyring(monkeypatch)
    assert backend.keyring_set("svc", "k1", "v") is False


def test_keyring_delete_is_noop_when_unavailable(monkeypatch):
    _install_missing_keyring(monkeypatch)
    backend.keyring_delete("svc", "k1")  # must not raise


def test_keyring_get_degrades_on_backend_exception(monkeypatch):
    _install_broken_keyring(monkeypatch)
    assert backend.keyring_get("svc", "k1") is None


def test_keyring_set_degrades_on_backend_exception(monkeypatch):
    _install_broken_keyring(monkeypatch)
    assert backend.keyring_set("svc", "k1", "v") is False


def test_keyring_delete_degrades_on_backend_exception(monkeypatch):
    _install_broken_keyring(monkeypatch)
    backend.keyring_delete("svc", "k1")  # best-effort, must not raise


def test_keyring_delete_absent_entry_is_not_an_error(monkeypatch):
    _install_fake_keyring(monkeypatch)
    backend.keyring_delete("svc", "never-set")  # must not raise


def test_keyring_set_failure_masks_value_in_log(monkeypatch, caplog):
    """A keyring write failure must never leak the raw secret value into the
    warning log, even when the exception text happens to echo it back."""
    fake = types.ModuleType("keyring")
    fake.get_password = lambda *a, **k: None
    fake.delete_password = lambda *a, **k: None

    def _boom_with_value(service, key, value):
        raise RuntimeError(f"backend rejected value {value!r}")

    fake.set_password = _boom_with_value
    monkeypatch.setitem(sys.modules, "keyring", fake)

    with caplog.at_level("WARNING"):
        ok = backend.keyring_set("svc", "k1", "super-secret-literal-value")
    assert ok is False
    assert "super-secret-literal-value" not in caplog.text
    assert "<redacted>" in caplog.text


# ---------------------------------------------------------------------------
# mask_value / mask_pattern
# ---------------------------------------------------------------------------


def test_mask_value_redacts_known_value():
    out = backend.mask_value("the key is sk-abc123xyz, keep it safe", "sk-abc123xyz")
    assert "sk-abc123xyz" not in out
    assert "<redacted>" in out


def test_mask_value_redacts_multiple_secrets():
    out = backend.mask_value("first=AAA second=BBB", "AAA", "BBB")
    assert "AAA" not in out
    assert "BBB" not in out
    assert out.count("<redacted>") == 2


def test_mask_value_skips_falsy_secrets():
    out = backend.mask_value("nothing to hide", "", None)  # type: ignore[arg-type]
    assert out == "nothing to hide"


def test_mask_value_leaves_unrelated_text_intact():
    assert backend.mask_value("hello world", "unrelated") == "hello world"


def test_mask_pattern_redacts_all_matches():
    pattern = re.compile(r"\d{4}")
    out = backend.mask_pattern("codes: 1234 and 5678", pattern)
    assert "1234" not in out
    assert "5678" not in out
    assert out.count("<redacted>") == 2


# ---------------------------------------------------------------------------
# config_dir
# ---------------------------------------------------------------------------


def test_config_dir_respects_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert backend.config_dir() == tmp_path / "vivarium-dashboard"


def test_config_dir_falls_back_to_home_config(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    expected = Path(os.path.expanduser("~/.config")) / "vivarium-dashboard"
    assert backend.config_dir() == expected
