// src/Katex.tsx — typeset a LaTeX string with KaTeX.
//
// Process contracts carry their governing equations as LaTeX source
// (`_contract.math`). We render them as display-mode math so the card shows
// real typeset equations instead of monospace text. Invalid LaTeX degrades to
// the raw source (throwOnError:false) rather than blanking the card.
//
// A wide equation used to overflow the fixed-width card, so the box got an
// `overflow-x:auto` scrollbar — which, in the SVG/PNG figure export, rendered
// as a gray bar clipping the equation. Instead we measure the typeset width and
// scale the whole equation DOWN to fit the box: no scrollbar, no clipping, the
// full equation always visible.
import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import katex from 'katex';

export function KatexBlock({ tex }: { tex: string }) {
  const html = useMemo(
    () => katex.renderToString(tex, {
      throwOnError: false,
      displayMode: true,
      output: 'html',
      strict: false,
    }),
    [tex],
  );
  const wrapRef = useRef<HTMLDivElement>(null);
  // scale ≤ 1 shrinks a too-wide equation to fit; h keeps the layout box tight
  // to the scaled height so shrinking doesn't leave a gap below.
  const [fit, setFit] = useState<{ scale: number; h?: number }>({ scale: 1 });
  useLayoutEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const measure = () => {
      const disp = wrap.querySelector('.katex-display') as HTMLElement | null;
      if (!disp) { setFit({ scale: 1 }); return; }
      const avail = wrap.clientWidth;
      // scrollWidth is layout px, unaffected by React Flow's zoom transform.
      const natural = disp.scrollWidth;
      if (avail > 0 && natural > avail) {
        const s = avail / natural;
        setFit({ scale: s, h: disp.scrollHeight * s });
      } else {
        setFit({ scale: 1 });
      }
    };
    measure();
    // KaTeX math fonts load asynchronously; the equation widens once they do,
    // so the first measure (pre-font) under-reads the width and skips scaling.
    // Re-measure after fonts settle (and a short backstop tick) so the scale is
    // computed against the FINAL typeset width — this is what the headless
    // figure export depends on.
    try { (document as any).fonts?.ready?.then(() => measure()); } catch { /* no font API */ }
    const t = window.setTimeout(measure, 400);
    // Re-fit if the card is resized (manual node resize / relayout).
    const ro = new ResizeObserver(measure);
    ro.observe(wrap);
    return () => { window.clearTimeout(t); ro.disconnect(); };
  }, [html]);
  return (
    <div
      ref={wrapRef}
      className="katex-eq"
      style={{ overflow: 'hidden', height: fit.h }}
    >
      <div
        style={{
          transform: fit.scale < 1 ? `scale(${fit.scale})` : undefined,
          transformOrigin: 'top left',
        }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
