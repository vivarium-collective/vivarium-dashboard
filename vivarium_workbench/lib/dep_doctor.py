"""Framework-dependency doctor.

Turns the *silent* / *opaque* staleness failures that cost real debugging time
into actionable messages:

- a stale ``process-bigraph`` (predating the ``artifacts`` module) makes the
  server subprocess crash on boot and the whole test suite fail to collect with
  a bare ``ModuleNotFoundError: process_bigraph.artifacts`` — miles from the
  cause;
- a stale ``viva-superpowers`` (predating ``test_audit`` / ``loop_state``) makes
  the study-detail **Audit** and **Build** tabs render a blank "unavailable"
  with no hint that the fix is a dependency refresh.

`check_framework_deps()` probes each and returns structured findings; the CLI
``vivarium-workbench doctor`` prints them, and ``serve`` logs a one-line warning
per problem at startup. Pure + import-safe: every probe is wrapped, so importing
or running the doctor never raises.
"""
from __future__ import annotations

import importlib
from typing import Any

# (import target, why it matters, how to fix) — the framework deps whose
# staleness produces a confusing downstream symptom.
_PROBES: list[tuple[str, str, str]] = [
    ("process_bigraph.artifacts",
     "the run/artifact plumbing the server imports at boot",
     "process-bigraph is stale (predates the `artifacts` module) — reinstall it at main "
     "(uv lock --upgrade-package process-bigraph && uv sync)"),
    ("viva_superpowers.test_audit",
     "the test-sufficiency audit the Assurance > Audit tab renders",
     "viva-superpowers is stale — the Audit tab will show 'unavailable'; reinstall it at main "
     "(uv lock --upgrade-package viva-superpowers && uv sync)"),
    ("viva_superpowers.loop_state",
     "the model-build loop provenance the Assurance > Build tab renders",
     "viva-superpowers is stale — the Build tab will show 'unavailable'; reinstall it at main "
     "(uv lock --upgrade-package viva-superpowers && uv sync)"),
]


def check_framework_deps() -> list[dict[str, Any]]:
    """Probe the framework deps. Returns one finding dict per probe:
    ``{ok: bool, target: str, why: str, detail: str, fix: str}``. Never raises."""
    out: list[dict[str, Any]] = []
    for target, why, fix in _PROBES:
        try:
            importlib.import_module(target)
            out.append({"ok": True, "target": target, "why": why, "detail": "importable", "fix": ""})
        except Exception as e:  # noqa: BLE001 — any import failure is a finding, not a crash
            out.append({"ok": False, "target": target, "why": why,
                        "detail": f"{type(e).__name__}: {e}", "fix": fix})
    return out


def problems(findings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The non-ok findings (empty = healthy)."""
    findings = check_framework_deps() if findings is None else findings
    return [f for f in findings if not f.get("ok")]


def format_report(findings: list[dict[str, Any]] | None = None) -> str:
    """Human-readable multi-line report."""
    findings = check_framework_deps() if findings is None else findings
    lines = ["Framework dependency doctor:"]
    for f in findings:
        mark = "✓" if f.get("ok") else "✗"
        lines.append(f"  {mark} {f['target']} — {f['detail']}")
        if not f.get("ok"):
            lines.append(f"      ↳ needed for {f['why']}")
            lines.append(f"      ↳ fix: {f['fix']}")
    probs = [f for f in findings if not f.get("ok")]
    lines.append("" if probs else "All framework dependencies are current. ✓")
    if probs:
        lines.append(f"{len(probs)} stale dependency finding(s) — see fixes above.")
    return "\n".join(lines)


def warn_lines(findings: list[dict[str, Any]] | None = None) -> list[str]:
    """One compact warning line per problem, for startup logging (no-op if healthy)."""
    return [f"stale dependency: {f['target']} not importable ({f['detail']}). {f['fix']}"
            for f in problems(findings)]
