import { memo, useEffect, useState } from "react";
import { Handle, Position, NodeResizer, useReactFlow, useNodeId, type NodeProps } from "@xyflow/react";
import type { StoreNodeData } from "../types";
import type { ZoomTierId } from "../layouts/types";
import { abbreviateType } from "../contract";

/** The four store handles + optional collapse indicator, shared by both the
 *  legacy (hierarchy) and the tiered (process-column) render paths. Edge
 *  attachment (Task 6 focus culling) depends on these handle ids, so they are
 *  present at every tier. */
function StoreHandles() {
  // Wiring convention:
  //   LEFT  source — store value flows OUT to a process's input (left of process)
  //   RIGHT target — store RECEIVES a process's output (right of process)
  //   TOP   target — place edge IN from parent store
  //   BOTTOM source — place edge OUT to child store
  return (
    <>
      <Handle type="target" position={Position.Top} id="top-place" />
      <Handle type="source" position={Position.Left} id="left-out" />
      <Handle type="target" position={Position.Right} id="right-in" />
      <Handle type="source" position={Position.Bottom} id="bottom-place" />
    </>
  );
}

function StoreNode({ data }: NodeProps & { data: StoreNodeData }) {
  const isCollapsed = (data as any).isCollapsed;
  const tierRaw = (data as any)._tier as ZoomTierId | undefined;

  // Manual resize: drag a corner to widen/enlarge the store, just like a
  // process card. Handles are hidden by CSS until the node is hovered.
  // Hand-set size persists on data._size (saved with the layout/default view);
  // local `dims` gives smooth drag feedback, seeded from + synced to it.
  const _rf = useReactFlow();
  const _nodeId = useNodeId();
  const savedSize = (data as any)._size as { width: number; height: number } | undefined;
  const [dims, setDims] = useState<{ width: number; height: number } | null>(savedSize ?? null);
  useEffect(() => {
    if (savedSize) setDims(savedSize);
  }, [savedSize?.width, savedSize?.height]);
  // Override the tier's max-width/height caps too, or the inline width can't
  // grow past them and a drag just shifts the box instead of widening it.
  const sizeStyle = dims
    ? { width: dims.width, height: dims.height, maxWidth: dims.width, maxHeight: dims.height }
    : undefined;
  const resizer = (
    <NodeResizer
      isVisible
      minWidth={72}
      minHeight={44}
      onResize={(_e, p) => setDims({ width: p.width, height: p.height })}
      onResizeEnd={(_e, p) => {
        if (_nodeId) _rf.setNodes((ns: any[]) => ns.map((n) =>
          n.id === _nodeId ? { ...n, data: { ...n.data, _size: { width: p.width, height: p.height } } } : n));
      }}
      handleClassName="loom-resize-handle"
      lineClassName="loom-resize-line"
    />
  );

  // Hyperedge marker (Milner view): the process is FULLY collapsed — no node
  // object at all, just a single point vertex where its (dashed) hyperedges
  // converge. All handles are centered on the point so every edge radiates from
  // it; the label sits just beneath.
  if ((data as any)._hyperedge) {
    return (
      <div className="loom-hyperedge" title={data.label}>
        <StoreHandles />
        <span className="loom-hyperedge-label">{data.label}</span>
      </div>
    );
  }

  // Hierarchy mode never stamps a tier — render the legacy circle unchanged so
  // that mode is byte-identical to before semantic zoom existed.
  if (tierRaw == null) {
    const hasValue = data.value !== undefined && data.value !== null;
    return (
      <div className={`store-node ${isCollapsed ? "store-node-collapsed" : ""}`} style={sizeStyle}>
        {resizer}
        <Handle type="target" position={Position.Top} id="top-place" />
        <Handle type="source" position={Position.Left} id="left-out" />
        <Handle type="target" position={Position.Right} id="right-in" />
        <div className="store-label">{data.label}</div>
        {hasValue && (
          <div className="store-value" title={String(data.value)}>
            {String(data.value).slice(0, 20)}
          </div>
        )}
        {(data as any).isGroup && isCollapsed && (
          <div className="collapse-indicator">▶</div>
        )}
        <Handle type="source" position={Position.Bottom} id="bottom-place" />
      </div>
    );
  }

  // Semantic zoom (process-column mode): the stamped tier decides WHICH rows
  // exist. Font size is constant across tiers (see App.css) — legibility at low
  // zoom comes from dropping content, never from shrinking text. A row with no
  // data is omitted, never rendered empty.
  const tier = tierRaw;
  const readers: string[] = (data as any)._readers ?? [];
  const writers: string[] = (data as any)._writers ?? [];
  // A hub store's wire fan is hidden in hierarchy mode; App flags it so the
  // reader/writer count can stand in for the wires at EVERY tier, not just
  // contract+ (where ordinary stores surface their wiring).
  const isHub: boolean = (data as any)._isHub === true;
  const rawType = typeof (data as any).valueType === "string" ? (data as any).valueType : "";

  const show = {
    value: tier !== "glyph",
    type: tier === "types" || tier === "config" || tier === "contract" || tier === "full",
    wiring: tier === "contract" || tier === "full" || isHub,
    full: tier === "full",
  };
  // Stores Detail override (the Detail menu) controls how much of a store shows:
  //   'name'  → just the label   'value' → + value   'type' → + value + type
  const _ov = (data as any)._detailOverrides as { stores?: string } | undefined;
  if (_ov) {
    if (_ov.stores === "name")  { show.value = false; show.type = false; }
    else if (_ov.stores === "value") { show.value = true;  show.type = false; }
    else if (_ov.stores === "type")  { show.value = true;  show.type = true; }
  }

  return (
    <div
      className={`store-node store-node-${tier} ${isCollapsed ? "store-node-collapsed" : ""} ${isHub ? "store-node-hub" : ""}`}
      style={sizeStyle}
    >
      {resizer}
      <StoreHandles />
      <div className="store-label">{data.label}</div>
      {show.value && data.value != null && (
        <div className="store-node-value">{String(data.value)}</div>
      )}
      {show.type && rawType && (
        <div className="store-node-type" title={rawType}>{abbreviateType(rawType)}</div>
      )}
      {show.wiring && (readers.length > 0 || writers.length > 0) && (
        <div className="store-node-wiring">
          {readers.length > 0 && <span>{readers.length} read</span>}
          {readers.length > 0 && writers.length > 0 && <span> · </span>}
          {writers.length > 0 && <span>{writers.length} write</span>}
        </div>
      )}
      {show.full && (data as any)._emitted && (
        <div className="store-node-emit">emitted</div>
      )}
      {(data as any).isGroup && (
        <div className="collapse-indicator">
          {isCollapsed ? "▶" : "▼"}
        </div>
      )}
    </div>
  );
}

export default memo(StoreNode);
