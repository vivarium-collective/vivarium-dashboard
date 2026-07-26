// src/panels/NestingTree.tsx — recursive containment-tree renderer for the
// Processes panel. Shows the composite the way it's nested and lazily reveals a
// Composite Process's inner processes on expand (fetchInnerComposite — same
// payloads the drill-in mini-map uses, so it works live AND in static bundles).
//
// Leaves that are ON the current canvas (nodeId present) keep full affordances:
// checkbox (show/hide), row-click (focus + center), keep-open ★. Lazily-loaded
// inner leaves are informational (the canvas shows the outer composite); an
// inner Composite Process is itself expandable, so you can browse all the way
// down without drilling.

import { useCallback, useState } from 'react';
import { fetchInnerComposite } from '../api';
import { buildTreeFromState, type TreeNode } from '../layouts/nestingTree';
import type { UseFocus } from '../hooks/useFocus';

interface InnerState {
  loading: boolean;
  error?: string;
  children?: TreeNode[];
}

export interface NestingTreeProps {
  tree: TreeNode[];
  /** Root composite id — needed to fetch inner composites by hops. */
  rootId: string | null;
  /** Hops from the root generator to the current canvas level (drill prefix). */
  hopsPrefix?: string[][];
  focus: UseFocus;
  hiddenIds: Set<string>;
  /** Pinned ("preferred") node ids — the ★ toggles these; they float to the top
   *  in a Pinned section rendered by the parent panel. */
  pinnedIds?: Set<string>;
  onTogglePin?: (id: string) => void;
  onToggleHidden?: (id: string) => void;
  onNavigate: (nodeId: string) => void;
  /** Lowercased search query; when set, everything auto-expands to reveal hits. */
  query: string;
}

const INDENT = 12;

export function NestingTree(props: NestingTreeProps) {
  // Manual expand/collapse override, keyed by TreeNode.key. Absent = default
  // (groups open, composite leaves closed).
  const [open, setOpen] = useState<Record<string, boolean>>({});
  // Lazily-fetched inner composites, keyed by TreeNode.key.
  const [inner, setInner] = useState<Record<string, InnerState>>({});

  const loadInner = useCallback(
    async (key: string, hops: string[][]) => {
      if (!props.rootId) return;
      setInner((m) => (m[key]?.loading || m[key]?.children ? m : { ...m, [key]: { loading: true } }));
      try {
        const res = await fetchInnerComposite(props.rootId, hops);
        const children = buildTreeFromState(res?.state ?? res);
        setInner((m) => ({ ...m, [key]: { loading: false, children } }));
      } catch (e) {
        setInner((m) => ({ ...m, [key]: { loading: false, error: (e as Error).message } }));
      }
    },
    [props.rootId],
  );

  const q = props.query;

  const renderLevel = (nodes: TreeNode[], depth: number, parentHops: string[][]) => {
    // In search mode, drop branches with no matching descendant leaf.
    const visible = q ? nodes.filter((n) => subtreeMatches(n, q)) : nodes;

    return visible.map((node) => {
      const pad = { paddingLeft: depth * INDENT + 8 };
      if (node.kind === 'group') {
        const isOpen = q ? true : (open[node.key] ?? true);
        return (
          <div key={node.key} className="loom-tree-branch">
            <div
              className="loom-tree-row loom-tree-group"
              style={pad}
              role="button"
              aria-expanded={isOpen}
              onClick={() => setOpen((o) => ({ ...o, [node.key]: !isOpen }))}
            >
              <span className="loom-tree-caret">{isOpen ? '▾' : '▸'}</span>
              <span className="loom-tree-name">{node.label}</span>
              <span className="loom-tree-count">{node.processCount}</span>
            </div>
            {isOpen && renderLevel(node.children, depth + 1, parentHops)}
          </div>
        );
      }

      // Leaf: process / step.
      const focused = node.nodeId ? props.focus.ctx.focused.has(node.nodeId) : false;
      const pinned = node.nodeId ? !!props.pinnedIds?.has(node.nodeId) : false;
      const hidden = node.nodeId ? props.hiddenIds.has(node.nodeId) : false;
      const hops = [...parentHops, node.path];
      const hopKey = node.key;
      const inSt = inner[hopKey];
      const leafOpen = node.isComposite && !!(q ? true : open[hopKey]);

      const cls = 'loom-tree-row loom-tree-leaf'
        + (focused ? ' is-active' : '')
        + (hidden ? ' is-hidden' : '')
        + (node.nodeId ? '' : ' is-inner');

      const onRowClick = () => {
        if (node.isComposite) {
          const willOpen = !(open[hopKey] ?? false);
          setOpen((o) => ({ ...o, [hopKey]: willOpen }));
          if (willOpen && !inSt?.children && !inSt?.loading) loadInner(hopKey, hops);
        } else if (node.nodeId) {
          props.focus.select(node.nodeId);
          props.onNavigate(node.nodeId);
        }
      };

      return (
        <div key={node.key} className="loom-tree-branch">
          <div
            className={cls}
            style={pad}
            onMouseEnter={node.nodeId ? () => props.focus.hover(node.nodeId!) : undefined}
            onMouseLeave={node.nodeId ? () => props.focus.hover(null) : undefined}
            onClick={onRowClick}
            title={node.path.join(' / ')}
          >
            {node.isComposite
              ? <span className="loom-tree-caret">{leafOpen ? '▾' : '▸'}</span>
              : <span className="loom-tree-caret loom-tree-caret-empty" />}
            {props.onToggleHidden && node.nodeId && (
              <input
                type="checkbox"
                className="loom-tree-visible"
                checked={!hidden}
                title={hidden ? 'Show on canvas' : 'Hide from canvas'}
                aria-label={`Toggle ${node.label}`}
                onClick={(e) => e.stopPropagation()}
                onChange={() => props.onToggleHidden!(node.nodeId!)}
              />
            )}
            <span className="loom-tree-name">{node.label}</span>
            {node.isComposite && <span className="loom-tree-badge loom-badge-composite">composite</span>}
            {node.isOrphan && <span className="loom-tree-badge loom-badge-orphan" title="Uncategorized — matches no known subsystem">uncategorized</span>}
            {node.nodeId && props.onTogglePin && (
              <button
                type="button"
                className={`loom-tree-pin${pinned ? ' is-pinned' : ''}`}
                title={pinned ? 'Unpin' : 'Pin to top'}
                aria-pressed={pinned}
                onClick={(e) => { e.stopPropagation(); props.onTogglePin!(node.nodeId!); }}
              >
                {pinned ? '★' : '☆'}
              </button>
            )}
          </div>
          {node.isComposite && leafOpen && (
            <div className="loom-tree-inner">
              {inSt?.loading && <div className="loom-tree-note" style={{ paddingLeft: (depth + 1) * INDENT + 8 }}>loading inner composite…</div>}
              {inSt?.error && <div className="loom-tree-note loom-tree-err" style={{ paddingLeft: (depth + 1) * INDENT + 8 }}>{inSt.error}</div>}
              {inSt?.children && renderLevel(inSt.children, depth + 1, hops)}
            </div>
          )}
        </div>
      );
    });
  };

  if (!props.tree.length) return <div className="loom-tree-empty">No processes</div>;
  return <div className="loom-tree">{renderLevel(props.tree, 0, props.hopsPrefix ?? [])}</div>;
}

/** Whether a subtree contains a leaf whose label matches the query. */
function subtreeMatches(node: TreeNode, q: string): boolean {
  if (node.label.toLowerCase().includes(q)) return true;
  return node.children.some((c) => subtreeMatches(c, q));
}
