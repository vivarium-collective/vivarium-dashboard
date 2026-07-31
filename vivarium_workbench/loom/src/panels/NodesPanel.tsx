// src/panels/NodesPanel.tsx — the hierarchical store-node tree.
//
// Extracted verbatim from the old right-sidebar "Nodes" tab so it can dock
// independently. Mirrors the store nesting (ported from bigraph-viz2's
// renderNodes/row): each row indents by depth, gets a ▸/▾ caret when it has
// children, and a show/hide checkbox that reflects EFFECTIVE visibility (OFF
// when the node or any ancestor is hidden). The big bulk/listeners subtrees
// start collapsed: only depth 0 is expanded by default.

import { useEffect, useMemo, useRef, useState } from 'react';
import { isHiddenByAncestor } from './filterHidden';

// --- store-node tree ------------------------------------------------------
//
// The loom's store node ids are `path.join('.')` (root is '<root>'); a node's
// parent is the store at `path.slice(0, -1)`. We build a tree from the FLAT list
// of store React Flow nodes, synthesizing intermediate group nodes for any path
// segment that has no explicit node so the nesting is always complete.

export interface NodeTreeNode {
  id: string;
  label: string;
  path: string[];
  /** Subtitle: the joined path, or a value-type hint. */
  sub: string;
  children: NodeTreeNode[];
}

function pathKey(path: string[]): string {
  return path.length ? path.join('.') : '<root>';
}

/**
 * Build a tree of the STORE nodes, nested by `data.path`. Processes are
 * excluded (they live in the Process panel). Intermediate path segments with no
 * explicit node are synthesized as group nodes. Returns a synthetic root whose
 * `children` are the top-level stores.
 */
export function buildNodeTree(nodes: any[]): NodeTreeNode {
  const stores = nodes.filter((n) => n.type === 'store');
  const byId = new Map<string, NodeTreeNode>();

  const root: NodeTreeNode = { id: '<root>', label: '<root>', path: [], sub: '', children: [] };
  byId.set('<root>', root);

  // Ensure a tree node exists for every prefix of `path`, wiring parents.
  const ensure = (path: string[], label: string, sub: string): NodeTreeNode => {
    const id = pathKey(path);
    const existing = byId.get(id);
    if (existing) {
      // A previously-synthesized group may now get its real label/subtitle.
      if (label) existing.label = label;
      if (sub) existing.sub = sub;
      return existing;
    }
    const node: NodeTreeNode = { id, label, path, sub, children: [] };
    byId.set(id, node);
    if (path.length > 0) {
      const parent = ensure(path.slice(0, -1), '', '');
      parent.children.push(node);
    } else {
      // path === [] is the root, already seeded above.
    }
    return node;
  };

  for (const n of stores) {
    const path: string[] = n.data?.path ?? [];
    if (path.length === 0) continue;  // the root itself, already present
    const label: string = n.data?.label ?? path[path.length - 1];
    const sub: string = path.join('.');
    ensure(path, label, sub);
  }

  return root;
}

function countTree(node: NodeTreeNode): number {
  let n = 0;
  for (const c of node.children) n += 1 + countTree(c);
  return n;
}

export interface NodesPanelProps {
  nodes: any[];
  hidden: Set<string>;
  onToggleHidden: (id: string) => void;
  onShowAll: (kind: 'process' | 'store') => void;
  /** Store node id (`path.join('.')`) clicked on the canvas — its row is
   *  expanded-to, scrolled into view and highlighted so it's easy to toggle. */
  selectedId?: string | null;
  /** Bumped on every canvas click so re-clicking the same node re-reveals it. */
  revealNonce?: number;
}

export function NodesPanel(props: NodesPanelProps) {
  const tree = useMemo(() => buildNodeTree(props.nodes), [props.nodes]);

  // Default expansion: top-level stores only (depth 0). This keeps deep stores
  // like `bulk` / `listeners` collapsed for performance on big composites.
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(tree.children.map((c) => c.id)),
  );

  // Re-seed the default expansion when the underlying composite changes (the
  // top-level store ids will differ). Keyed on the joined top-level ids.
  const topIds = tree.children.map((c) => c.id).join('|');
  useEffect(() => {
    setExpanded(new Set(tree.children.map((c) => c.id)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topIds]);

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Reveal a canvas-clicked STORE in the tree: expand its ancestor groups so the
  // row is visible, then scroll it into view (+ highlight, below). Processes
  // aren't in this tree, so a process click is a no-op here.
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const selectedId = props.selectedId ?? null;
  useEffect(() => {
    if (!selectedId) return;
    const parts = selectedId.split('.');
    setExpanded((prev) => {
      const next = new Set(prev);
      for (let i = 1; i < parts.length; i++) next.add(parts.slice(0, i).join('.'));
      return next;
    });
    const t = setTimeout(() => {
      rowRefs.current.get(selectedId)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }, 40);
    return () => clearTimeout(t);
  }, [props.revealNonce, selectedId]);

  const total = countTree(tree);

  // Flatten the visible (expanded) rows top-down into render specs.
  const rows: { node: NodeTreeNode; depth: number; hasChildren: boolean; open: boolean }[] = [];
  const walk = (node: NodeTreeNode, depth: number) => {
    for (const child of node.children) {
      const hasChildren = child.children.length > 0;
      const open = expanded.has(child.id);
      rows.push({ node: child, depth, hasChildren, open });
      if (hasChildren && open) walk(child, depth + 1);
    }
  };
  walk(tree, 0);

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <button
          onClick={() => props.onShowAll('store')}
          style={{
            background: 'transparent', border: 0, padding: 0,
            color: '#2563eb', fontSize: 12, cursor: 'pointer',
            textDecoration: 'underline',
          }}
        >
          Show all
        </button>
      </div>
      {total === 0 && <p style={{ color: '#888', fontSize: 12 }}>None.</p>}
      {rows.map(({ node, depth, hasChildren, open }) => {
        // EFFECTIVE visibility: off when the node OR any ancestor is hidden.
        const ancHidden = isHiddenByAncestor(node.path.slice(0, -1), props.hidden);
        const effectivelyHidden = props.hidden.has(node.id) || ancHidden;
        const isSelected = node.id === selectedId;
        return (
          <div
            key={node.id}
            ref={(el) => { if (el) rowRefs.current.set(node.id, el); }}
            style={{
              display: 'flex', alignItems: 'flex-start', gap: 4,
              padding: '3px 4px', paddingLeft: depth * 14 + 4, fontSize: 12,
              background: isSelected ? '#eff6ff' : undefined,
              borderRadius: isSelected ? 4 : undefined,
              boxShadow: isSelected ? 'inset 2px 0 0 #2563eb' : undefined,
            }}
          >
            {/* expand caret (or a spacer to keep checkboxes aligned) */}
            {hasChildren ? (
              <span
                onClick={() => toggleExpand(node.id)}
                title={open ? 'Collapse' : 'Expand'}
                style={{
                  cursor: 'pointer', color: '#6b7280', width: 12,
                  textAlign: 'center', userSelect: 'none', lineHeight: '16px',
                }}
              >
                {open ? '▾' : '▸'}
              </span>
            ) : (
              <span style={{ width: 12, flex: '0 0 12px' }} />
            )}
            <input
              type="checkbox"
              checked={!effectivelyHidden}
              disabled={ancHidden}
              onChange={() => props.onToggleHidden(node.id)}
              title={ancHidden ? 'Hidden because an ancestor is hidden' : undefined}
              style={{ marginTop: 2, cursor: ancHidden ? 'default' : 'pointer' }}
            />
            <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
              <span style={{ color: effectivelyHidden ? '#9ca3af' : '#111827' }}>
                {node.label}
              </span>
              {node.sub && (
                <span style={{
                  fontFamily: 'monospace', fontSize: 11, color: '#9ca3af',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {node.sub}
                </span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
