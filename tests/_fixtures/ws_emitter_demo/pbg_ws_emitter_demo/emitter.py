"""A minimal file-backed emitter Step that is NOT deep-copyable.

``FileEmitter.__init__`` eagerly creates a ``ThreadPoolExecutor`` — exactly the
shape of ``viva_emitters.parquet_emitter.ParquetEmitter`` (``threaded=True`` by
default), whose executor holds a ``_queue.SimpleQueue`` that raises
``TypeError: cannot pickle '_queue.SimpleQueue' object`` under ``copy.deepcopy``.

That is the live instance ``to_document()`` embeds on the realized emitter edge,
and the object that made ``export_composite_pbg`` crash when
``rewrite_local_addresses`` (which starts with ``copy.deepcopy(document)``) ran
*before* the realized-edge instance was stripped.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from process_bigraph import Step


class FileEmitter(Step):
    """Writes each observed value to a JSON file under ``out_dir``.

    Rebuilds purely from ``address`` + ``config`` (``out_dir``), so a stripped,
    portable ``.pbg`` reloads and re-emits without the original live instance.
    """

    config_schema = {
        "out_dir": {"_type": "string", "_default": "out"},
    }

    def __init__(self, config=None, core=None):
        super().__init__(config, core)
        # Eager, un-deep-copyable resource (mirrors ParquetEmitter's executor).
        self.executor = ThreadPoolExecutor(max_workers=1)
        self._count = 0

    def inputs(self):
        return {"level": "float"}

    def outputs(self):
        return {}

    def update(self, state):
        out_dir = Path((self.config or {}).get("out_dir", "out"))
        out_dir.mkdir(parents=True, exist_ok=True)
        self._count += 1
        (out_dir / f"emit_{self._count}.json").write_text(
            json.dumps({"level": state.get("level")}), encoding="utf-8"
        )
        return {}
