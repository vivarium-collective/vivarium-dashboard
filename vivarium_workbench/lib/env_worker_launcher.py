"""How an env worker comes into being — the `EnvironmentResolver`'s one seam.

The pool (``env_worker_pool``) owns *when* a worker is created and reused; this
module owns *how*. There are exactly two ways, and which one a deployment uses is
**not a per-call choice**:

* **Local** — spawn a subprocess over a ``socketpair`` against the workspace's own
  interpreter. What a laptop does, because a laptop has no cluster.
* **Remote** — ask viva-api to run the simulator's **prebuilt image** as a worker
  in its own pod, and let it dial back (REFACTOR-PLAN §2A.8, #942). What a hosted
  deployment does, because hosted never builds an environment.

**Selected by deployment topology, not preference** (§2A.8). One wiring decision
at the composition root (§5C.4) — ``default_launcher()`` — so there is nothing to
cherry-pick per call site, and the two implementations cannot drift into being
alternatives someone chooses between.

Both produce an ``EnvWorker`` speaking the identical protocol; everything above
the connection is shared (spec §2).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from vivarium_workbench.lib.env_compat import get_env
from vivarium_workbench.lib.env_worker_client import EnvWorker, EnvWorkerUnavailable
from vivarium_workbench.lib.env_worker_dialback import DialBackError, DialBackListener

logger = logging.getLogger(__name__)

# How long to wait for a worker pod to schedule, pull (usually cached) and dial
# back. Generous and deliberately distinct from the per-call timeout: this covers
# Kubernetes, not the protocol.
REMOTE_START_TIMEOUT = 300.0


class WorkerLauncher(Protocol):
    """Create one worker for a workspace. The pool decides when; this decides how."""

    #: Distinguishes workers in the pool's key. A local and a remote worker for
    #: the same (workspace, interpreter) are different environments and must not
    #: share a pool entry.
    kind: str

    def env_key(self, workspace: str) -> str:
        """Identify the environment this launcher would give the workspace.

        The pool keys warm workers on it, so it must distinguish environments that
        differ and match ones that don't. It is the launcher's to answer because
        only the launcher knows what the environment IS: a local worker's is the
        interpreter it spawns, a remote worker's is the image it runs — and asking
        the workspace for an interpreter it will never use is what broke the
        venv-less hosted workspace (a strict-mode resolve raised before the remote
        launcher, which ignores interpreters, was ever chosen).
        """
        ...

    def launch(self, workspace: str, *, interpreter: str | None, timeout: float) -> EnvWorker:
        ...


class LocalWorkerLauncher:
    """Spawn a subprocess against the workspace's interpreter (today's behavior)."""

    kind = "local"

    def env_key(self, workspace: str) -> str:
        from vivarium_workbench.lib import env_resolver
        return env_resolver.resolve_interpreter(workspace)

    def launch(self, workspace: str, *, interpreter: str | None, timeout: float) -> EnvWorker:
        return EnvWorker(workspace, interpreter=interpreter, timeout=timeout)


class RemoteEnvWorker(EnvWorker):
    """An ``EnvWorker`` whose peer is a Kubernetes Job.

    Overrides ``close`` so ending a session also deletes the Job. Without this a
    worker pod outlives its only client and is reachable by nobody — the leak the
    TTL backstop exists to catch, and which should not be the normal path.
    """

    _job_name: str
    _client: object

    def close(self) -> None:
        try:
            super().close()
        finally:
            try:
                self._client.stop_env_worker(self._job_name)  # type: ignore[attr-defined]
            except Exception as e:  # noqa: BLE001 — teardown must not raise into the pool
                logger.warning("env-worker Job %s not deleted: %s", self._job_name, e)


class RemoteWorkerLauncher:
    """Run the simulator's prebuilt image as a worker; it dials back to us.

    ``advertise_host`` is where the worker connects — this pod's IP, which the
    deployment supplies (Downward API). We do not discover it: viva-api would need
    pod-get to look it up, and we already know it.
    """

    kind = "remote"

    def __init__(self, client, *, advertise_host: str, bind_host: str = "0.0.0.0"):
        self._client = client
        self._advertise_host = advertise_host
        self._bind_host = bind_host

    def env_key(self, workspace: str) -> str:
        """The image, named by the commit its build stamp pins.

        NOT the interpreter: the worker runs the simulator image's own Python and
        never sees a path from this filesystem. Keying on the commit also keeps a
        re-materialized workspace from being served by a warm worker still running
        the image it was pinned to before.
        """
        return f"image:{self._require_commit(workspace)}"

    def _require_commit(self, workspace: str) -> str:
        commit = _commit_for_workspace(workspace)
        if not commit:
            # Hosted requires every served workspace to be image-backed (§2A.8).
            # Say which workspace and why, rather than failing later inside a call.
            raise EnvWorkerUnavailable(
                f"workspace {workspace} has no build stamp (.viv-build.json); a hosted "
                "env worker runs the simulator's prebuilt image and needs its commit"
            )
        return commit

    def launch(self, workspace: str, *, interpreter: str | None, timeout: float) -> EnvWorker:
        commit = self._require_commit(workspace)
        with DialBackListener(bind_host=self._bind_host) as listener:
            handle = self._client.start_env_worker(
                commit=commit,
                callback_host=self._advertise_host,
                callback_port=listener.port,
                token=listener.token,
            )
            job_name = handle.get("job_name", "")
            try:
                sock = listener.accept(timeout=REMOTE_START_TIMEOUT)
            except DialBackError as e:
                # The pod never called home. Delete it — otherwise it lingers until
                # TTL — and surface the worker's own logs, which say why far better
                # than the timeout does.
                logs = _safe_logs(self._client, job_name)
                _safe_stop(self._client, job_name)
                raise EnvWorkerUnavailable(
                    f"env worker for {commit} did not connect: {e}"
                    + (f"\nworker logs:\n{logs}" if logs else "")
                ) from e

        worker = RemoteEnvWorker.from_socket(sock, workspace, timeout=timeout)
        worker._job_name = job_name
        worker._client = self._client
        logger.info("remote env worker ready for %s (commit %s, job %s)", workspace, commit, job_name)
        return worker


def _commit_for_workspace(workspace: str) -> str | None:
    """The commit a materialized build was stamped with.

    ``materialize_build`` writes ``.viv-build.json``; that stamp is the link from a
    served workspace to the image that IS its environment.
    """
    import json

    stamp = Path(workspace) / ".viv-build.json"
    try:
        data = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    commit = data.get("commit")
    return str(commit) if commit else None


def _safe_logs(client, job_name: str) -> str | None:
    try:
        return client.env_worker_status(job_name, include_logs=True).get("logs")
    except Exception:  # noqa: BLE001 — diagnostics must never mask the real error
        return None


def _safe_stop(client, job_name: str) -> None:
    try:
        client.stop_env_worker(job_name)
    except Exception:  # noqa: BLE001
        logger.warning("could not delete env-worker Job %s", job_name)


def default_launcher() -> WorkerLauncher:
    """The composition root (§5C.4): one decision, made from deployment config.

    Remote when this deployment declares where workers should dial back to;
    local otherwise. Deliberately not a per-call or per-workspace switch.
    """
    host = get_env("ENV_WORKER_ADVERTISE_HOST", "") or ""
    if not host.strip():
        return LocalWorkerLauncher()
    from vivarium_workbench.lib.sms_api_client import SmsApiClient
    from vivarium_workbench.lib.workspace_deps_views import _sms_api_base

    # The SAME accessor every other viva-api call site uses (VIVA_API_BASE, else
    # SMS_API_BASE). Constructing SmsApiClient() bare would silently take its
    # localhost:8080 default — which in a pod is the workbench itself, not the
    # api Service, so every worker launch would fail to reach viva-api.
    base = _sms_api_base()
    logger.info("env workers: REMOTE (image-as-worker), dial-back to %s, api at %s", host, base)
    return RemoteWorkerLauncher(SmsApiClient(base), advertise_host=host.strip())
