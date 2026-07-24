// src/hooks/useFocus.ts — which processes are "active" right now.
//
// focused = hover ∪ selection (transient). pinned = explicit, accumulates,
// so two processes' wiring can be compared side by side.
//
// `ctx` is memoized on the three primitives, NOT rebuilt per render: the edge
// filter memoizes on `ctx` identity, and a fresh Set every render would make
// that memo a no-op and re-filter several hundred edges on every mouse move.
// The setters likewise no-op when the value is unchanged, so sliding across one
// process card's interior does not churn state.

import { useCallback, useMemo, useState } from 'react';
import type { FocusContext } from '../layouts/types';

export interface UseFocus {
  hovered: string | null;
  selected: string | null;
  pinned: Set<string>;
  /** The single "locked" node — set by a plain canvas click, which both selects
   *  (Inspector) and pins its wiring persistently. Distinct from the multi-`pinned`
   *  comparison set: a plain click on another node SWITCHES the lock (replaces
   *  it), where a pin accumulates. `null` when nothing is locked. */
  locked: string | null;
  hover: (id: string | null) => void;
  select: (id: string | null) => void;
  togglePin: (id: string) => void;
  /** Lock a node (select it AND persistently highlight its wiring), replacing any
   *  prior lock; `lock(null)` unlocks and deselects. */
  lock: (id: string | null) => void;
  clear: () => void;
  /** Drop any pin `isLive` rejects (e.g. a pinned node just got hidden). A
   *  no-op — same Set identity — when nothing needed pruning. Also clears the
   *  lock if the locked node is no longer live. */
  prunePins: (isLive: (id: string) => boolean) => void;
  ctx: FocusContext;
}

export function useFocus(): UseFocus {
  const [hovered, setHovered] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [pinned, setPinned] = useState<Set<string>>(() => new Set());
  const [locked, setLocked] = useState<string | null>(null);

  const togglePin = useCallback((id: string) => {
    setPinned((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }, []);

  // A plain click both selects (drives the Inspector) and locks (persistent wire
  // highlight). Clicking another node replaces the lock; lock(null) unlocks.
  const lock = useCallback((id: string | null) => {
    setLocked(id);
    setSelected(id);
  }, []);

  const clear = useCallback(() => {
    setHovered(null);
    setSelected(null);
    setLocked(null);
    setPinned((prev) => (prev.size === 0 ? prev : new Set()));
  }, []);

  const prunePins = useCallback((isLive: (id: string) => boolean) => {
    setPinned((prev) => {
      let changed = false;
      const next = new Set<string>();
      for (const id of prev) {
        if (isLive(id)) next.add(id);
        else changed = true;
      }
      return changed ? next : prev;
    });
    setLocked((prev) => (prev && !isLive(prev) ? null : prev));
  }, []);

  const ctx = useMemo<FocusContext>(() => {
    const focused = new Set<string>();
    if (hovered) focused.add(hovered);
    if (selected) focused.add(selected);
    // The locked node's wiring must stay highlighted at any zoom, so fold it into
    // the pinned set the edge filter reads. Only mint a new Set when the lock adds
    // something the comparison-pin set doesn't already carry.
    let pinnedOut = pinned;
    if (locked && !pinned.has(locked)) {
      pinnedOut = new Set(pinned);
      pinnedOut.add(locked);
    }
    return { focused, pinned: pinnedOut };
  }, [hovered, selected, pinned, locked]);

  return {
    hovered, selected, pinned, locked,
    hover: setHovered, select: setSelected,
    togglePin, lock, clear, prunePins, ctx,
  };
}
