// src/layouts/registry.ts — the ordered set of available layout modes.
// Adding a view mode means adding one entry here.
//
// The cluster-grid packing is the sole canvas layout (mode id 'hierarchy',
// kept stable so saved layouts / default resolution / App's hub-count branch
// keep working — only the algorithm was swapped from the ELK-layered hierarchy
// to clusterGrid.ts's compact, grid-snapped, persistent packing). The former
// `process-column` mode was retired from the UI: its clustered process list
// lives on as the dockable Process panel. `hierarchy.ts` (applyLayout +
// hierarchyMode) and `processColumn.ts` remain on disk — still exercised
// directly by their unit tests — but neither drives the canvas.

import type { LayoutMode } from './types';
import { clusterGridMode } from './clusterGrid';
import { flowElkRightMode } from './flow';
import { treeMode, gridMode } from './treeFlow';

// Tree (treeMode, id 'flow-down') is the default: an org-chart nesting layout
// that reads the place-graph hierarchy top-down. (Was 'hierarchy', the
// cluster-grid packing — still available from the Layout menu.)
export const DEFAULT_MODE_ID = 'flow-down';

// hierarchy = the non-directional relationship packing (default). flow-down =
// "Tree": the place-graph org-chart with processes docked into swimlanes.
// tree-grid = "Grid": the same org-chart with every process pulled right into a
// scannable grid. flow-right = "Flow": ELK layered left→right DAG. (The former
// ELK flow-down mode is replaced by treeMode, which reuses its 'flow-down' id so
// saved top-to-bottom layouts keep resolving; flowElkDownMode stays in flow.ts
// for its unit tests.)
export const LAYOUT_MODES: LayoutMode[] = [clusterGridMode, treeMode, gridMode, flowElkRightMode];

export function getMode(id: string | null | undefined): LayoutMode {
  return LAYOUT_MODES.find((m) => m.id === id)
    ?? LAYOUT_MODES.find((m) => m.id === DEFAULT_MODE_ID)
    ?? LAYOUT_MODES[0];
}
