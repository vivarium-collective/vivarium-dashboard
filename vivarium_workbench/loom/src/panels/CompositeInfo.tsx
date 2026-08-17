// src/panels/CompositeInfo.tsx — the loom's TOP BAR: a full-width composite
// header (name · id · library · counts) with an expandable description, and a
// minimize toggle so it can shrink to a thin strip. Repurposes the old thin
// breadcrumb into the "what is this" surface the full workbench card shows.
import { useState } from 'react';

export interface CompositeInfoProps {
  name: string | null;
  description: string | null;
  compositeId?: string | null;
  library?: string | null;
  nProcesses?: number;
  nParams?: number;
  /** Start expanded (default). */
  defaultOpen?: boolean;
}

export function CompositeInfo(props: CompositeInfoProps) {
  const [open, setOpen] = useState(props.defaultOpen ?? true);
  const [hidden, setHidden] = useState(false);
  if (!props.name && !props.compositeId) return null;
  const title = props.name
    || (props.compositeId ? props.compositeId.split('.').pop()!.replace(/[-_]/g, ' ') : 'Composite');

  // Fully minimized → a hairline strip with a restore chip.
  if (hidden) {
    return (
      <div className="cinfobar cinfobar-hidden">
        <button type="button" className="cinfobar-restore" onClick={() => setHidden(false)}
          title="Show composite info">ⓘ {title} ▸</button>
      </div>
    );
  }

  const counts: string[] = [];
  if (props.nProcesses != null) counts.push(`${props.nProcesses} process${props.nProcesses === 1 ? '' : 'es'}`);
  if (props.nParams != null) counts.push(`${props.nParams} param${props.nParams === 1 ? '' : 's'}`);

  return (
    <div className={'cinfobar' + (open ? ' cinfobar-open' : '')}>
      <div className="cinfobar-row">
        <span className="cinfobar-i" aria-hidden="true">ⓘ</span>
        <span className="cinfobar-name" title={props.compositeId || undefined}>{title}</span>
        {props.compositeId && props.compositeId !== props.name && (
          <span className="cinfobar-id">{props.compositeId}</span>
        )}
        {props.library && <span className="cinfobar-lib">{props.library}</span>}
        {counts.length > 0 && <span className="cinfobar-counts">{counts.join(' · ')}</span>}
        <span className="cinfobar-actions">
          {props.description && (
            <button type="button" className="cinfobar-btn" onClick={() => setOpen((o) => !o)}
              title={open ? 'Hide details' : 'Show details'} aria-expanded={open}>
              {open ? 'Hide details ▾' : 'Details ▸'}
            </button>
          )}
          <button type="button" className="cinfobar-btn cinfobar-min" onClick={() => setHidden(true)}
            title="Minimize info bar" aria-label="Minimize">—</button>
        </span>
      </div>
      {open && props.description && (
        <div className="cinfobar-desc">{props.description}</div>
      )}
    </div>
  );
}
