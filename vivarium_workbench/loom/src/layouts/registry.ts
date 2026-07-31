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
import { flowDownMode, flowRightMode } from './flow';

export const DEFAULT_MODE_ID = 'hierarchy';

// hierarchy = the non-directional relationship packing (default). flow-tb /
// flow-lr = directional flow-network layouts (see the direction switch).
export const LAYOUT_MODES: LayoutMode[] = [clusterGridMode, flowDownMode, flowRightMode];

export function getMode(id: string | null | undefined): LayoutMode {
  return LAYOUT_MODES.find((m) => m.id === id)
    ?? LAYOUT_MODES.find((m) => m.id === DEFAULT_MODE_ID)
    ?? LAYOUT_MODES[0];
}
