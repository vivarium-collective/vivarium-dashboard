// src/topoPlayback.ts — when the layout effect rebuilds nodes for a live
// TOPOLOGY trajectory, it must decide between two behaviours:
//
//   playback frame-step → keep every on-screen node where it is, place only new
//                         nodes (smooth stepping, no jitter)
//   intentional view apply → do a FULL apply of the view's saved positions,
//                            even mid-trajectory (restore / apply a saved view)
//
// Getting this wrong is the "saved view is gone after I switch and come back on a
// running composite" bug: the playback branch ran on EVERY pass and silently
// dropped applyView. Keep the decision here so it is unit-tested.

/** True when this rebuild is a playback frame-step (keep positions), NOT an
 *  intentional view application. `applyingView` (set by applyView) forces a full
 *  apply so the view's positions win over the current on-screen arrangement. */
export function isPlaybackStep(
  isTopoTraj: boolean,
  frameIdx: number | null,
  prevCount: number,
  applyingView: boolean,
): boolean {
  return isTopoTraj && frameIdx !== null && prevCount > 0 && !applyingView;
}
