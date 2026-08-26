import { describe, it, expect } from 'vitest';
import { isPlaybackStep } from '../topoPlayback';

describe('isPlaybackStep', () => {
  it('is a playback step while stepping frames on a live trajectory', () => {
    expect(isPlaybackStep(true, 2, 5, false)).toBe(true);
  });

  it('yields to an intentional view apply mid-trajectory (the bug fix)', () => {
    // applyView set applyingView=true → NOT a playback step → full apply wins,
    // so restoring/applying a saved view is no longer dropped on a running composite.
    expect(isPlaybackStep(true, 2, 5, true)).toBe(false);
  });

  it('is not a playback step when there is no trajectory', () => {
    expect(isPlaybackStep(false, 2, 5, false)).toBe(false);
    expect(isPlaybackStep(true, null, 5, false)).toBe(false);
  });

  it('is not a playback step on the first build (no prior nodes)', () => {
    expect(isPlaybackStep(true, 0, 0, false)).toBe(false);
  });
});
