// src/panels/VisualizationsPanel.tsx — rendered Visualization step output
// from the most recent run. Each entry is the HTML produced by one viz step
// (Plotly + inline JS); we drop it into an iframe with `srcDoc` so its
// <script> blocks execute and don't leak into the bigraph-loom document.
import { zipSync, strToU8 } from 'fflate';

type VizPayload = string | { html: string };

export interface VisualizationsPanelProps {
  vizHtml: Record<string, VizPayload> | null;
  hasRun: boolean;
  readOnly?: boolean;
  /** Composite name/id — used to name the downloaded .zip. */
  baseName?: string;
}

function _payloadHtml(p: VizPayload): string {
  return typeof p === 'string' ? p : (p?.html || '');
}

/** Zip every rendered visualization (one self-contained .html each) and hand it
 *  to the browser as a single download. Uses fflate (already vendored) so it is
 *  purely client-side — no run-data round-trip to the server. */
function downloadVizZip(vizHtml: Record<string, VizPayload>, baseName?: string): void {
  const files: Record<string, Uint8Array> = {};
  const seen = new Set<string>();
  for (const [path, payload] of Object.entries(vizHtml)) {
    let name = (path.replace(/[^a-zA-Z0-9._-]/g, '_') || 'viz');
    if (!name.toLowerCase().endsWith('.html')) name += '.html';
    let unique = name;
    let i = 2;
    while (seen.has(unique)) { unique = name.replace(/\.html$/i, `_${i}.html`); i++; }
    seen.add(unique);
    files[unique] = strToU8(_payloadHtml(payload));
  }
  const zipped = zipSync(files, { level: 6 });
  const blob = new Blob([zipped as BlobPart], { type: 'application/zip' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${(baseName || 'composite').replace(/[^a-zA-Z0-9._-]/g, '_')}-visualizations.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function VisualizationsPanel({ vizHtml, hasRun, readOnly, baseName }: VisualizationsPanelProps) {
  const wrap: React.CSSProperties = { padding: 16, fontFamily: 'system-ui, sans-serif' };

  if (!vizHtml) {
    return (
      <div style={wrap}>
        <h3 style={{ marginTop: 0 }}>Visualizations</h3>
        <p style={{ color: '#6b7280' }}>
          {readOnly
            ? 'The read-only mirror does not include run data — run this composite in a live dashboard to see visualizations.'
            : hasRun ? 'Loading visualizations…' : 'No run yet — press ▶ Run above.'}
        </p>
      </div>
    );
  }

  const entries = Object.entries(vizHtml);
  if (entries.length === 0) {
    return (
      <div style={wrap}>
        <h3 style={{ marginTop: 0 }}>Visualizations</h3>
        <p style={{ color: '#6b7280' }}>
          Run complete — no visualizations declared by this composite.
        </p>
      </div>
    );
  }

  return (
    <div style={wrap}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 12, marginBottom: 10,
      }}>
        <h3 style={{ margin: 0 }}>Visualizations</h3>
        <button
          type="button"
          onClick={() => downloadVizZip(vizHtml, baseName)}
          title={`Download all ${entries.length} visualization${entries.length === 1 ? '' : 's'} as a .zip`}
          style={{
            fontSize: 13, fontWeight: 600, padding: '4px 11px', cursor: 'pointer',
            color: '#0d6e6b', background: '#fff',
            border: '1px solid #0d6e6b', borderRadius: 6, whiteSpace: 'nowrap',
          }}
        >
          ↓ Visualizations
        </button>
      </div>
      {entries.map(([path, payload]) => {
        const html = _payloadHtml(payload);
        return (
          <div key={path} style={{
            marginBottom: 16,
            border: '1px solid #e5e7eb', borderRadius: 4,
          }}>
            <div style={{
              padding: '6px 10px', background: '#f3f4f6',
              fontFamily: 'monospace', fontSize: 12,
            }}>
              {path}
            </div>
            <iframe
              srcDoc={html || '<p style="font-family:system-ui;color:#888;padding:12px">No HTML</p>'}
              style={{ width: '100%', height: '70vh', minHeight: 400, border: 0 }}
              sandbox="allow-scripts"
              title={`viz-${path}`}
            />
          </div>
        );
      })}
    </div>
  );
}
