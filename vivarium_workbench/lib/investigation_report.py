"""Deterministic, self-contained investigation-report generator.

Renders one investigation to a single self-contained HTML document — executive
band, per-study spine sections (Model · Simulation run · Visualizations · Tests ·
Decision), inline SVG figures, collapsible studies, and per-section feedback that
exports to a YAML feedback report.

Everything is read from EXISTING workspace files: ``investigation.yaml``, each
member ``study.yaml``, and any loop-trajectory JSON already present in the
workspace. There is no model call and no invented prose — ``build_report_data``
assembles a pure data dict that is embedded into a fixed template + client
renderer. The only new content a report ever carries is the feedback a reviewer
types, which is exported (never fabricated).
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import yaml

from vivarium_workbench.lib.single_study_report import _load_study_spec
from vivarium_workbench.lib.workspace_paths import WorkspacePaths

_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "investigation-report.html"
_TRAJ_SCHEMAS = ("agent_build_trajectory", "model_build_trajectory")

# study.yaml fields the renderer consumes (everything else is ignored so the
# report never carries content that isn't one of these declared fields)
_STUDY_KEEP = (
    "title", "confidence", "gate_status", "question", "claim", "biological_summary",
    "requires", "sourcing", "baseline", "behavior_tests", "runs", "conclusion",
    "loop_provenance", "purpose", "findings", "conclusion_logic", "limitations",
)

# inline-image budget: keep the self-contained report a sane size
_IMG_PER_FILE_MAX = 1_400_000     # skip a single figure larger than this
_IMG_TOTAL_MAX = 11_000_000       # stop embedding once the report gets heavy
_IMG_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".gif": "image/gif",
             ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _humanize(slug: str) -> str:
    return re.sub(r"[-_]+", " ", str(slug)).strip().title()


def _embed_visualizations(study_dir: Path, viz_list, budget: list) -> list:
    """Resolve each ``visualizations[].address`` of the form ``image:<relpath>``
    to a data-URI so the report stays self-contained. Respects a size budget
    (``budget[0]`` is the running total); oversized/missing files are skipped
    with a note so the report never silently drops a figure it meant to show."""
    out = []
    for v in (viz_list or []):
        if not isinstance(v, dict):
            continue
        addr = str(v.get("address") or "")
        name = v.get("name") or ""
        if not addr.startswith("image:"):
            continue
        rel = addr[len("image:"):]
        f = (study_dir / rel).resolve()
        try:
            f.relative_to(study_dir.resolve())
        except ValueError:
            continue  # never read outside the study dir
        ext = f.suffix.lower()
        if not f.is_file() or ext not in _IMG_MIME:
            continue
        size = f.stat().st_size
        if size > _IMG_PER_FILE_MAX or budget[0] + size > _IMG_TOTAL_MAX:
            out.append({"name": name, "skipped": True, "reason": "too large to inline"})
            continue
        try:
            data = base64.b64encode(f.read_bytes()).decode("ascii")
        except OSError:
            continue
        budget[0] += size
        out.append({"name": name, "data_uri": f"data:{_IMG_MIME[ext]};base64,{data}"})
    return out


def _norm_study(s) -> str:
    return re.sub(r"-(agent|policy)$", "", str(s or "").strip())


def _slim_traj(t: dict) -> dict:
    """Reduce a loop-trajectory doc to exactly what the figures need."""
    return {
        "driver": t.get("driver"),
        "contract": t.get("contract"),
        "tests": t.get("tests"),
        "result": t.get("result"),
        "iterations": [
            {
                "iteration": it.get("iteration"),
                "active": it.get("active"),
                "n_pass": it.get("n_pass"),
                "n_hard": it.get("n_hard"),
                "newly_fixed": it.get("newly_fixed"),
                "regressed": it.get("regressed"),
                "decision": it.get("agent_decision") or it.get("decision"),
                "observables": it.get("observables"),
                "tests": [
                    {
                        "id": x.get("id") or x.get("name"), "label": x.get("label"),
                        "verdict": x.get("verdict"), "margin": x.get("margin"),
                        "observed": x.get("observed"), "expected": x.get("expected"),
                    }
                    for x in (it.get("tests") or [])
                ],
            }
            for it in (t.get("iterations") or [])
        ],
    }


def _discover_trajectories(wp) -> list[dict]:
    """Every loop-trajectory JSON under ``investigations/``, tagged with the study
    it belongs to and whether it is an agent or a deterministic-policy run
    (agent_build_trajectory/* → agent; model_build_trajectory/* → policy)."""
    out: list[dict] = []
    root = wp.investigations
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        sc = str(d.get("schema") or "")
        if not sc.startswith(_TRAJ_SCHEMAS):
            continue
        out.append({
            "study": _norm_study(d.get("study")),
            "stem": p.stem,
            "kind": "agent" if sc.startswith("agent_build") else "policy",
            "doc": d,
        })
    return out


def _match_traj(trajs, slug, kind):
    """Match a trajectory to a study slug. The ``study`` field is not always the
    slug (e.g. 'bounded-cell-agent', 'multicell' vs 'multicellular'), so accept a
    normalized exact match, a prefix match, or a filename-stem prefix."""
    for t in trajs:
        if t["kind"] != kind:
            continue
        st = t["study"]
        if st == slug or (len(st) >= 4 and slug.startswith(st)) or t["stem"].startswith(slug):
            return _slim_traj(t["doc"])
    return None


def build_report_data(ws_root, inv_slug: str) -> dict:
    """Assemble the pure report-data dict for one investigation from existing
    files only. Raises FileNotFoundError if the investigation is missing."""
    ws_root = Path(ws_root)
    wp = WorkspacePaths.load(ws_root)
    inv_path = wp.investigations / inv_slug / "investigation.yaml"
    if not inv_path.is_file():
        raise FileNotFoundError(f"investigation.yaml not found for {inv_slug!r}")
    inv = yaml.safe_load(inv_path.read_text(encoding="utf-8")) or {}
    trajs = _discover_trajectories(wp)

    studies = []
    img_budget = [0]
    for slug in (inv.get("studies") or []):
        try:
            spec = _load_study_spec(ws_root, slug)
        except (FileNotFoundError, ValueError):
            continue
        real_slug = spec.get("name") or slug
        s = {k: spec.get(k) for k in _STUDY_KEEP if spec.get(k) is not None}
        s["slug"] = real_slug
        s["title"] = spec.get("title") or _humanize(real_slug)   # title is optional in some workspaces
        at = _match_traj(trajs, real_slug, "agent")
        pt = _match_traj(trajs, real_slug, "policy")
        if at:
            s["agent_trajectory"] = at
        if pt:
            s["policy_trajectory"] = pt
        # inline any on-disk study visualization images (self-contained report)
        if spec.get("visualizations"):
            figs = _embed_visualizations(wp.studies / real_slug, spec["visualizations"], img_budget)
            if figs:
                s["figures_embedded"] = figs
        studies.append(s)

    return {
        "slug": inv.get("name") or inv_slug,
        "title": inv.get("title") or inv_slug,
        "status": inv.get("status"),
        "question": inv.get("question"),
        "hypothesis": inv.get("hypothesis"),
        "lead": inv.get("lead"),
        "executive": inv.get("executive"),
        "at_a_glance": inv.get("at_a_glance"),
        "catalog": inv.get("catalog"),
        "workspace": ws_root.name,
        "provenance": (
            f"investigations/{inv_slug}/investigation.yaml · studies/*/study.yaml · loop-trajectory JSON"
        ),
        "studies": studies,
    }


def _h(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_html(data: dict) -> str:
    """Embed the report-data dict into the fixed template + renderer."""
    tpl = _TEMPLATE.read_text(encoding="utf-8")
    # escape '<' so the JSON can never break out of the <script> element
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    title = f"{data.get('title', 'Investigation')} — report"
    return tpl.replace("__TITLE__", _h(title)).replace("__DATA__", payload)


def render_investigation_report(ws_root, inv_slug: str, *, out_dir=None) -> Path:
    """Render one investigation to ``reports/investigation-<slug>.html`` (or
    ``out_dir``) and return the written path."""
    ws_root = Path(ws_root)
    data = build_report_data(ws_root, inv_slug)
    html = render_html(data)
    out_dir = Path(out_dir) if out_dir is not None else WorkspacePaths.load(ws_root).reports
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"investigation-{inv_slug}.html"
    out.write_text(html, encoding="utf-8")
    return out
