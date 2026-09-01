"""Fixture workspace package: a composite with a live file-backed emitter.

Importing the package fires the ``@composite_generator`` decorator so the
composite is discoverable by ``process_bigraph.composite_spec.get``.
"""
from . import composites  # noqa: F401
