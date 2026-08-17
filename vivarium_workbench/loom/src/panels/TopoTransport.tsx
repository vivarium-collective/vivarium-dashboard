// src/panels/TopoTransport.tsx — the run PLAYBACK transport (step / play / scrub).
//
// Extracted so the run bar and the chromeless embed share ONE control: after a
// run produces a trajectory, this sits INLINE in the run bar (run + step are one
// unified control), rather than floating separately over the canvas.
export interface TopoTransportProps {
  frameIdx: number;
  frameCount: number;
  frameTime?: number;
  playing: boolean;
  onPrev: () => void;
  onNext: () => void;
  onToggle: () => void;
  onScrub: (i: number) => void;
  onExit: () => void;
}

export function TopoTransport(props: TopoTransportProps) {
  const { frameIdx, frameCount, frameTime, playing } = props;
  return (
    <div className="topo-transport">
      <span className="topo-transport-title">Step</span>
      <button onClick={props.onPrev} disabled={frameIdx <= 0} title="Previous frame">◀</button>
      <button className="topo-transport-play" onClick={props.onToggle}
        title={playing ? 'Pause' : 'Play'}>{playing ? '⏸' : '▶'}</button>
      <button onClick={props.onNext} disabled={frameIdx >= frameCount - 1} title="Next frame">▶❘</button>
      <input type="range" min={0} max={frameCount - 1} value={frameIdx}
        onChange={(e) => props.onScrub(parseInt(e.target.value, 10))} />
      <span className="topo-transport-frame">
        frame {frameIdx + 1}/{frameCount}
        {frameTime != null ? ` · t=${frameTime}` : ''}
      </span>
      <button className="topo-transport-exit" onClick={props.onExit}
        title="Exit playback (restore composite)">✕</button>
    </div>
  );
}
