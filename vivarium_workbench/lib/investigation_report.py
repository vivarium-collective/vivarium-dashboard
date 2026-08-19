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

from vivarium_workbench.lib.investigation_members import (
    investigation_member_slugs,
    member_slug,
)
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
    "parent_studies", "pipeline_gate",
)

# 5-state study verdict (mirrors viva_superpowers roll-up): each maps to a glyph
# + label the report legend enumerates.
_VERDICT_GLYPH = {
    "passed": ("✅", "passed"), "failing": ("⛔", "failing"), "blocked": ("⚠", "blocked"),
    "needs_calibration": ("🔄", "needs calibration"), "not_started": ("◽", "not evaluated"),
}
_VERDICT_MAP = {
    "passing": "passed", "passing-with-caveats": "passed", "passed": "passed", "pass": "passed",
    "failing": "failing", "failed": "failing", "fail": "failing", "blocked": "blocked",
    "needs_calibration": "needs_calibration", "not_started": "not_started",
}


def _study_verdict(spec, computed_gate) -> str:
    """Reduce a study to one of the five verdict states from its computed gate
    evaluator, else its gate_status, else run presence."""
    res = (computed_gate or {}).get("result")
    if res and res in _VERDICT_MAP:
        return _VERDICT_MAP[res]
    gs = spec.get("gate_status")
    if gs in ("passed", "pass"):
        return "passed"
    if gs in ("failed", "fail"):
        return "failing"
    return "not_started" if not spec.get("runs") else "blocked"


def _outcome_counts(spec) -> dict:
    passed = skipped = failed = 0
    for r in (spec.get("runs") or []):
        for o in ((r.get("outcomes") or {}).values()):
            res = str((o or {}).get("result", "")).upper()
            if res == "PASS":
                passed += 1
            elif res in ("SKIP", "SKIPPED", "NA", "N/A"):
                skipped += 1
            elif res == "FAIL":
                failed += 1
    return {"passed": passed, "skipped": skipped, "failed": failed}


def _depths(slugs, edges) -> dict:
    """Longest-path depth per node (topological column for the DAG)."""
    incoming = {s: [] for s in slugs}
    for e in edges:
        if e["to"] in incoming and e["from"] in incoming:
            incoming[e["to"]].append(e["from"])
    depth = {s: 0 for s in slugs}
    for _ in range(len(slugs)):  # relax up to N times (DAG converges)
        changed = False
        for s in slugs:
            d = max((depth[p] + 1 for p in incoming[s]), default=0)
            if d != depth[s]:
                depth[s] = d
                changed = True
        if not changed:
            break
    return depth


def _build_spine(ws_root, inv_slug: str, studies: list) -> dict:
    """Computed spine presentation: per-study verdicts, the verdict-annotated
    study DAG, the acceptance roll-up, and the AC→study gating matrix. All from
    the existing server-side computations (build_iset_detail, ac_gating_matrix)."""
    detail = {}
    try:
        from vivarium_workbench.lib.report_views import build_iset_detail
        detail = build_iset_detail(ws_root, inv_slug) or {}
    except Exception:
        detail = {}
    cgv = {s.get("name"): s.get("computed_gate_verdict") for s in detail.get("studies", []) if s.get("name")}
    rcmap = {s.get("name"): s.get("run_commands") for s in detail.get("studies", []) if s.get("name")}
    ac_matrix = None
    try:
        from vivarium_workbench.lib import linkage_index
        ac_matrix = linkage_index.ac_gating_matrix(ws_root, inv_slug)
    except Exception:
        ac_matrix = None

    slugs = [s["slug"] for s in studies]
    edges = []
    for s in studies:
        gate = cgv.get(s["slug"])
        s["verdict"] = _study_verdict(s, gate)
        s["verdict_counts"] = _outcome_counts(s)
        if gate:
            s["computed_gate_verdict"] = gate
        rc = rcmap.get(s["slug"])
        if rc:
            s["run_commands"] = rc
        for p in (s.get("parent_studies") or []):
            src = p.get("study") if isinstance(p, dict) else p
            if src in slugs:
                edges.append({"from": src, "to": s["slug"]})
    depth = _depths(slugs, edges)
    nodes = [{"slug": s["slug"], "title": s["title"], "verdict": s["verdict"],
              "counts": s["verdict_counts"], "depth": depth.get(s["slug"], 0)} for s in studies]
    return {
        "verdict_dag": {"nodes": nodes, "edges": edges},
        "acceptance": detail.get("computed_acceptance"),
        "ac_matrix": ac_matrix,
    }

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


_LOOM_IMG_CANDIDATES = (
    "viz/model-loom.png", "viz/model-loom.svg",
    "visualizations/model-loom.png", "visualizations/model-loom.svg",
)


def _model_loom_img(study_dir: Path, budget: list) -> "str | None":
    """Data-URI for a study's pre-rendered bigraph-loom image (Model section).

    Looks for a saved loom render at ``viz/model-loom.{png,svg}`` (produced by
    ``vivarium-workbench render-loom``). PNG is preferred — a rasterised loom is
    ~0.3 MB vs a 1-4 MB KaTeX/font-heavy vector SVG. Respects the shared inline-
    image budget; returns None when absent or oversized.
    """
    for rel in _LOOM_IMG_CANDIDATES:
        f = study_dir / rel
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext not in _IMG_MIME:
            continue
        size = f.stat().st_size
        if size > _IMG_PER_FILE_MAX or budget[0] + size > _IMG_TOTAL_MAX:
            return None
        try:
            data = base64.b64encode(f.read_bytes()).decode("ascii")
        except OSError:
            return None
        budget[0] += size
        return f"data:{_IMG_MIME[ext]};base64,{data}"
    return None


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


def _compact_bigraph(state: dict) -> dict:
    """Reduce a resolved composite ``state`` to a compact bigraph topology for
    the Model-section loom view: the nested store tree (name + type) and the
    flat process list (name + address + declared input/output ports)."""
    procs: list = []

    def walk(node: dict) -> list:
        out = []
        for k, v in node.items():
            if k.startswith("_") or not isinstance(v, dict):
                continue
            t = v.get("_type")
            if t in ("process", "step"):
                procs.append({
                    "name": k, "kind": t, "address": v.get("address"),
                    "inputs": list((v.get("inputs") or {}).keys()),
                    "outputs": list((v.get("outputs") or {}).keys()),
                })
                continue
            out.append({"name": k, "type": t, "children": walk(v)})
        return out

    stores = walk(state)
    return {"processes": procs, "stores": stores}


def _model_topology(ws_root, spec: dict) -> "dict | None":
    """Best-effort bigraph topology for the study's first baseline composite,
    used to render the loom view in the Model section. Fully guarded: any
    resolution/import failure returns None so the report never breaks."""
    try:
        cid = None
        for b in (spec.get("baseline") or []):
            if isinstance(b, dict) and b.get("composite"):
                cid = b["composite"]
                break
        if not cid:
            return None
        from vivarium_workbench.lib.composite_resolve import resolve_composite
        data = resolve_composite(ws_root, cid)
        if not isinstance(data, dict):
            return None
        state = data["state"] if isinstance(data.get("state"), dict) else data
        if not isinstance(state, dict):
            return None
        topo = _compact_bigraph(state)
        if not topo["processes"] and not topo["stores"]:
            return None
        topo["composite"] = cid
        return topo
    except Exception:
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
    # Read the member list via the shared helper so BOTH the pre-migration
    # `studies:` key and the post-migration `members:` key render — otherwise a
    # members-only investigation reports zero studies (the generated report's
    # study list comes solely from here). Normalize dict/bare-slug entries.
    for entry in investigation_member_slugs(inv):
        slug = member_slug(entry)
        if not slug:
            continue
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
        # resolve the baseline composite's bigraph topology for the Model loom view
        topo = _model_topology(ws_root, spec)
        if topo:
            s["model_topology"] = topo
        # embed a pre-rendered loom image (offline-safe Model view) if the study
        # saved one via `vivarium-workbench render-loom`
        loom_img = _model_loom_img(wp.studies / real_slug, img_budget)
        if loom_img:
            s["model_loom"] = loom_img
        studies.append(s)

    spine = _build_spine(ws_root, inv_slug, studies)

    return {
        "slug": inv.get("name") or inv_slug,
        "title": inv.get("title") or inv_slug,
        "status": inv.get("status"),
        "question": inv.get("question"),
        "hypothesis": inv.get("hypothesis"),
        "lead": inv.get("lead"),
        "executive": inv.get("executive"),
        "at_a_glance": inv.get("at_a_glance"),
        "acceptance_criteria": inv.get("acceptance_criteria"),
        "spine": spine,
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
