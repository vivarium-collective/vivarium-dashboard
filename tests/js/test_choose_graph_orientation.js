// tests/js/test_choose_graph_orientation.js — run with: node tests/js/test_choose_graph_orientation.js
const assert = require('assert');
const { chooseGraphOrientation } = require('../../vivarium_workbench/static/aig-graph.js');

// Wide/shallow: 12 unlinked studies, all roots, single depth level -> TB (fill
// vertical space with rows instead of squishing one wide column).
assert.strictEqual(chooseGraphOrientation({ 0: 12 }), 'TB', 'wide/shallow -> TB');

// Deep/narrow: a single 4-long chain, one study per depth level -> LR (reads as
// a left-to-right sequence).
assert.strictEqual(chooseGraphOrientation({ 0: 1, 1: 1, 2: 1, 3: 1 }), 'LR', 'deep/narrow -> LR');

// maxDepth <= 2 forces TB even if not obviously "wide" (two levels reads as a
// short, flat graph best filled top-to-bottom).
assert.strictEqual(chooseGraphOrientation({ 0: 2, 1: 3 }), 'TB', 'shallow (<=2 levels) -> TB');

// A level wider than the graph is deep -> TB even with several levels.
assert.strictEqual(chooseGraphOrientation({ 0: 1, 1: 8, 2: 1 }), 'TB', 'a wide level -> TB');

// More levels than the widest level -> LR.
assert.strictEqual(chooseGraphOrientation({ 0: 1, 1: 2, 2: 2, 3: 1, 4: 1 }), 'LR', 'more levels than breadth -> LR');

// Empty/degenerate input doesn't throw and returns a valid orientation.
assert.ok(['LR', 'TB'].indexOf(chooseGraphOrientation({})) !== -1, 'empty depthCounts -> valid orientation');
assert.ok(['LR', 'TB'].indexOf(chooseGraphOrientation()) !== -1, 'undefined depthCounts -> valid orientation');

console.log('ok test_choose_graph_orientation');
