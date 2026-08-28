"""Background-thread job manager for investigation-wide multi-variant runs.

The ``/api/investigation-run-unblocked`` endpoint kicks off a sequence
of variant runs (potentially tens of minutes total). HTTP requests can
not block that long, so the work is queued onto a background thread
and tracked here. Clients poll
``/api/investigation-run-unblocked-status?job_id=...`` for progress.

A "job" is one investigation-wide run sequence. It holds:

  job_id       opaque short id (caller polls with this)
  status       queued | running | done | failed
  investigation slug
  items        list of variant-level sub-jobs, each:
                 {study, variant, status, run_id?, error?}
  started_at   ISO8601
  completed_at ISO8601 (set when status reaches done/failed)
  worker       Thread instance (not serialised)

Jobs live in-process; restarting the dashboard loses them. The runs
themselves write to ``studies/<slug>/runs.db`` and that persistence is
the durable artefact — the in-memory job is just progress signalling.
"""
from __future__ import annotations

import threading
import traceback
import uuid
from datetime import datetime, timezone
from typing import Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


#: Item statuses that mean "this item will not change again".
#:
#: ``submitted`` is deliberately NOT here: it means the work was dispatched to
#: viva-api and is running on Batch, carrying a ``simulation_id`` that can still
#: resolve to done or failed. Treating it as terminal is what made a successful
#: async dispatch look finished (or, before this, look *failed* — the worker only
#: accepted HTTP 200 and `remote_run_submit` answers 202).
TERMINAL_STATUSES = frozenset({"done", "failed", "skipped"})


class RunJob:
    def __init__(self, investigation: str, items: list[dict]):
        self.job_id = uuid.uuid4().hex[:12]
        self.investigation = investigation
        self.items: list[dict] = items  # mutated as work progresses
        self.status = "queued"
        self.started_at = _now()
        self.completed_at: str | None = None
        self.error: str | None = None
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "job_id":        self.job_id,
                "investigation": self.investigation,
                "status":        self.status,
                "items":         [dict(it) for it in self.items],
                "started_at":    self.started_at,
                "completed_at":  self.completed_at,
                "error":         self.error,
                "progress":      self._progress_locked(),
            }

    def _progress_locked(self) -> dict:
        n = len(self.items)
        done = sum(1 for it in self.items if it.get("status") in TERMINAL_STATUSES)
        running = sum(1 for it in self.items if it.get("status") == "running")
        submitted = sum(1 for it in self.items if it.get("status") == "submitted")
        return {"total": n, "done": done, "running": running,
                "submitted": submitted}

    def update_item(self, idx: int, **fields) -> None:
        with self._lock:
            if 0 <= idx < len(self.items):
                self.items[idx].update(fields)


class RunJobManager:
    """In-process registry of background run-jobs."""

    def __init__(self):
        self._jobs: dict[str, RunJob] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        investigation: str,
        items: list[dict],
        worker_fn: Callable[[RunJob], None],
    ) -> RunJob:
        """Create a RunJob, start its background worker, return the handle."""
        job = RunJob(investigation, items)
        with self._lock:
            self._jobs[job.job_id] = job

        def _run():
            try:
                with job._lock:
                    job.status = "running"
                worker_fn(job)
                with job._lock:
                    if all(it.get("status") in TERMINAL_STATUSES for it in job.items):
                        any_failed = any(it.get("status") == "failed" for it in job.items)
                        job.status = "failed" if any_failed else "done"
                    elif any(it.get("status") == "submitted" for it in job.items):
                        # The worker is finished dispatching, but work it handed to
                        # Batch is still running. The job is NOT done — its items
                        # resolve when their simulation_ids do. Reporting "done"
                        # here (as the old else-branch did unconditionally) would
                        # tell the UI a 10,000-sim campaign had completed the moment
                        # it was submitted.
                        job.status = "submitted"
                    else:
                        job.status = "done"
            except BaseException as e:  # noqa: BLE001
                with job._lock:
                    job.status = "failed"
                    job.error = f"worker crashed: {e}\n{traceback.format_exc()[-2000:]}"
            finally:
                with job._lock:
                    job.completed_at = _now()

        t = threading.Thread(target=_run, daemon=True, name=f"runjob-{job.job_id}")
        job._worker = t
        t.start()
        return job

    def get(self, job_id: str) -> RunJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            jobs = list(self._jobs.values())
        # Most recent first
        jobs.sort(key=lambda j: j.started_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]


# Module-level singleton — one manager per dashboard process.
manager = RunJobManager()


# ---------------------------------------------------------------------------
# Investigation-level "run unblocked" planner
# ---------------------------------------------------------------------------

#: viva-api ``ComposeJobStatus`` values that mean the run is over.
#: Anything not listed — waiting/queued/running/pending/suspended, or an absent
#: status — leaves the item ``submitted``: an unknown state is not a finished one.
_UPSTREAM_DONE = frozenset({"completed"})
_UPSTREAM_FAILED = frozenset({"failed", "cancelled", "out_of_memory", "timeout"})


def refresh_submitted(job, client=None) -> None:
    """Resolve a job's ``submitted`` items against viva-api, in ONE call.

    ``submitted`` means the work was dispatched to Batch and viva-api holds the
    truth about it, keyed by ``simulation_id``. This asks for all of them at once
    (``GET /compose/v1/simulations/status/batch``) rather than per item, and is
    called on **status read** rather than from a polling thread — so nothing is
    held open on the workbench side while Batch works.

    Best-effort by design: if viva-api is unreachable the items stay
    ``submitted``, which is what they are. Losing the poll must not turn a
    running campaign into a failed one — that is the mistake this whole change
    exists to undo.
    """
    with job._lock:
        pending = [(i, it.get("simulation_id")) for i, it in enumerate(job.items)
                   if it.get("status") == "submitted" and it.get("simulation_id")]
    if not pending:
        return
    if client is None:
        from vivarium_workbench.lib.sms_api_client import SmsApiClient
        from vivarium_workbench.lib.workspace_deps_views import _sms_api_base
        client = SmsApiClient(_sms_api_base())
    try:
        rows = client.compose_status_batch([sid for _, sid in pending])
    except Exception:  # noqa: BLE001 — a poll must never fail a running job
        return
    by_sim = {r.get("sim_id"): r for r in rows if isinstance(r, dict)}
    for idx, sid in pending:
        row = by_sim.get(sid)
        if not row:
            continue
        upstream = (row.get("status") or "").lower()
        if upstream in _UPSTREAM_DONE:
            job.update_item(idx, status="done")
        elif upstream in _UPSTREAM_FAILED:
            job.update_item(idx, status="failed",
                            error=row.get("error_message") or f"upstream: {upstream}")
        else:
            job.update_item(idx, phase=upstream or "running")
    with job._lock:
        if all(it.get("status") in TERMINAL_STATUSES for it in job.items):
            any_failed = any(it.get("status") == "failed" for it in job.items)
            job.status = "failed" if any_failed else "done"
            if job.completed_at is None:
                job.completed_at = _now()


def enumerate_unblocked(spec: dict) -> tuple[list[dict], list[dict]]:
    """Return (runnable_items, blocked_items) for one study's spec.

    A variant is **blocked** if the study has any ``conditions.model_settings``
    (or legacy ``expert_inputs``) entry with ``gate: required-before-run``
    whose ``current`` is null / missing. The variant is **runnable**
    otherwise.

    Items have shape ``{study, variant, base_composite?, params?, kind}``
    where kind ∈ {"baseline", "variant"}.

    A study with no variants surfaces its baseline as a single runnable item.
    """
    cond = spec.get("conditions") or {}
    # Backward-compat: accept either model_settings or the legacy alias.
    settings = cond.get("model_settings") or cond.get("expert_inputs") or []
    pending_required = [
        s for s in settings
        if isinstance(s, dict)
        and s.get("gate") == "required-before-run"
        and (s.get("current") is None or s.get("current") == "")
    ]
    blocked_reason = None
    if pending_required:
        names = ", ".join(s.get("name", "?") for s in pending_required)
        blocked_reason = f"required-before-run settings unset: {names}"

    study_slug = spec.get("name") or "(unnamed)"
    runnable: list[dict] = []
    blocked: list[dict] = []

    # Baseline as the implicit first item.
    baseline = cond.get("baseline") or {}
    if baseline.get("composite"):
        item = {
            "study":          study_slug,
            "variant":        "baseline",
            "kind":           "baseline",
            "composite":      baseline.get("composite"),
            "params":         dict(baseline.get("params") or {}),
            "status":         "queued",
        }
        if blocked_reason:
            item["status"] = "blocked"
            item["error"] = blocked_reason
            blocked.append(item)
        else:
            runnable.append(item)

    for v in cond.get("variants") or []:
        if not isinstance(v, dict):
            continue
        item = {
            "study":          study_slug,
            "variant":        v.get("name", "?"),
            "kind":           "variant",
            "composite":      v.get("composite") or v.get("base_composite") or baseline.get("composite"),
            "params":         dict(v.get("parameter_overrides") or v.get("params") or {}),
            "status":         "queued",
        }
        if blocked_reason:
            item["status"] = "blocked"
            item["error"] = blocked_reason
            blocked.append(item)
        else:
            runnable.append(item)

    return runnable, blocked
