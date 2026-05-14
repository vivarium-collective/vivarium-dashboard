"""Fixture composite generators for ws_increase_demo.

hint_test is a minimal @composite_generator with default_n_steps=42 so the
/api/composites endpoint test can assert the field is surfaced.
"""
from pbg_superpowers.composite_generator import composite_generator


@composite_generator(name="hint_test", description="", parameters={},
                     default_n_steps=42)
def hint_test(core=None):
    return {}
