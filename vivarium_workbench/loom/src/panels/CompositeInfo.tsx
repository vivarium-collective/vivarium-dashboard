// src/panels/CompositeInfo.tsx — a collapsible info panel pinned at the top of
// the Explore graph. Surfaces the composite's name + description (the "what is
// this / how does it behave" the full workbench card shows) INSIDE the loom, so
// it's available even in the chromeless / header=off embed. Collapsed to a slim
// "ⓘ name" pill by default; click to expand the description.
import { useState } from 'react';

export interface CompositeInfoProps {
  name: string | null;
  description: string | null;
  library?: string | null;
  /** Start expanded (default collapsed to the pill). */
  defaultOpen?: boolean;
}

export function CompositeInfo(props: CompositeInfoProps) {
  const [open, setOpen] = useState(!!props.defaultOpen);
  if (!props.name && !props.description) return null;
  const title = props.name || 'Composite';
  return (
    <div className={'cinfo' + (open ? ' cinfo-open' : '')}>
      <button type="button" className="cinfo-bar" onClick={() => setOpen((o) => !o)}
        title={open ? 'Hide details' : 'Show details'} aria-expanded={open}>
        <span className="cinfo-i" aria-hidden="true">ⓘ</span>
        <span className="cinfo-title">{title}</span>
        {props.library && <span className="cinfo-lib">{props.library}</span>}
        <span className="cinfo-chevron" aria-hidden="true">{open ? '▾' : '▸'}</span>
      </button>
      {open && props.description && (
        <div className="cinfo-body">{props.description}</div>
      )}
    </div>
  );
}
