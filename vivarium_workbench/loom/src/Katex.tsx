// src/Katex.tsx — typeset a LaTeX string with KaTeX.
//
// Process contracts carry their governing equations as LaTeX source
// (`_contract.math`). We render them as display-mode math so the card shows
// real typeset equations instead of monospace text. Invalid LaTeX degrades to
// the raw source (throwOnError:false) rather than blanking the card.
import { useMemo } from 'react';
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
  return <div className="katex-eq" dangerouslySetInnerHTML={{ __html: html }} />;
}
