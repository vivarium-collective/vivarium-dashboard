/** Display name for a node title: underscores become spaces so a long name
 *  (e.g. `structural_packing` → "structural packing") reads cleanly AND can wrap
 *  onto two lines at that space when the card is narrow. Display-only — the
 *  underlying node id / path is unchanged, so wiring + name-pattern logic (emitter
 *  / viz classification) still see the raw name. */
export const displayName = (s: unknown): string => String(s ?? '').replace(/_/g, ' ');
