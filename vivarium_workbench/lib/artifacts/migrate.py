"""Re-key an artifact store after a content-address formula change.

process-bigraph 1.7.0 fixed whole-float narrowing: `canonical` had always
*claimed* to make ``seed: 1`` and ``seed: 1.0`` the same address and had never
actually done it, because it hung the narrowing on json's ``default=`` hook,
which only fires for values json cannot encode. A float can be encoded, so the
hook never ran.

**What that means for an existing store.** The relation between the two
formulas is exact::

    artifact_id(config) == legacy_artifact_id(narrow_whole_floats(config))

So an artifact whose config contains no whole-valued float **does not move at
all**, and one whose config spells a whole number as a float moves onto the
address its int-spelled twin already had. This is a targeted rename of a
minority of entries, not a rehash of the store — and the bytes never change,
only the directory they sit in.

**Where the old address comes from.** Two sources, tried in order:

1. ``meta.json``'s ``address_inputs`` — recorded from this release onward.
   Exact, and works for artifacts produced at any commit.
2. The workspace itself — ``study.yaml`` gives a study's composite and
   config, and the input ids come from resolving its producers. This is what
   covers artifacts written *before* ``address_inputs`` existed, but it can
   only reconstruct addresses for studies the workspace still declares, at
   the workspace's current commit.

Anything neither source explains is **logged as orphaned, never deleted**. An
orphan costs a recompute on next use; deleting one that was still reachable
would cost the data. The asymmetry decides it.

Re-running is a no-op: :meth:`ArtifactStore.rekey` skips an entry that has
already moved and refuses to clobber one already at the destination.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from process_bigraph.artifacts import artifact_id, legacy_artifact_id

from vivarium_workbench.lib.artifacts.store import ArtifactStore


@dataclass
class MigrationReport:
    """What the migration did, and what it could not account for."""

    moved: list[tuple[str, str]] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    already_migrated: list[str] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)

    @property
    def scanned(self) -> int:
        return (len(self.moved) + len(self.unchanged)
                + len(self.already_migrated) + len(self.orphaned))

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "moved": [{"from": old, "to": new} for old, new in self.moved],
            "unchanged": list(self.unchanged),
            "already_migrated": list(self.already_migrated),
            "orphaned": list(self.orphaned),
        }

    def summary(self) -> str:
        lines = [
            f"scanned {self.scanned} artifact(s)",
            f"  moved:            {len(self.moved)}",
            f"  unchanged:        {len(self.unchanged)}",
            f"  already migrated: {len(self.already_migrated)}",
            f"  orphaned:         {len(self.orphaned)}",
        ]
        for old, new in self.moved:
            lines.append(f"    {old} -> {new}")
        if self.orphaned:
            lines.append(
                "  orphaned artifacts cannot be re-keyed (no recorded "
                "address inputs, and no current study explains them). They "
                "are left in place and will be recomputed on next use:")
            lines.extend(f"    {oid}" for oid in self.orphaned)
        return "\n".join(lines)


def _recorded_address_inputs(meta: dict) -> dict | None:
    """The address inputs a self-describing artifact carries, if any."""
    recorded = (meta or {}).get("address_inputs")
    if not isinstance(recorded, dict):
        return None
    if not {"composite_id", "config", "input_ids", "commit"} <= set(recorded):
        return None
    return recorded


def _addresses_from_workspace(ws_root: Path) -> tuple[dict[str, dict],
                                                      dict[str, str]]:
    """Map every address the current workspace explains to its address inputs.

    Reconstructs each declared study's address inputs the way the pipeline
    would. The map is keyed by the address under **both** formulas, not just
    the legacy one: after a migration the artifact sits at its new address,
    and a re-run that only knew legacy addresses would fail to recognise its
    own work and report it as orphaned.

    Studies the workspace no longer declares, and artifacts produced at an
    older commit, simply do not appear here — they become orphans, which is
    the honest answer rather than a guess.
    """
    from vivarium_workbench.lib.artifacts import pipeline
    from vivarium_workbench.lib.study_spec import study_interface

    commit = pipeline._workspace_commit(ws_root)
    explained: dict[str, dict] = {}
    remap: dict[str, str] = {}
    resolved: dict[str, tuple[str, str] | None] = {}

    def walk(slug: str, seen: frozenset[str]) -> tuple[str, str] | None:
        """Return ``(legacy_address, new_address)`` for ``slug``.

        Both are needed, and they must be built from *matching* generations
        of upstream ids: an address folds in its inputs' addresses, so a
        downstream's new address uses its producers' NEW ids. Mixing the new
        formula with legacy input ids would compute an address nothing will
        ever look for.
        """
        if slug in resolved:
            return resolved[slug]
        if slug in seen:            # a cycle: the pipeline rejects these too
            return None
        try:
            iface = study_interface(pipeline._load_study_spec(ws_root, slug))
        except Exception:
            return None             # not a study we can read; leave to orphans

        legacy_inputs, new_inputs = [], []
        for inp in iface["inputs"]:
            upstream = walk(inp["from"], seen | {slug})
            if upstream is None:
                resolved[slug] = None
                return None         # an unresolvable producer poisons the id
            legacy_inputs.append(upstream[0])
            new_inputs.append(upstream[1])

        common = {"composite_id": iface["composite"] or slug,
                  "config": iface["config"], "commit": commit}
        address_inputs = {**common, "input_ids": sorted(new_inputs)}

        legacy = legacy_artifact_id(
            **{**common, "input_ids": sorted(legacy_inputs)})
        new = artifact_id(**address_inputs)

        # Keyed under both generations: before a migration the artifact sits
        # at the legacy address, after one it sits at the new address, and a
        # re-run must recognise its own work rather than call it orphaned.
        explained[legacy] = address_inputs
        explained[new] = address_inputs
        remap[legacy] = new
        resolved[slug] = (legacy, new)
        return legacy, new

    for slug in _declared_slugs(ws_root):
        walk(slug, frozenset())

    return explained, remap


def _declared_slugs(ws_root: Path) -> list[str]:
    """Every study slug the workspace declares.

    ``iter_study_dirs`` is the workspace's own answer to this — flat and
    nested layouts, top-level winning a slug collision — so the migration
    sees exactly the studies the pipeline would.
    """
    from vivarium_workbench.lib.workspace_paths import WorkspacePaths

    return [d.name for d in WorkspacePaths.load(ws_root).iter_study_dirs()]


def migrate_artifacts(ws_root: Path | str, *,
                      dry_run: bool = False) -> MigrationReport:
    """Re-key ``ws_root``'s artifact store onto the current address formula.

    Idempotent: re-running finds nothing left to move.

    ``dry_run`` reports what would happen without touching the store — worth
    running first, since the orphan list is the part a caller may want to act
    on before anything moves.
    """
    ws_root = Path(ws_root)
    store = ArtifactStore(ws_root)
    report = MigrationReport()

    from_workspace, remap = _addresses_from_workspace(ws_root)

    for old_id in store.ids():
        try:
            meta = store.meta(old_id)
        except (OSError, ValueError):
            report.orphaned.append(old_id)
            continue

        recorded = _recorded_address_inputs(meta)
        if recorded is not None:
            # The recorded `input_ids` are the producers' addresses *as of
            # when this artifact was stored* — legacy ones for anything
            # written before the fix. A producer that moves takes its
            # consumer's address with it, so remap them before rehashing.
            recorded = {**recorded, "input_ids": sorted(
                remap.get(i, i) for i in recorded["input_ids"])}

        inputs = recorded or from_workspace.get(old_id)
        if inputs is None:
            report.orphaned.append(old_id)
            continue

        new_id = artifact_id(**inputs)
        if new_id == old_id:
            report.unchanged.append(old_id)
            continue

        if store.has(new_id):
            # Already at the destination — a previous run moved it, or the
            # int-spelled twin was computed independently. Either way the new
            # address resolves, so the migration's goal is met.
            report.already_migrated.append(old_id)
            continue

        if not dry_run:
            store.rekey(old_id, new_id)
        report.moved.append((old_id, new_id))

    return report
