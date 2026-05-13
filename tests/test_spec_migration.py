"""Tests for migrating a study spec.yaml from legacy `composites:` to v2 `variants:`."""
import textwrap
import yaml

from vivarium_dashboard.lib.spec_migration import migrate_study_to_v2_vocabulary


def _write(tmp_path, body):
    p = tmp_path / 'spec.yaml'
    p.write_text(textwrap.dedent(body).lstrip())
    return p


def test_migrate_renames_composites_to_variants(tmp_path):
    p = _write(tmp_path, """
        name: s
        composites:
          - {name: a, source: pkg.a}
    """)
    migrate_study_to_v2_vocabulary(p)
    data = yaml.safe_load(p.read_text())
    assert 'composites' not in data
    assert data['variants'] == [{'name': 'a', 'source': 'pkg.a'}]


def test_migrate_nests_overrides_into_intervention(tmp_path):
    p = _write(tmp_path, """
        name: s
        composites:
          - {name: a, source: pkg.a}
          - name: b
            extends: a
            parameter_overrides: {state.x: 1.0}
            process_overrides: {p: null}
    """)
    migrate_study_to_v2_vocabulary(p)
    data = yaml.safe_load(p.read_text())
    b = data['variants'][1]
    assert b['intervention'] == {
        'description': '',
        'parameter_overrides': {'state.x': 1.0},
        'process_overrides': {'p': None},
    }
    assert 'parameter_overrides' not in b
    assert 'process_overrides' not in b


def test_migrate_sets_baseline_from_first_source_variant(tmp_path):
    p = _write(tmp_path, """
        name: s
        composites:
          - {name: a, source: pkg.a}
          - {name: b, extends: a}
    """)
    migrate_study_to_v2_vocabulary(p)
    data = yaml.safe_load(p.read_text())
    assert data['baseline'] == 'a'


def test_migrate_initializes_blank_fields(tmp_path):
    p = _write(tmp_path, """
        name: s
        composites:
          - {name: a, source: pkg.a}
    """)
    migrate_study_to_v2_vocabulary(p)
    data = yaml.safe_load(p.read_text())
    assert data['comparisons'] == []
    assert data['groups'] == []
    assert data['conclusions'] == ''
    assert data['question'] == ''
    assert data['hypothesis'] == ''
    assert data['status'] == 'draft'
    assert data['topic'] == ''


def test_migrate_initializes_groups_blank_on_v2_spec(tmp_path):
    """A v2-shape spec missing only `groups:` gets it backfilled."""
    p = _write(tmp_path, """
        name: s
        baseline: a
        question: ""
        hypothesis: ""
        status: draft
        variants:
          - {name: a, source: pkg.a}
        comparisons: []
        conclusions: ""
    """)
    migrate_study_to_v2_vocabulary(p)
    data = yaml.safe_load(p.read_text())
    assert data['groups'] == []


def test_migrate_idempotent(tmp_path):
    p = _write(tmp_path, """
        name: s
        baseline: a
        question: ""
        hypothesis: ""
        status: draft
        topic: ""
        variants:
          - {name: a, source: pkg.a}
        comparisons: []
        groups: []
        conclusions: ""
    """)
    before = p.read_text()
    migrate_study_to_v2_vocabulary(p)
    assert p.read_text() == before
