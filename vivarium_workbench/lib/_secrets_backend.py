"""Shared OS-keyring + secret-masking primitives for vivarium-workbench.

Factored out of ``github_auth.py`` (item 72 Phase 2 — see
``ecosystem/docs/plan-colab-design-clone.md`` Part 5) so GitHub-token storage
and the generalized named-secret store (:mod:`vivarium_workbench.lib.secrets_store`)
share one keyring backend and one masking discipline instead of duplicating
logic. Internal module: import ``github_auth`` or ``secrets_store`` instead of
depending on this directly.

``KEYRING_SERVICE`` deliberately keeps the pre-rename ``vivarium-dashboard``
name (see this repo's own CLAUDE.md "Rename (in progress)" section) so
credentials ``github_auth.py`` already persisted under that service keep
resolving unchanged; the generalized store rides the same service rather than
opening a second one.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Same OS-keyring service both github_auth.py and secrets_store.py store
# under. One service, disjoint key namespaces (see secrets_store.py's
# ``_keyring_key`` for how it avoids colliding with a GitHub login string).
KEYRING_SERVICE = "vivarium-dashboard"

REDACTED = "<redacted>"


# ---------------------------------------------------------------------------
# Keyring storage — wraps the optional ``keyring`` library so missing/broken
# backends degrade to "caller falls back to in-memory" rather than crashing.
# ---------------------------------------------------------------------------


def keyring_available() -> bool:
    """Whether the optional ``keyring`` package is importable in this env."""
    try:
        import keyring  # noqa: F401
        return True
    except Exception:
        return False


def keyring_get(service: str, key: str) -> str | None:
    """Read ``key`` from the OS keyring under ``service``.

    ``None`` if the keyring is unavailable, the entry is absent, or the
    backend raised. Read failures never carry a secret value (nothing was
    retrieved), so nothing needs masking before logging them.
    """
    if not keyring_available():
        return None
    try:
        import keyring
        return keyring.get_password(service, key)
    except Exception as e:
        log.warning("keyring read failed for service=%s key=%s: %s", service, key, e)
        return None


def keyring_set(service: str, key: str, value: str) -> bool:
    """Write ``value`` to the OS keyring under ``service``/``key``.

    Returns whether it was actually persisted (``False`` when the keyring is
    unavailable or the backend raised — the caller is responsible for an
    in-memory fallback in that case). The known ``value`` is masked out of
    any exception text before logging.
    """
    if not keyring_available():
        return False
    try:
        import keyring
        keyring.set_password(service, key, value)
        return True
    except Exception as e:
        log.warning("keyring write failed for service=%s key=%s: %s",
                    service, key, mask_value(str(e), value))
        return False


def keyring_delete(service: str, key: str) -> None:
    """Best-effort delete; an absent entry is not an error."""
    if not keyring_available():
        return
    try:
        import keyring
        keyring.delete_password(service, key)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Masking — two complementary mechanisms. Pattern-based catches a *known
# shape* (e.g. GitHub's ``gh[opusr]_...`` tokens) even when the caller doesn't
# have the literal value in hand. Value-based catches an *arbitrary* secret
# (any shape) whenever the caller does hold the literal value — the only
# mechanism that generalizes correctly to secrets_store.py's named secrets,
# which have no fixed shape to pattern-match against.
# ---------------------------------------------------------------------------


def mask_value(text: str, *secrets: str) -> str:
    """Redact every occurrence of a known secret value in ``text``.

    Falsy entries in ``secrets`` are skipped (never redacts unrelated text).
    Use whenever a captured value you hold the literal secret for (subprocess
    output, an exception message, an HTTP body) might echo it back.
    """
    out = text
    for s in secrets:
        if s:
            out = out.replace(s, REDACTED)
    return out


def mask_pattern(text: str, pattern: re.Pattern[str]) -> str:
    """Redact every regex match of ``pattern`` in ``text``."""
    return pattern.sub(REDACTED, text)


# ---------------------------------------------------------------------------
# Config dir — shared base for any small on-disk (non-secret) hint/index file
# a keyring-backed store needs, e.g. github_auth.py's last-login hint or
# secrets_store.py's per-workspace name index.
# ---------------------------------------------------------------------------


def config_dir() -> Path:
    """Base config dir: ``$XDG_CONFIG_HOME/vivarium-dashboard`` or
    ``~/.config/vivarium-dashboard``.

    Deliberately keeps the pre-rename ``vivarium-dashboard`` name (matches
    ``KEYRING_SERVICE`` and github_auth.py's existing hint-file dir) so
    existing on-disk hints keep resolving across the vivarium-dashboard ->
    vivarium-workbench rename.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "vivarium-dashboard"
