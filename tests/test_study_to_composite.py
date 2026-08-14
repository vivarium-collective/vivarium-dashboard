"""Tests for ``study_to_composite`` -- a Study spec compiled into a runnable
workflow composite (the end-to-end: a Study IS a workflow composite, run via
``run_workflow``, address-compatible with the dead ``resolve_study``).

Uses a toy ``@composite_generator`` (``toy_study_gen``) registered in this
module -- workbench tests must not pull in v2ecoli/ecoli_baseline.
"""
from __future__ import annotations

import os
import sys

import pytest
from bigraph_schema import allocate_core

from process_bigraph.artifacts import artifact_id
from process_bigraph.composite import Process
from process_bigraph.composite_generator import composite_generator
from process_bigraph.workflow import run_workflow
from process_bigraph.workflow.tasks import CompositeTask

from vivarium_workbench.lib.artifacts.pipeline import _workspace_commit
from vivarium_workbench.lib.study_spec import study_interface
from vivarium_workbench.lib.study_to_composite import study_to_composite


# ``CompositeTask`` fans out real ``python -m process_bigraph.run_composite
# --build`` subprocesses, which re-import the generator fresh by dotted
# module path (``import=[...]``). This test module's own dotted path would
# be ``tests.test_study_to_composite`` -- but the sibling pbg worktree this
# environment prepends onto PYTHONPATH (see module docstring / repo
# CLAUDE.md) ships an unrelated top-level ``tests.py``, which shadows any
# namespace-package ``tests/`` directory earlier on the path (PEP 420: a
# namespace portion always yields to a regular module found later in the
# search). Sidestep the collision by also putting this test module's own
# directory directly on ``PYTHONPATH`` (subprocesses inherit ``os.environ``,
# not the parent's live ``sys.path``) and importing this module by its bare
# top-level name instead of the shadowed ``tests.`` prefix.
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)
_existing_pythonpath = os.environ.get('PYTHONPATH', '')
if _TESTS_DIR not in _existing_pythonpath.split(os.pathsep):
    os.environ['PYTHONPATH'] = (
        os.pathsep.join([_TESTS_DIR, _existing_pythonpath])
        if _existing_pythonpath else _TESTS_DIR)


# ── toy generator (consumed by the compiled composite's CompositeTask) ──

class _ToyRamp(Process):
    """Advances ``level`` by ``rate`` per tick, starting at ``seed``."""

    config_schema = {'rate': 'float'}

    def inputs(self):
        return {'level': 'float'}

    def outputs(self):
        return {'level': 'float'}

    def update(self, state, interval):
        return {'level': self.config['rate'] * interval}


def _provision_toy_ramp(core):
    core.register_link('_ToyRamp', _ToyRamp)
    return core


@composite_generator(name='toy_study_gen', core_extensions=[_provision_toy_ramp])
def toy_study_gen(rate=2.0, seed=0.0):
    """No declared emitter -> resolves to the framework's RAMEmitter default
    (fine here: ``study_to_composite`` sets ``allow_in_memory_emitter=True``,
    and the toy ReportCard grades run-free off the scatter's own result
    paths, never off emitted records -- see ``study_to_composite`` module
    docs)."""
    return {'state': {
        'level': float(seed),
        'ramp': {
            '_type': 'process', 'address': 'local:_ToyRamp',
            'config': {'rate': rate},
            'inputs': {'level': ['level']}, 'outputs': {'level': ['level']}}}}


_IMPORT = ['test_study_to_composite']


def _spec(**overrides):
    spec = {
        'composite': 'toy_study_gen',
        'config': {'rate': 3.0},
        'seeds': [0, 1],
        'n_steps': 2,
        'import': _IMPORT,
    }
    spec.update(overrides)
    return spec


# ── (1) unit: compile shape ──────────────────────────────────────────────

def test_compiles_sims_as_scattered_composite_task(tmp_path):
    composite = study_to_composite(_spec(), outdir=str(tmp_path))

    # Read the built node back off the composite's own realized state.
    sims = composite.state['sims']
    # The realized address is parsed into {'protocol', 'data'}, not the raw
    # 'local:CompositeTask' string the document declared it as.
    assert sims['address'] == {'protocol': 'local', 'data': 'CompositeTask'}
    assert sims['config']['scatter_param'] == 'seed'
    assert sims['config']['generator'] == 'toy_study_gen'
    assert sims['config']['overrides'] == {'rate': 3.0}

    assert 'verdict' in composite.bridge['outputs']


def test_no_composite_raises():
    with pytest.raises(ValueError, match='composite'):
        study_to_composite({'config': {}})


def test_declared_inputs_not_yet_wired_raises():
    spec = _spec(inputs=[{'artifact': 'sim_data', 'from': 'parca'}])
    with pytest.raises(NotImplementedError, match='inputs'):
        study_to_composite(spec)


# ── (2) run: end-to-end through run_workflow ─────────────────────────────

def test_run_workflow_produces_gated_verdict(tmp_path):
    composite = study_to_composite(_spec(), outdir=str(tmp_path))
    result = run_workflow(composite, backend='local', outdir=str(tmp_path))

    assert result.status == 'ok'
    verdict = result.outputs.get('verdict')
    assert verdict is not None
    assert verdict['status'] in {'pass', 'fail', 'warn'}
    assert verdict['status'] == 'pass'  # both seeds ran -> gate passes

    results = result.outputs.get('results')
    assert set(results) == {'0', '1'}

    # Cross-check against the composite's own read_bridge().
    assert composite.read_bridge() == result.outputs


# ── (3) address parity with resolve_study ────────────────────────────────
#
# The study DAG (this compiler) and the sim cache (CompositeTask, inside the
# compiled composite) must share ONE content-addressing formula:
# ``process_bigraph.artifacts.artifact_id`` (single-sourced -- see
# ``vivarium_workbench/lib/artifacts/hashing.py``). ``resolve_study``
# (``lib/artifacts/pipeline.py:189``) computes a STUDY-level address:
#
#     artifact_id(composite_id=iface.composite, config=iface.config,
#                  input_ids=sorted(producer_ids), commit=_workspace_commit(ws))
#
# ``CompositeTask`` computes a PER-SEED address (``tasks.py:_address``):
#
#     artifact_id(composite_id=generator, config={**overrides, seed: val,
#                  'steps': steps, 'provision': provision},
#                  input_ids=sorted(ref_hashes), commit=code_version)
#
# These are deliberately NOT the same address (a per-seed sim-cache key is
# necessarily finer-grained than a per-study pull-or-compute key -- one
# study resolves to N seed runs). The precise, exact relationship this test
# pins: CompositeTask's per-seed config is iface.config extended by EXACTLY
# the scatter/steps/provision fold, and -- when ``study_to_composite`` is
# given the SAME commit ``resolve_study`` would use for this workspace (via
# its optional ``commit=`` kwarg, threaded into CompositeTask's
# ``code_version``) -- the two formulas share composite_id, config ROOT, and
# commit exactly, differing only by that documented, well-defined fold.
# For a producer-less study (this minimal slice's scope) both sides'
# ``input_ids`` are ``[]``, so the fold is the ONLY difference left.

def test_address_parity_with_resolve_study(tmp_path):
    spec = _spec()
    iface = study_interface(spec)

    # A real (non-empty) commit -- git-init tmp_path so `_workspace_commit`
    # returns the actual HEAD sha resolve_study would compute for this
    # workspace. Deliberately NOT the non-git "" case: CompositeTask's own
    # `_code_version` reads `self.config.get('code_version') or
    # _default_code_version(...)` (tasks.py) -- an *empty-string* explicit
    # commit is falsy and silently overridden by the framework-version
    # default, which would make this test's premise (both sides using the
    # SAME commit) false by an unrelated `or`-fallback quirk, not by
    # anything `study_to_composite` does.
    import subprocess
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'config', 'user.email', 'a@b.c'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'config', 'user.name', 'a'], cwd=tmp_path, check=True)
    (tmp_path / '.gitkeep').write_text('')
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'commit', '-q', '-m', 'init'], cwd=tmp_path, check=True)

    commit = _workspace_commit(tmp_path)
    assert commit  # non-empty real sha

    composite = study_to_composite(spec, outdir=str(tmp_path), commit=commit)
    sims_config = composite.state['sims']['config']
    assert sims_config['code_version'] == commit

    # Reconstruct the per-seed sim-cache address via the REAL CompositeTask
    # (not a reimplementation of its formula).
    task = CompositeTask(sims_config, core=allocate_core())
    for seed in spec['seeds']:
        actual = task._address(entry=None, val=seed, ref_hashes=[])
        expected = artifact_id(
            composite_id=iface['composite'],
            config={**iface['config'], 'seed': seed,
                    'steps': sims_config['steps'], 'provision': []},
            input_ids=[],
            commit=commit,
        )
        assert actual == expected, (
            f'seed {seed}: CompositeTask per-seed address does not match '
            f'iface.config folded with {{seed, steps, provision}} at the '
            f'same commit resolve_study would use')

    # Call the REAL `resolve_study` (not a reimplementation of its formula
    # either) against a study.yaml written to this same git workspace, and
    # confirm its study-level address is exactly the fold-free root that
    # every per-seed CompositeTask address above extends.
    import yaml
    from vivarium_workbench.lib.artifacts.pipeline import resolve_study

    (tmp_path / 'studies' / 'toy').mkdir(parents=True)
    (tmp_path / 'studies' / 'toy' / 'study.yaml').write_text(yaml.safe_dump({
        'name': 'toy', 'composite': iface['composite'], 'config': iface['config'],
    }))

    def _stub_compute(ws_root, slug, *, artifact_id, composite, config,
                       input_ids, out_dir, resolved_inputs=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / 'out.bin'
        p.write_bytes(b'toy')
        return p

    resolved = resolve_study(tmp_path, 'toy', compute_fn=_stub_compute)
    study_level_address = resolved['artifact_id']

    assert study_level_address == artifact_id(
        composite_id=iface['composite'], config=iface['config'],
        input_ids=[], commit=commit,
    ), 'resolve_study must use the exact fold-free root the CompositeTask addresses extend'

    # It differs from every per-seed address (finer- vs. study-granularity)
    # -- but shares the same composite_id/commit/hash function, and its
    # config is exactly what's left of the per-seed config once the fold
    # (seed/steps/provision) is stripped back out. THIS is the precise
    # relationship linking the study DAG's cache to the per-seed sim cache.
    for seed in spec['seeds']:
        per_seed = task._address(entry=None, val=seed, ref_hashes=[])
        assert per_seed != study_level_address
