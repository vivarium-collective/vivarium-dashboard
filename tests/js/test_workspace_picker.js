// tests/js/test_workspace_picker.js — run with: node tests/js/test_workspace_picker.js
//
// Exercises the pure helpers of static/workspace-picker.js (the sleek header
// workspace switcher): filterWorkspaces() search + current-first sort, and
// statusMeta() status → dot/class mapping. The module short-circuits to
// module.exports in Node, so requiring it does not touch the DOM.
const assert = require('assert');
const wp = require('../../vivarium_workbench/static/workspace-picker.js');

function run() {
  var items = [
    { name: 'ecoli-v2', label: 'ecoli-v2', status: 'stopped' },
    { name: 'increase-demo', label: 'increase-demo', status: 'current' },
    { name: 'glycolysis-sweep', label: 'glycolysis-sweep', status: 'stopped' },
  ];

  // empty query → all, current first.
  var all = wp.filterWorkspaces(items, '');
  assert.strictEqual(all.length, 3, 'empty query returns all');
  assert.strictEqual(all[0].status, 'current', 'current workspace sorts first');
  assert.strictEqual(all[1].name, 'ecoli-v2', 'rest sort alphabetically (ecoli before glycolysis)');

  // substring filter (case-insensitive).
  var g = wp.filterWorkspaces(items, 'GLY');
  assert.strictEqual(g.length, 1, 'filter matches by case-insensitive substring');
  assert.strictEqual(g[0].name, 'glycolysis-sweep', 'filter selects the right workspace');

  // no match → empty.
  assert.strictEqual(wp.filterWorkspaces(items, 'zzz').length, 0, 'no match → empty list');

  // null-safe.
  assert.strictEqual(wp.filterWorkspaces(null, '').length, 0, 'null items → empty');

  // statusMeta → dot + class.
  assert.strictEqual(wp.statusMeta('current').cls, 'ready', 'current → ready');
  assert.strictEqual(wp.statusMeta('running').cls, 'ready', 'running → ready');
  assert.strictEqual(wp.statusMeta('stopped').cls, 'stopped', 'stopped → stopped');
  assert.strictEqual(wp.statusMeta('stale').cls, 'stale', 'stale → stale');
  assert.strictEqual(wp.statusMeta('missing').cls, 'missing', 'missing → missing');
  assert.strictEqual(wp.statusMeta('bogus').cls, 'stopped', 'unknown → stopped fallback');
  assert.strictEqual(typeof wp.statusMeta('current').dot, 'string', 'meta carries a dot glyph');

  console.log('test_workspace_picker.js: all assertions passed');
}

try { run(); } catch (e) { console.error(e); process.exit(1); }
