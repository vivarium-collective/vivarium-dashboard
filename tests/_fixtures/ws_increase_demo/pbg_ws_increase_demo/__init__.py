"""Fixture workspace package: a trivial IncreaseProcess composite for testing."""
# Import composites submodule so @composite_generator decorators fire when
# this package is imported during generator discovery.
from . import composites  # noqa: F401
