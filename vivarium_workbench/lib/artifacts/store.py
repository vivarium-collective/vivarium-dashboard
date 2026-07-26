"""Content-addressed artifact store.

Keyed by an already-computed ``artifact_id`` string (see ``hashing.py``).
Each artifact lives under ``<workspace>/.pbg/artifacts/<artifact_id>/`` (the
exact base dir is layout-aware via ``WorkspacePaths``, never hardcoded), and
holds the payload plus a ``meta.json``.

Payloads may be a single file (copied to ``artifact.bin``) or a directory
(copied to ``payload/`` — sim_data caches and zarr stores are directories).
``meta.json`` is written last, atomically, so ``has()`` only reports true once
an artifact is fully written — a partial/interrupted copy is never mistaken
for a store hit.

``put`` is idempotent: if the id is already present, the existing artifact is
returned unchanged (store hit wins), regardless of what ``src`` currently
contains.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from vivarium_workbench.lib.atomic_io import atomic_write_text
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


class ArtifactStore:
    """Content-addressed store rooted at ``<workspace>/.pbg/artifacts``."""

    def __init__(self, ws_root: Path | str):
        self.base = WorkspacePaths.load(ws_root).pbg / "artifacts"

    def _dir(self, artifact_id: str) -> Path:
        return self.base / artifact_id

    def _meta_path(self, artifact_id: str) -> Path:
        return self._dir(artifact_id) / "meta.json"

    def has(self, artifact_id: str) -> bool:
        return self._meta_path(artifact_id).is_file()

    def path(self, artifact_id: str) -> Path:
        d = self._dir(artifact_id)
        file_payload = d / "artifact.bin"
        if file_payload.exists():
            return file_payload
        return d / "payload"

    def put(self, artifact_id: str, src: Path | str, meta: dict) -> Path:
        if self.has(artifact_id):
            return self.path(artifact_id)

        src = Path(src)
        d = self._dir(artifact_id)
        d.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            dest = d / "payload"
            # Retry-safe: a prior put() may have crashed after copytree
            # started but before meta.json was written, leaving a partial
            # dest dir. Since has() is False in that case, clear it before
            # retrying — copytree raises FileExistsError on an existing dest.
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
        else:
            dest = d / "artifact.bin"
            # copy2 overwrites cleanly, but be explicit/defensive in case
            # dest is ever a directory left over from some other state.
            if dest.exists():
                dest.unlink()
            shutil.copy2(src, dest)

        atomic_write_text(self._meta_path(artifact_id), json.dumps(meta, indent=2))
        return dest

    def meta(self, artifact_id: str) -> dict:
        return json.loads(self._meta_path(artifact_id).read_text())
