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

``put`` is idempotent by default: if the id is already present, the existing
artifact is returned unchanged (store hit wins), regardless of what ``src``
currently contains. Pass ``overwrite=True`` to force a refresh of an
already-present id's payload + meta (e.g. a caller that deliberately bypassed
its own read-cache and recomputed wants the new content actually persisted,
not silently discarded).

Payload replacement is ATOMIC (mirrors ``atomic_io.atomic_write_text``'s
write-to-sibling-then-``os.replace`` idiom): the new payload is fully built
at a sibling ``.new-<unique>`` path first, and only then swapped into place
via ``os.replace`` — ``dest`` is never removed before its replacement is
fully written. This matters most for ``overwrite=True``: without it, a
crash mid-copy would leave ``dest`` deleted (or partially overwritten) while
``meta.json`` (unchanged, written by an *earlier* successful ``put``) still
reports ``has() == True`` — a reader would trust a corrupt/missing artifact.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from vivarium_workbench.lib.atomic_io import atomic_write_text
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _unique_suffix() -> str:
    return f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


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

    def put(self, artifact_id: str, src: Path | str, meta: dict, *, overwrite: bool = False) -> Path:
        if self.has(artifact_id) and not overwrite:
            return self.path(artifact_id)

        src = Path(src)
        d = self._dir(artifact_id)
        d.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            dest = d / "payload"
            self._atomic_replace_dir(src, dest)
        else:
            dest = d / "artifact.bin"
            self._atomic_replace_file(src, dest)

        atomic_write_text(self._meta_path(artifact_id), json.dumps(meta, indent=2))
        return dest

    @staticmethod
    def _atomic_replace_dir(src: Path, dest: Path) -> None:
        """Copy ``src`` to a sibling scratch dir, then atomically swap it
        into ``dest``. ``os.replace`` can rename directly onto ``dest`` when
        ``dest`` doesn't yet exist (the common fresh-write case); when
        ``dest`` already holds a prior payload (the ``overwrite=True`` case),
        POSIX ``rename`` refuses to replace a non-empty directory, so the old
        one is renamed aside first (also an atomic, near-instant metadata-only
        op) and best-effort ``rmtree``'d only after the new payload is
        already live at ``dest``.
        """
        suffix = _unique_suffix()
        new_dir = dest.parent / f"{dest.name}.new-{suffix}"
        if new_dir.exists():
            shutil.rmtree(new_dir)
        shutil.copytree(src, new_dir)

        if dest.exists():
            old_dir = dest.parent / f"{dest.name}.old-{suffix}"
            os.replace(dest, old_dir)
            os.replace(new_dir, dest)
            shutil.rmtree(old_dir, ignore_errors=True)
        else:
            os.replace(new_dir, dest)

    @staticmethod
    def _atomic_replace_file(src: Path, dest: Path) -> None:
        """Copy ``src`` to a sibling scratch file, then atomically swap it
        into ``dest`` — ``os.replace`` on a file always atomically replaces
        an existing destination, no separate delete/aside step needed."""
        suffix = _unique_suffix()
        new_file = dest.parent / f"{dest.name}.new-{suffix}"
        shutil.copy2(src, new_file)
        os.replace(new_file, dest)

    def meta(self, artifact_id: str) -> dict:
        return json.loads(self._meta_path(artifact_id).read_text())

    def ids(self) -> list[str]:
        """Every artifact id present in the store, sorted.

        Only fully-written entries count — an id with no ``meta.json`` is a
        partial or interrupted ``put``, exactly as ``has()`` defines it.
        """
        if not self.base.is_dir():
            return []
        return sorted(
            d.name for d in self.base.iterdir()
            if d.is_dir() and (d / "meta.json").is_file())

    def rekey(self, old_id: str, new_id: str) -> bool:
        """Move an artifact to a new address. Returns True if it moved.

        For an address-formula change: the bytes are unchanged, only where
        they live. A directory rename, so it is near-instant and atomic
        whatever the payload's size.

        Idempotent by design, because a migration must be safe to re-run:
        nothing at ``old_id`` (already migrated, or never present) is a no-op,
        and something already at ``new_id`` is left alone rather than
        clobbered — a store hit at the new address is the outcome the
        migration wanted, and the old entry is reported so the caller can
        decide about it rather than losing it silently.
        """
        if old_id == new_id:
            return False
        source, dest = self._dir(old_id), self._dir(new_id)
        if not (source / "meta.json").is_file():
            return False
        if (dest / "meta.json").is_file():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, dest)
        return True
